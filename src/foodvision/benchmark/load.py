"""Load reviewed manifest groups into the evaluator-only `benchmark` schema (POC-12).

Runs only as an evaluator login: refuses superusers, inference logins and any database where
the inference role can read benchmark tables. One `benchmark.samples` row per photo; all
photos of a group share its split and reference. Re-loading a group under the same
reference_version replaces it (idempotent). Photo bytes go to the private object store; the
database keeps hashes, consent and retention only.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import Connection, delete, insert, select, text

from foodvision.benchmark.manifest import Group, reference_totals
from foodvision.data.models import images, reference_items, reference_nutrients, samples
from foodvision.data.object_store import LocalObjectStore, store_image

NUTRIENT_UNITS = {"energy_kcal": "kcal", "protein_g": "g", "carbohydrate_g": "g", "fat_g": "g"}
BENCHMARK_TABLES = ("samples", "reference_items", "reference_nutrients")


class EvaluatorAuthorizationError(PermissionError):
    pass


def check_evaluator(conn: Connection) -> str:
    role = conn.execute(text("SELECT current_user")).scalar_one()
    if conn.execute(
        text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
    ).scalar_one():
        raise EvaluatorAuthorizationError(f"{role!r} is a superuser; use an fv_evaluator login")
    member = "SELECT pg_has_role(current_user, :group, 'MEMBER')"
    if not conn.execute(text(member), {"group": "fv_evaluator"}).scalar_one():
        raise EvaluatorAuthorizationError(f"{role!r} is not an fv_evaluator login")
    if conn.execute(text(member), {"group": "fv_inference"}).scalar_one():
        raise EvaluatorAuthorizationError(f"{role!r} is also an inference login")
    leaked = [
        table
        for table in BENCHMARK_TABLES
        if conn.execute(
            text("SELECT has_table_privilege('fv_inference', :t, 'SELECT')"),
            {"t": f"benchmark.{table}"},
        ).scalar_one()
    ]
    if leaked:
        raise EvaluatorAuthorizationError(f"fv_inference can read benchmark tables: {leaked}")
    return role


@dataclass
class LoadSummary:
    groups: int = 0
    samples: int = 0
    new_images: int = 0
    skipped: list[str] | None = None


def _image_id(conn, store, data_dir: Path, photo, is_synthetic: bool, now: datetime, out):
    existing = conn.execute(
        select(images.c.image_id).where(
            images.c.original_sha256 == photo.sha256, images.c.deleted_at.is_(None)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    days = (photo.retain_until - now.date()).days
    if days <= 0:
        raise ValueError(f"photo {photo.photo_id}: retain_until {photo.retain_until} has passed")
    stored = store_image(
        conn,
        store,
        (data_dir / photo.file).read_bytes(),
        consent_basis=f"{photo.rights.value}: {photo.consent_reference}",
        retention_days=days,
        now=now,
        is_synthetic=is_synthetic,
    )
    out.new_images += 1
    return stored.image_id


def _component_rows(group: Group, reviewers: str) -> list[dict]:
    if group.recipe is not None:
        return [
            {
                "verified_identity": group.recipe.dish_identity,
                "preparation": None,
                "edible_grams": group.recipe.served_grams,
                "reference_source": "recipe (ingredients x served/cooked yield)",
                "reviewer": reviewers,
            }
        ]
    return [
        {
            "verified_identity": c.identity,
            "preparation": c.preparation.value,
            "edible_grams": c.edible_grams,
            "reference_source": (
                f"{c.values.source.value}:{c.values.source_ref}@{c.values.source_version}"
                if c.values
                else f"missing ({c.measurement.value})"
            ),
            "reviewer": reviewers,
        }
        for c in group.components
    ]


def load_groups(
    conn: Connection,
    store: LocalObjectStore,
    groups: list[Group],
    data_dir: Path,
    reference_version: str,
    now: datetime,
) -> LoadSummary:
    """Load reviewed groups that have a split. Callers must validate the manifest first."""
    check_evaluator(conn)
    summary = LoadSummary(skipped=[])
    for group in groups:
        if group.review.status != "reviewed" or group.split is None:
            summary.skipped.append(group.group_id)
            continue
        conn.execute(
            delete(samples).where(
                samples.c.group_id == group.group_id,
                samples.c.reference_version == reference_version,
            )
        )
        totals = reference_totals(group)
        reviewers = "; ".join(r.reviewer for r in group.review.reviewers)
        for photo in group.photos:
            # Versioned ID: an older (possibly locked) reference version is never overwritten.
            sample_id = f"{group.group_id}:{photo.photo_id}@{reference_version}"
            image_id = _image_id(conn, store, data_dir, photo, group.is_synthetic, now, summary)
            conn.execute(
                insert(samples).values(
                    sample_id=sample_id,
                    image_id=image_id,
                    group_id=group.group_id,
                    category=group.category.value,
                    split=group.split.value,
                    expected_outcome=group.expected_outcome.value,
                    reference_version=reference_version,
                    is_synthetic=group.is_synthetic,
                )
            )
            for row in _component_rows(group, reviewers):
                conn.execute(insert(reference_items).values(sample_id=sample_id, **row))
            if totals is not None:
                for key, unit in NUTRIENT_UNITS.items():
                    conn.execute(
                        insert(reference_nutrients).values(
                            sample_id=sample_id,
                            nutrient=key,
                            amount=getattr(totals.nutrients, key),
                            unit=unit,
                            method=totals.method,
                            quality_grade=group.quality_grade.value,
                        )
                    )
            summary.samples += 1
        summary.groups += 1
    return summary
