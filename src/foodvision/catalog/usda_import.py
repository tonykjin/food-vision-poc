"""Idempotent import of a documented FoodData Central subset into food_catalog.

Keeps the FDC ID, data type, source release, name, preparation, reference basis, nutrient
IDs/names/units and portions. Never invents values: missing nutrients are stored as NULL,
portions without a gram weight are skipped, and every skip is counted in the report.
Re-importing the same (FDC ID, source_version) replaces that record and its children.
"""

import hashlib
import json
import zipfile
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, delete, insert, select, update

from foodvision.catalog.preparation import preparation_state, preparation_text
from foodvision.data.models import food_nutrients, food_portions, food_records

PROVIDER = "USDA"
DATASET_KEYS = {
    "FoundationFoods": "Foundation",
    "SRLegacyFoods": "SR Legacy",
    "BrandedFoods": "Branded",
}
# Result nutrient -> FDC nutrient IDs in precedence order (catalog/usda-subset-v1.json).
NUTRIENT_PRECEDENCE: dict[str, tuple[int, ...]] = {
    "energy": (2048, 2047, 1008),
    "protein": (1003,),
    "fat": (1004, 1085),
    "carbohydrate": (1005, 1050),
}
EXPECTED_UNITS = {"energy": "kcal", "protein": "g", "fat": "g", "carbohydrate": "g"}
GRAM_UNITS = {"g", "grm", "gram", "grams"}
ML_UNITS = {"ml", "mlt", "milliliter", "milliliters"}


class UnsupportedDataset(ValueError):
    pass


@dataclass
class ImportReport:
    source_version: str
    data_type: str | None = None
    entries: int = 0
    null_entries: int = 0
    inserted: int = 0
    replaced: int = 0
    skipped: Counter = field(default_factory=Counter)
    missing_nutrients: Counter = field(default_factory=Counter)
    rejected_negative: Counter = field(default_factory=Counter)  # never clamped to 0
    nutrient_sources: Counter = field(default_factory=Counter)
    portions: int = 0
    portions_skipped: Counter = field(default_factory=Counter)
    preparation_states: Counter = field(default_factory=Counter)

    def as_dict(self) -> dict[str, Any]:
        return {k: dict(v) if isinstance(v, Counter) else v for k, v in self.__dict__.items()}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_dataset(path: Path) -> tuple[str, list[Any]]:
    """Read an official FDC JSON download (.zip or .json). Returns (data_type, entries)."""
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if n.endswith(".json")]
            if len(names) != 1:
                raise UnsupportedDataset(f"expected one JSON file in {path.name}, found {names}")
            payload = json.loads(archive.read(names[0]))
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
    keys = [k for k in payload if k in DATASET_KEYS]
    if len(keys) != 1:
        raise UnsupportedDataset(f"unsupported FDC dataset keys {list(payload)}")
    return DATASET_KEYS[keys[0]], payload[keys[0]]


def _select_nutrients(raw_nutrients: list[Any], report: ImportReport) -> list[dict[str, Any]]:
    by_id: dict[int, dict[str, Any]] = {}
    for entry in raw_nutrients or []:
        nutrient = (entry or {}).get("nutrient") or {}
        if nutrient.get("id") is not None:
            by_id.setdefault(int(nutrient["id"]), entry)
    rows = []
    for name, ids in NUTRIENT_PRECEDENCE.items():
        chosen = None
        for nutrient_id in ids:
            entry = by_id.get(nutrient_id)
            if entry is None or entry.get("amount") is None:
                continue
            if (entry["nutrient"].get("unitName") or "").lower() != EXPECTED_UNITS[name]:
                continue
            if float(entry["amount"]) < 0:
                # e.g. carbohydrate "by difference" can come out negative; not clamped to 0.
                report.rejected_negative[f"{name}:{nutrient_id}"] += 1
                continue
            chosen = (nutrient_id, entry)
            break
        if chosen is None:
            report.missing_nutrients[name] += 1
            rows.append(
                {
                    "nutrient": name,
                    "amount": None,
                    "unit": EXPECTED_UNITS[name],
                    "source_nutrient_id": None,
                    "source_nutrient_name": None,
                }
            )
            continue
        nutrient_id, entry = chosen
        report.nutrient_sources[f"{name}:{nutrient_id}"] += 1
        rows.append(
            {
                "nutrient": name,
                "amount": float(entry["amount"]),
                "unit": EXPECTED_UNITS[name],
                "source_nutrient_id": nutrient_id,
                "source_nutrient_name": entry["nutrient"].get("name"),
            }
        )
    return rows


def _portion_name(portion: dict[str, Any]) -> str:
    unit = (portion.get("measureUnit") or {}).get("name") or ""
    modifier = (portion.get("modifier") or "").strip()
    description = (portion.get("portionDescription") or "").strip()
    amount = portion.get("amount")
    if unit == "RACC":
        return "RACC (reference amount customarily consumed)"
    label = description or " ".join(
        x for x in (unit if unit != "undetermined" else "", modifier) if x
    )
    label = label or "portion"
    return f"{amount:g} {label}" if isinstance(amount, (int, float)) and not description else label


