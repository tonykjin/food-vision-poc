"""Frozen benchmark metric definitions (plan §10-§11, POC-13). Version: METRICS_VERSION.

Change a definition only by bumping the version and saying why in benchmarks/metrics.md;
never to make results look better. Every attempt stays in its denominator: failures,
abstentions, partial results and timeouts are reported, never dropped.
"""

import math
import random
import re
import statistics
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from foodvision.contracts.results import NUTRIENT_KEYS, AnalysisResult, Nutrients

METRICS_VERSION = "metrics-v1"
# Plan §11 "proposed useful-result event": business thresholds still to be approved and frozen.
USEFUL_DEFINITION = "useful-v1 (PROPOSED, not yet approved)"
ABSOLUTE_FLOOR = {"energy_kcal": 50.0, "protein_g": 3.0, "carbohydrate_g": 3.0, "fat_g": 3.0}
RELATIVE_TOLERANCE = {"energy_kcal": 0.15, "protein_g": 0.20, "carbohydrate_g": 0.20, "fat_g": 0.20}
# Relative error only when the reference is at least the absolute floor ("sufficiently
# nonzero"); below it the absolute error is the meaningful number.
RELATIVE_MIN_REFERENCE = ABSOLUTE_FLOOR
ABSTAIN_EQUIVALENT_ERRORS = {"empty_recognition"}  # e.g. fatsecret 211: a correct "no food"
ITEM_MAPPING = "lexical-v1 (automatic, UNREVIEWED; ambiguous cases need human review)"
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 13


@dataclass(frozen=True)
class Reference:
    """Evaluator-side truth for one group (never passed to a pipeline)."""

    group_id: str
    category: str
    grade: str
    expected_outcome: str  # "estimate" | "abstain"
    nutrients: Nutrients | None  # None for abstain-expected groups
    components: tuple[tuple[str, str, float], ...] = ()  # (identity, preparation, grams)

    @property
    def scorable(self) -> bool:
        """Primary numeric accuracy: estimate-expected, grade A/B, all four nutrients known."""
        return (
            self.expected_outcome == "estimate"
            and self.grade in ("A", "B")
            and self.nutrients is not None
            and not self.nutrients.missing()
        )


@dataclass(frozen=True)
class Attempt:
    """One fresh analysis of one sample by one configuration."""

    config: str
    group_id: str
    sample_id: str
    repeat: int
    status: str  # complete | partial | abstained | failed
    error_code: str | None
    server_total_ms: float
    known_cost_usd: float
    estimated_cost_usd: float | None  # None when any attempt in the scan had unknown cost
    result: AnalysisResult | None  # None when the output may not be kept (payload-free record)


# --- per-attempt formulas ---------------------------------------------------------------


def errors(predicted: float, reference: float, nutrient: str) -> tuple[float, float, float | None]:
    """(absolute, signed, relative or None). Relative needs reference >= the floor."""
    signed = predicted - reference
    relative = abs(signed) / reference if reference >= RELATIVE_MIN_REFERENCE[nutrient] else None
    return abs(signed), signed, relative


def within_tolerance(predicted: float, reference: float, nutrient: str) -> bool:
    allowed = max(ABSOLUTE_FLOOR[nutrient], RELATIVE_TOLERANCE[nutrient] * reference)
    return abs(predicted - reference) <= allowed


def predicted_totals(attempt: Attempt) -> Nutrients | None:
    """Totals of a complete result only; partial totals are never whole-meal estimates."""
    if attempt.status != "complete" or attempt.result is None:
        return None
    totals = attempt.result.totals.nutrients
    return None if totals.missing() else totals


def is_useful(attempt: Attempt, reference: Reference) -> bool:
    """Plan §11 useful-result event (proposed thresholds)."""
    predicted = predicted_totals(attempt)
    if predicted is None or not reference.scorable:
        return False
    return all(
        within_tolerance(getattr(predicted, n), getattr(reference.nutrients, n), n)
        for n in NUTRIENT_KEYS
    )


