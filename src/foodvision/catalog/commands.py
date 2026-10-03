"""CLI handlers: import-usda, import-usda-api and catalog-report.

Catalog writes need the owner/migration role (the inference role can only read the catalog),
so these commands use MIGRATION_DATABASE_URL. Reports are printed and written under the
git-ignored work/ folder.
"""

import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, text

from foodvision.catalog.preparation import PreparationState
from foodvision.catalog.usda_import import import_dataset_file, sha256_file
from foodvision.matching.retrieval import CatalogTools
from foodvision.measurement.spans import ScanRecorder

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SUBSET = ROOT / "catalog" / "usda-subset-v1.json"
DEFAULT_PROBES = ROOT / "catalog" / "pilot-probes.json"
WORK = ROOT / "work" / "catalog"


def _database_url() -> str:
    url = os.environ.get("MIGRATION_DATABASE_URL")
    if not url:
        raise SystemExit("Set MIGRATION_DATABASE_URL (catalog writes need the owner role).")
    return url


def _write_report(name: str, payload: dict) -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    path = WORK / name
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def import_usda(dataset: str, version: str, subset: str | None = None) -> int:
    path = Path(dataset)
    manifest = json.loads(Path(subset or DEFAULT_SUBSET).read_text(encoding="utf-8"))
    entry = next((d for d in manifest["downloads"] if d["file"] == path.name), None)
    if entry is None:
        raise SystemExit(
            f"{path.name} is not listed in {manifest['subset_version']}; document it first"
        )
    if entry["source_version"] != version:
        raise SystemExit(
            f"--version {version!r} differs from documented {entry['source_version']!r}"
        )
    if sha256_file(path) != entry["sha256"]:
        raise SystemExit(f"{path.name} SHA-256 does not match the documented release")
    engine = create_engine(_database_url())
    with engine.begin() as conn:
        report = import_dataset_file(conn, path, source_version=version)
    engine.dispose()
    payload = {"subset_version": manifest["subset_version"], "file": path.name, **report.as_dict()}
    out = _write_report(f"import-{version}.json", payload)
    print(json.dumps(payload, indent=2, default=str))
    print(f"report written to {out}")
    return 0


def catalog_report(probes: str | None = None) -> int:
    probe_list = json.loads(Path(probes or DEFAULT_PROBES).read_text(encoding="utf-8"))["probes"]
    engine = create_engine(_database_url())
    with engine.connect() as conn:
        counts = [
            dict(r._mapping)
            for r in conn.execute(
                text(
                    "SELECT data_type, source_version, count(*) AS foods, "
                    "count(*) FILTER (WHERE preparation_state = 'ambiguous') "
                    "AS ambiguous_preparation "
                    "FROM food_catalog.food_records GROUP BY 1, 2 ORDER BY 1, 2"
                )
            )
        ]
        missing = [
            dict(r._mapping)
            for r in conn.execute(
                text(
                    "SELECT r.data_type, n.nutrient, count(*) AS records_missing FROM "
                    "food_catalog.food_nutrients n "
                    "JOIN food_catalog.food_records r USING (food_id) "
                    "WHERE n.amount IS NULL GROUP BY 1, 2 ORDER BY 1, 2"
                )
            )
        ]
        no_portions = conn.execute(
            text(
                "SELECT count(*) FROM food_catalog.food_records r WHERE NOT EXISTS ("
                "SELECT 1 FROM food_catalog.food_portions p WHERE p.food_id = r.food_id)"
            )
        ).scalar_one()
        tools = CatalogTools(conn)
        probe_results, outcome_counts = [], Counter()
        for probe in probe_list:
            prep = PreparationState(probe["preparation"]) if probe["preparation"] else None
            outcome = tools.search_foods(probe["query"], prep)
            status = (
                outcome.no_match_reason.value
                if not outcome.matched
                else f"matched_{outcome.candidates[0].match_mode}"
            )
            outcome_counts[status] += 1
            probe_results.append(
                {
                    **probe,
                    "status": status,
                    "top": [
                        f"{c.food_id} {c.name} [{c.data_type}]" for c in outcome.candidates[:3]
                    ],
                }
            )
    engine.dispose()
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "records": counts,
        "missing_nutrients": missing,
        "records_without_portions": no_portions,
        "probe_outcomes": dict(outcome_counts),
        "probes": probe_results,
    }
    out = _write_report("catalog-report.json", payload)
    print(json.dumps(payload, indent=2))
    print(f"report written to {out}")
    return 0


def import_usda_api(fdc_ids: str | None = None, subset: str | None = None) -> int:
    """Fetch documented Branded FDC IDs via the API and import them with a retrieval stamp."""
    import uuid

    from foodvision.catalog.usda_import import import_entries
    from foodvision.config import AppKind, load_settings
    from foodvision.measurement.budget import BudgetPolicy
    from foodvision.measurement.events import ScanStatus
    from foodvision.providers.usda_client import UsdaClient

    manifest = json.loads(Path(subset or DEFAULT_SUBSET).read_text(encoding="utf-8"))
    documented = [int(x["fdc_id"]) for x in manifest["branded_api_fdc_ids"]]
    ids = [int(x) for x in fdc_ids.split(",")] if fdc_ids else documented
    undocumented = sorted(set(ids) - set(documented))
    if undocumented:
        raise SystemExit(
            f"FDC IDs {undocumented} are not documented in {manifest['subset_version']}"
        )
    settings = load_settings(AppKind.AGENT)  # reads USDA_API_KEY; the value is never printed
    if settings.usda_api_key is None:
        raise SystemExit("USDA_API_KEY is missing (foodvision doctor --app agent)")

    retrieved_at = datetime.now(UTC)
    version = f"fdc-api-branded-{retrieved_at:%Y-%m-%d}"
    recorder = ScanRecorder(
        f"usda-import-{uuid.uuid4().hex[:8]}",
        "catalog_import",
        budget=BudgetPolicy(deadline_s=120, max_model_calls=0, max_attempts=10),
    )
    client = UsdaClient(settings.usda_api_key.get_secret_value())
    try:
        foods = client.fetch_foods(ids, recorder)
        record = recorder.finish(ScanStatus.COMPLETE)
    except Exception as exc:
        record = recorder.finish(ScanStatus.FAILED, getattr(exc, "code", None))
        print(json.dumps({"failed": type(exc).__name__, "attempts": record.attempts}, indent=2))
        return 1
    returned = {int(f["fdcId"]) for f in foods if f and f.get("fdcId") is not None}
    engine = create_engine(_database_url())
    with engine.begin() as conn:
        report = import_entries(
            conn, foods, data_type="Branded", source_version=version, retrieved_at=retrieved_at
        )
    engine.dispose()
    payload = {
        "subset_version": manifest["subset_version"],
        "source": "FDC API POST /v1/foods",
        "retrieved_at": retrieved_at.isoformat(),
        "requested": ids,
        "not_returned": sorted(set(ids) - returned),
        "telemetry": {
            "attempts": record.attempts,
            "retries": record.retries,
            "server_total_ms": record.server_total_ms,
            "outcomes": [a.outcome.value for a in record.attempt_records],
        },
        **report.as_dict(),
    }
    out = _write_report(f"import-{version}.json", payload)
    print(json.dumps(payload, indent=2, default=str))
    print(f"report written to {out}")
    return 0