def _generic_portions(raw: list[Any], report: ImportReport) -> list[dict[str, Any]]:
    rows, seen = [], Counter()
    for portion in raw or []:
        if not portion:
            continue
        gram_weight = portion.get("gramWeight")
        if not isinstance(gram_weight, (int, float)) or gram_weight <= 0:
            report.portions_skipped["no_gram_weight"] += 1  # never inferred from the measure
            continue
        name = _portion_name(portion)
        seen[name] += 1
        if seen[name] > 1:
            name = f"{name} [{seen[name]}]"
        unit = (portion.get("measureUnit") or {}).get("name")
        rows.append(
            {
                "portion_name": name,
                "quantity": portion.get("amount"),
                "measure_unit": unit,
                "modifier": portion.get("modifier") or None,
                "gram_weight": float(gram_weight),
                "portion_source": "racc" if unit == "RACC" else "source_data",
            }
        )
    return rows


def _branded_basis_and_portions(raw: dict[str, Any], report: ImportReport):
    unit = (raw.get("servingSizeUnit") or "").strip().lower()
    size = raw.get("servingSize")
    household = (raw.get("householdServingFullText") or "").strip()
    if unit in GRAM_UNITS:
        basis = ("per_100g", 100, "g")
        if isinstance(size, (int, float)) and size > 0:
            label = f"1 serving (label: {household})" if household else "1 serving (label)"
            portions = [
                {
                    "portion_name": label,
                    "quantity": 1,
                    "measure_unit": "serving",
                    "modifier": household or None,
                    "gram_weight": float(size),
                    "portion_source": "branded_label_serving",
                }
            ]
        else:
            portions = []
            report.portions_skipped["branded_serving_missing"] += 1
    elif unit in ML_UNITS:
        basis = ("per_100ml", 100, "ml")
        portions = []  # an ml serving has no gram weight without a supported density
        report.portions_skipped["branded_serving_ml_no_density"] += 1
    else:
        return None, []
    return basis, portions


def _published(raw: dict[str, Any]) -> date | None:
    value = raw.get("publicationDate") or raw.get("publishedDate")
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date() if value else None
        except ValueError:
            continue
    return None


def import_entries(
    conn: Connection,
    entries: Iterable[Any],
    *,
    data_type: str,
    source_version: str,
    retrieved_at: datetime | None = None,
    is_synthetic: bool = False,
) -> ImportReport:
    report = ImportReport(source_version=source_version, data_type=data_type)
    for raw in entries:
        report.entries += 1
        if not raw:
            report.null_entries += 1
            continue
        fdc_id, name = raw.get("fdcId"), (raw.get("description") or "").strip()
        if fdc_id is None or not name:
            report.skipped["missing_id_or_name"] += 1
            continue
        if (raw.get("dataType") or data_type) != data_type:
            report.skipped["unexpected_data_type"] += 1
            continue
        if data_type == "Branded":
            basis, portions = _branded_basis_and_portions(raw, report)
            if basis is None:
                report.skipped["branded_unknown_serving_unit"] += 1
                continue
            category = raw.get("brandedFoodCategory")
            brand = raw.get("brandName") or raw.get("brandOwner")
        else:
            basis, portions = (
                ("per_100g", 100, "g"),
                _generic_portions(raw.get("foodPortions"), report),
            )
            category = (raw.get("foodCategory") or {}).get("description")
            brand = None

        state = preparation_state(name)
        report.preparation_states[state.value] += 1
        record = {
            "data_type": data_type,
            "name": name,
            "preparation": preparation_text(name),
            "preparation_state": state.value,
            "brand": brand,
            "region": "US",
            "category": category,
            "published_date": _published(raw),
            "retrieved_at": retrieved_at,
            "basis_kind": basis[0],
            "basis_quantity": basis[1],
            "basis_unit": basis[2],
            "is_synthetic": is_synthetic,
        }
        nutrients = _select_nutrients(raw.get("foodNutrients"), report)

        key = (
            (food_records.c.provider == PROVIDER)
            & (food_records.c.provider_food_id == str(fdc_id))
            & (food_records.c.source_version == source_version)
        )
        existing = conn.execute(select(food_records.c.food_id).where(key)).scalar_one_or_none()
        if existing is None:
            food_id = conn.execute(
                insert(food_records)
                .values(
                    provider=PROVIDER,
                    provider_food_id=str(fdc_id),
                    source_version=source_version,
                    **record,
                )
                .returning(food_records.c.food_id)
            ).scalar_one()
            report.inserted += 1
        else:
            food_id = existing
            conn.execute(
                update(food_records).where(food_records.c.food_id == food_id).values(**record)
            )
            conn.execute(delete(food_nutrients).where(food_nutrients.c.food_id == food_id))
            conn.execute(delete(food_portions).where(food_portions.c.food_id == food_id))
            report.replaced += 1
        conn.execute(insert(food_nutrients), [{"food_id": food_id, **n} for n in nutrients])
        if portions:
            conn.execute(insert(food_portions), [{"food_id": food_id, **p} for p in portions])
            report.portions += len(portions)
    return report


def import_dataset_file(
    conn: Connection, path: Path, *, source_version: str, expected_sha256: str | None = None
) -> ImportReport:
    if expected_sha256 is not None and sha256_file(path) != expected_sha256:
        raise UnsupportedDataset(f"{path.name} does not match the documented SHA-256")
    data_type, entries = load_dataset(path)
    return import_entries(conn, entries, data_type=data_type, source_version=source_version)