def is_correct_abstention(attempt: Attempt) -> bool:
    return attempt.status == "abstained" or (
        attempt.status == "failed" and attempt.error_code in ABSTAIN_EQUIVALENT_ERRORS
    )


# --- item mapping (food / preparation / portion) -------------------------------------------


def _tokens(name: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]+", name.lower()) if len(t) > 2}


def map_items(
    predicted: Sequence[tuple[str, str | None, float | None]],
    reference: Sequence[tuple[str, str, float]],
    threshold: float = 0.5,
) -> list[tuple[int, int]]:
    """Greedy one-to-one (pred_index, ref_index) pairs by token Jaccard >= threshold."""
    scores = []
    for i, (pname, _, _) in enumerate(predicted):
        for j, (rname, _, _) in enumerate(reference):
            a, b = _tokens(pname), _tokens(rname)
            if a and b:
                jaccard = len(a & b) / len(a | b)
                if jaccard >= threshold:
                    scores.append((-jaccard, i, j))
    used_p, used_r, pairs = set(), set(), []
    for _, i, j in sorted(scores):
        if i not in used_p and j not in used_r:
            used_p.add(i)
            used_r.add(j)
            pairs.append((i, j))
    return pairs


# --- aggregation helpers ------------------------------------------------------------------


def percentile(values: Sequence[float], q: float) -> float | None:
    """Linear interpolation between closest ranks (Hyndman-Fan type 7, numpy's default)."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def group_bootstrap(
    attempts: Sequence[Attempt],
    statistic: Callable[[Sequence[Attempt]], float | None],
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float] | None:
    """95% percentile interval, resampling whole groups (all photos and repeats together)."""
    by_group: dict[str, list[Attempt]] = defaultdict(list)
    for a in attempts:
        by_group[a.group_id].append(a)
    groups = sorted(by_group)
    if len(groups) < 2:
        return None
    rng = random.Random(seed)
    values = []
    for _ in range(resamples):
        sample = [a for g in rng.choices(groups, k=len(groups)) for a in by_group[g]]
        value = statistic(sample)
        if value is not None:
            values.append(value)
    if not values:
        return None
    return percentile(values, 0.025), percentile(values, 0.975)


# --- configuration report -----------------------------------------------------------------


@dataclass
class ConfigMetrics:
    config: str
    attempts: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    latency_ms: dict[str, float | None] = field(default_factory=dict)
    cost: dict[str, float | int | None] = field(default_factory=dict)
    # Derived accuracy metrics below (subject to the source's storage rights).
    useful: dict[str, float | int | tuple | None] = field(default_factory=dict)
    scorable_error: dict[str, dict[str, float | int | None]] = field(default_factory=dict)
    partial: dict[str, float | int | None] = field(default_factory=dict)
    abstention: dict[str, float | int | None] = field(default_factory=dict)
    items: dict[str, float | int | str | None] = field(default_factory=dict)
    repeatability: dict[str, float | int | None] = field(default_factory=dict)
    by_category: dict[str, dict[str, float | int | None]] = field(default_factory=dict)


def _useful_rate(attempts: Sequence[Attempt], refs: dict[str, Reference]) -> float | None:
    eligible = [a for a in attempts if refs[a.group_id].scorable]
    if not eligible:
        return None
    return sum(is_useful(a, refs[a.group_id]) for a in eligible) / len(eligible)


def _mean_abs_energy(attempts: Sequence[Attempt], refs: dict[str, Reference]) -> float | None:
    values = []
    for a in attempts:
        ref, pred = refs[a.group_id], predicted_totals(a)
        if ref.scorable and pred is not None:
            values.append(abs(pred.energy_kcal - ref.nutrients.energy_kcal))
    return _mean(values)


def config_metrics(config: str, attempts: Sequence[Attempt], refs: dict[str, Reference]):
    m = ConfigMetrics(config=config, attempts=len(attempts))
    for status in ("complete", "partial", "abstained", "failed"):
        m.status_counts[status] = sum(1 for a in attempts if a.status == status)

    times = [a.server_total_ms for a in attempts]
    complete_times = [a.server_total_ms for a in attempts if a.status == "complete"]
    m.latency_ms = {
        "p50_all": percentile(times, 0.5),
        "p95_all": percentile(times, 0.95),
        "p50_complete": percentile(complete_times, 0.5),
        "p95_complete": percentile(complete_times, 0.95),
    }

    eligible = [a for a in attempts if refs[a.group_id].scorable]
    useful = [a for a in eligible if is_useful(a, refs[a.group_id])]
    unknown_cost = sum(1 for a in attempts if a.estimated_cost_usd is None)
    known = sum(a.known_cost_usd for a in attempts)
    m.cost = {
        "known_cost_usd": known,
        "attempts_with_unknown_cost": unknown_cost,
        "per_attempt_usd": (known / len(attempts)) if attempts and not unknown_cost else None,
        "per_useful_usd": (known / len(useful)) if useful and not unknown_cost else None,
    }

    m.useful = {
        "definition": USEFUL_DEFINITION,
        "denominator_attempts": len(eligible),  # ALL attempts with a scorable reference
        "useful_attempts": len(useful),
        "pass_rate": (len(useful) / len(eligible)) if eligible else None,
        "pass_rate_ci95": group_bootstrap(eligible, lambda s: _useful_rate(s, refs)),
    }

    for n in NUTRIENT_KEYS:
        abs_e, signed_e, rel_e = [], [], []
        for a in eligible:
            pred = predicted_totals(a)
            if pred is None:
                continue
            ab, sg, rel = errors(getattr(pred, n), getattr(refs[a.group_id].nutrients, n), n)
            abs_e.append(ab)
            signed_e.append(sg)
            if rel is not None:
                rel_e.append(rel)
        m.scorable_error[n] = {
            "n_scorable": len(abs_e),  # complete results with all four totals known
            "mean_abs": _mean(abs_e),
            "median_abs": _median(abs_e),
            "mean_signed": _mean(signed_e),
            "n_relative": len(rel_e),
            "median_relative": _median(rel_e),
        }
    m.scorable_error["energy_kcal"]["mean_abs_ci95"] = group_bootstrap(
        eligible, lambda s: _mean_abs_energy(s, refs)
    )

    partials = [a for a in attempts if a.status == "partial" and a.result is not None]
    coverage = [
        a.result.totals.included_items
        / (a.result.totals.included_items + a.result.totals.excluded_items)
        for a in partials
        if a.result.totals.included_items + a.result.totals.excluded_items
    ]
    m.partial = {"partial_attempts": len(partials), "mean_item_coverage": _mean(coverage)}

    abstain_cases = [a for a in attempts if refs[a.group_id].expected_outcome == "abstain"]
    estimate_cases = [a for a in attempts if refs[a.group_id].expected_outcome == "estimate"]
    m.abstention = {
        "abstain_expected_attempts": len(abstain_cases),
        "correct_abstentions": sum(is_correct_abstention(a) for a in abstain_cases),
        "abstained_on_food": sum(is_correct_abstention(a) for a in estimate_cases),
    }

    m.items = _item_metrics(attempts, refs)
    m.repeatability = _repeatability(attempts)
    for category in sorted({refs[a.group_id].category for a in attempts}):
        subset = [a for a in attempts if refs[a.group_id].category == category]
        cat_eligible = [a for a in subset if refs[a.group_id].scorable]
        m.by_category[category] = {
            "attempts": len(subset),
            "complete": sum(1 for a in subset if a.status == "complete"),
            "failed": sum(1 for a in subset if a.status == "failed"),
            "useful_pass_rate": _useful_rate(cat_eligible, refs),
            "denominator_attempts": len(cat_eligible),
        }
    return m


def _item_metrics(attempts: Sequence[Attempt], refs: dict[str, Reference]) -> dict:
    predicted_n = reference_n = matched = prep_known = prep_correct = 0
    portion_abs: list[float] = []
    for a in attempts:
        ref = refs[a.group_id]
        if a.result is None or not ref.components or a.status not in ("complete", "partial"):
            continue
        pred = [(i.name, i.preparation, i.portion_g) for i in a.result.items]
        pairs = map_items(pred, ref.components)
        predicted_n += len(pred)
        reference_n += len(ref.components)
        matched += len(pairs)
        for i, j in pairs:
            _, p_prep, p_grams = pred[i]
            _, r_prep, r_grams = ref.components[j]
            if p_prep is not None:
                prep_known += 1
                prep_correct += p_prep == r_prep
            if p_grams is not None:
                portion_abs.append(abs(p_grams - r_grams))
    return {
        "mapping": ITEM_MAPPING,
        "precision": (matched / predicted_n) if predicted_n else None,
        "recall": (matched / reference_n) if reference_n else None,
        "preparation_accuracy": (prep_correct / prep_known) if prep_known else None,
        "preparation_unstated": matched - prep_known,
        "portion_mean_abs_g": _mean(portion_abs),
        "portion_median_abs_g": _median(portion_abs),
    }


def _repeatability(attempts: Sequence[Attempt]) -> dict:
    by_sample: dict[str, list[Attempt]] = defaultdict(list)
    for a in attempts:
        by_sample[a.sample_id].append(a)
    repeated = {s: v for s, v in by_sample.items() if len(v) >= 2}
    same_status = sum(1 for v in repeated.values() if len({a.status for a in v}) == 1)
    sds, cvs = [], []
    for v in repeated.values():
        energies = [t.energy_kcal for a in v if (t := predicted_totals(a)) is not None]
        if len(energies) >= 2:
            sd = statistics.stdev(energies)
            sds.append(sd)
            mean = statistics.fmean(energies)
            if mean > 0:
                cvs.append(sd / mean)
    return {
        "repeated_samples": len(repeated),
        "status_consistent_rate": (same_status / len(repeated)) if repeated else None,
        "samples_with_energy_spread": len(sds),
        "median_energy_sd_kcal": _median(sds),
        "median_energy_cv": _median(cvs),
    }


def agreement(a_attempts: Sequence[Attempt], b_attempts: Sequence[Attempt]) -> dict:
    """A vs B on the same sample and repeat. AGREEMENT, NOT ACCURACY: both can be wrong."""
    b_by_key = {(a.sample_id, a.repeat): a for a in b_attempts}
    diffs, close = [], 0
    for a in a_attempts:
        b = b_by_key.get((a.sample_id, a.repeat))
        ta, tb = predicted_totals(a), predicted_totals(b) if b else None
        if ta is None or tb is None:
            continue
        diffs.append(abs(ta.energy_kcal - tb.energy_kcal))
        close += within_tolerance(ta.energy_kcal, tb.energy_kcal, "energy_kcal")
    return {
        "label": "agreement between configurations, NOT accuracy",
        "paired_complete": len(diffs),
        "median_abs_energy_difference_kcal": _median(diffs),
        "energy_within_tolerance_rate": (close / len(diffs)) if diffs else None,
    }


def paired_useful_difference(
    a_attempts: Sequence[Attempt], b_attempts: Sequence[Attempt], refs: dict[str, Reference]
) -> dict:
    """Pass-rate difference (first minus second) on groups evaluable for both configs."""
    groups = {a.group_id for a in a_attempts} & {b.group_id for b in b_attempts}
    groups = {g for g in groups if refs[g].scorable}
    a_set = [a for a in a_attempts if a.group_id in groups]
    b_set = [b for b in b_attempts if b.group_id in groups]

    def diff(sample: Sequence[Attempt]) -> float | None:
        ra = _useful_rate([x for x in sample if x.config == a_set[0].config], refs)
        rb = _useful_rate([x for x in sample if x.config == b_set[0].config], refs)
        return None if ra is None or rb is None else ra - rb

    if not a_set or not b_set:
        return {"paired_groups": 0, "difference": None, "ci95": None}
    both = [*a_set, *b_set]
    return {
        "paired_groups": len(groups),
        "difference": diff(both),
        "ci95": group_bootstrap(both, diff),
    }
