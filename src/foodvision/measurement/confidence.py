"""Heuristic, uncalibrated Low/Medium/High confidence (plan §11, POC-11).

Rules read only structural fields of a finished result: preparation, alternatives, portion
method and assumption range, match method, missing nutrients and item count. They never read
model self-ratings, provider scores, A/B agreement or reference labels, and they never produce
a probability. Labels stay `heuristic_uncalibrated` until POC-15 measures pass rates per bucket
on separate calibration data. Changing a rule means bumping RULES_VERSION.

- identity: what the food is. Alternatives or an unknown preparation cap it at medium.
- portion: how much. Image-only portions are capped at medium (never validated); a wide
  low/high assumption range or an unknown weight gives low. Only measured weight can be high.
- nutrition_match: whether the record and nutrients support the item. Unresolved items,
  missing nutrients and fallback picks give low; a provider match or model pick gives medium.
- label: the lowest of the three. Scan level takes the worst item per dimension.
"""

from foodvision.contracts.results import (
    AnalysisResult,
    Confidence,
    ConfidenceLevel,
    ConfidenceType,
    MatchMethod,
    PortionMethod,
    ResultItem,
    ResultStatus,
)

RULES_VERSION = "confidence-rules-v1"
WIDE_PORTION_RATIO = 2.0  # high_g / low_g at or above this is a wide assumption range
MANY_ITEMS = 4  # this many items or more caps identity at medium (multi-item complexity)

_ORDER = [ConfidenceLevel.LOW, ConfidenceLevel.MEDIUM, ConfidenceLevel.HIGH]


def _lowest(levels: list[ConfidenceLevel]) -> ConfidenceLevel:
    return min(levels, key=_ORDER.index)


def _identity(item: ResultItem) -> tuple[ConfidenceLevel, list[str]]:
    reasons = []
    if item.alternatives:
        reasons.append(f"{item.name}: alternative identities possible")
    if item.preparation is None:
        reasons.append(f"{item.name}: preparation not established")
    return (ConfidenceLevel.MEDIUM if reasons else ConfidenceLevel.HIGH), reasons


def _portion(item: ResultItem) -> tuple[ConfidenceLevel, list[str]]:
    if item.portion_g is None or item.portion_method is PortionMethod.UNKNOWN:
        return ConfidenceLevel.LOW, [f"{item.name}: portion weight unknown"]
    if item.portion_method is PortionMethod.MEASURED_WEIGHT:
        return ConfidenceLevel.HIGH, []
    s = item.portion_scenarios
    if s is not None and s.high_g / s.low_g >= WIDE_PORTION_RATIO:
        return ConfidenceLevel.LOW, [
            f"{item.name}: wide portion assumption range ({s.low_g:.0f}-{s.high_g:.0f} g)"
        ]
    return ConfidenceLevel.MEDIUM, []  # estimated from the image, not measured


def _nutrition_match(item: ResultItem) -> tuple[ConfidenceLevel, list[str]]:
    if not item.resolved:
        return ConfidenceLevel.LOW, [f"{item.name}: no nutrition record used (unresolved)"]
    if item.nutrients.missing():
        return ConfidenceLevel.LOW, [
            f"{item.name}: record lacks {', '.join(item.nutrients.missing())}"
        ]
    if item.match_method is MatchMethod.FALLBACK_TOP_CANDIDATE:
        return ConfidenceLevel.LOW, [f"{item.name}: ambiguous match, top-ranked record used"]
    if item.match_method is MatchMethod.DETERMINISTIC_RANKING:
        return ConfidenceLevel.HIGH, []
    if item.match_method is MatchMethod.MODEL_SELECTION:
        return ConfidenceLevel.MEDIUM, [f"{item.name}: record chosen among ambiguous candidates"]
    return ConfidenceLevel.MEDIUM, [f"{item.name}: record matched by provider; basis not checked"]


def _unavailable(reason: str) -> Confidence:
    return Confidence(
        type=ConfidenceType.UNAVAILABLE, reasons=[reason], rules_version=RULES_VERSION
    )


def assess_confidence(result: AnalysisResult) -> Confidence:
    """Heuristic confidence for a finished result. Pure: does not modify `result`."""
    if result.is_mock:
        return _unavailable("MOCK result: nothing was recognized, so nothing is assessed.")
    if result.status is ResultStatus.FAILED:
        return _unavailable("Analysis failed: no result to assess.")
    if result.status is ResultStatus.ABSTAINED or not result.items:
        return _unavailable("Abstained: no food result to assess.")

    dimensions = {"identity": _identity, "portion": _portion, "nutrition_match": _nutrition_match}
    levels: dict[str, ConfidenceLevel] = {}
    reasons: list[str] = []
    for key, rule in dimensions.items():
        per_item = [rule(item) for item in result.items]
        levels[key] = _lowest([level for level, _ in per_item])
        reasons += [f"{key.replace('_', ' ')}: {r}" for _, rs in per_item for r in rs]
    if len(result.items) >= MANY_ITEMS:
        levels["identity"] = _lowest([levels["identity"], ConfidenceLevel.MEDIUM])
        reasons.append(f"identity: {len(result.items)} items in one image")
    if all(i.portion_method is not PortionMethod.MEASURED_WEIGHT for i in result.items):
        reasons.append("portion: image-only estimate; no measured weight")
    return Confidence(
        type=ConfidenceType.HEURISTIC_UNCALIBRATED,
        label=_lowest(list(levels.values())),
        reasons=reasons,
        rules_version=RULES_VERSION,
        **levels,
    )
