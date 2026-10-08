"""Empirical calibration of the frozen heuristic confidence buckets (plan §11, POC-15).

Fits on the **calibration split only** (the DB table also refuses `test`). For each heuristic
label (low/medium/high), the success event is the frozen useful-result event; the pass rate is
useful attempts / attempts on scorable references, and its interval resamples whole groups.
A rate is shown only when the bucket has at least MIN_GROUPS independent groups; otherwise the
bucket stays "insufficient data" and the label remains uncalibrated. High-confidence attempts
that were not useful are listed for human review.
"""

from collections.abc import Sequence

from foodvision.benchmark.metrics import (
    ABSOLUTE_FLOOR,
    RELATIVE_TOLERANCE,
    USEFUL_DEFINITION,
    Attempt,
    Reference,
    group_bootstrap,
    is_useful,
)

MIN_GROUPS = 30  # plan §11 suggested minimum of independent groups per bucket
BUCKETS = ("low", "medium", "high", "not_assessed")


def bucket_of(attempt: Attempt) -> str:
    confidence = attempt.result.confidence if attempt.result is not None else None
    label = confidence.label.value if confidence is not None and confidence.label else None
    return label or "not_assessed"


def calibrate(
    attempts: Sequence[Attempt], refs: dict[str, Reference], version: str, split: str
) -> dict:
    if split != "calibration":
        raise ValueError(f"calibration fits on the calibration split only, not {split!r}")
    scorable = [a for a in attempts if refs[a.group_id].scorable and a.result is not None]
    bins, rates, uncertainty, status, false_high = {}, {}, {}, {}, []
    for bucket in BUCKETS:
        members = [a for a in scorable if bucket_of(a) == bucket]
        groups = {a.group_id for a in members}
        useful = [a for a in members if is_useful(a, refs[a.group_id])]
        bins[bucket] = {"attempts": len(members), "groups": len(groups), "useful": len(useful)}
        if len(groups) >= MIN_GROUPS:
            rates[bucket] = len(useful) / len(members)
            uncertainty[bucket] = group_bootstrap(
                members,
                lambda s: sum(is_useful(a, refs[a.group_id]) for a in s) / len(s) if s else None,
            )
            status[bucket] = "calibrated"
        else:
            rates[bucket], uncertainty[bucket] = None, None
            status[bucket] = f"insufficient data ({len(groups)} < {MIN_GROUPS} groups)"
        if bucket == "high":
            false_high = sorted(
                {a.sample_id for a in members if not is_useful(a, refs[a.group_id])}
            )
    return {
        "version": version,
        "fitting_split": "calibration",
        "success_definition": (
            f"{USEFUL_DEFINITION}: complete result, every nutrient within "
            f"max(floor, relative x reference); floor {ABSOLUTE_FLOOR}, "
            f"relative {RELATIVE_TOLERANCE}"
        ),
        "unit": "group (all photos and repeats of one meal resampled together)",
        "min_groups_per_bucket": MIN_GROUPS,
        "bin_counts": bins,
        "rates": rates,
        "uncertainty": {k: list(v) if v else None for k, v in uncertainty.items()},
        "status": status,
        "false_high_confidence_for_review": false_high,
    }


def save_calibration(conn, record: dict) -> None:
    """Persist a calibration version (evaluator login only)."""
    from sqlalchemy import insert

    from foodvision.benchmark.load import check_evaluator
    from foodvision.data.models import calibration_versions

    check_evaluator(conn)
    conn.execute(
        insert(calibration_versions).values(
            version=record["version"],
            fitting_split=record["fitting_split"],
            success_definition=record["success_definition"],
            bin_counts=record["bin_counts"],
            rates=record["rates"],
            uncertainty={"intervals": record["uncertainty"], "status": record["status"]},
        )
    )
