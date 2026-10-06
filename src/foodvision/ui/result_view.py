"""Shared result cards for App A and App B (POC-11). Holds no secrets and calls nothing.

The helpers above `render_outcome` are pure (no Streamlit) so tests can check wording and
states. Rules shown here:
- Unknown nutrients read "unknown", never 0; non-complete totals are labeled with their status.
- Confidence is Low/Medium/High with reasons and is labeled heuristic and uncalibrated. No
  percentage is shown unless the contract says the confidence is empirically calibrated.
- There is no reference for a live scan, so accuracy reads "Reference unavailable".
- Backend time is `server_total_ms`. Browser click-to-render time is not measured, so
  `client_total_ms` reads unavailable.
- The automatic result is never edited. User corrections are kept beside it, in this browser
  session only, and nothing is recalculated from them.
"""

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from foodvision.contracts.results import (
    NUTRIENT_KEYS,
    AnalysisResult,
    Confidence,
    ConfidenceLevel,
    ConfidenceType,
    Metrics,
    ResultItem,
    ResultStatus,
    TotalsStatus,
)
from foodvision.nutrition.display import format_nutrient

NUTRIENT_LABELS = {
    "energy_kcal": "Energy",
    "protein_g": "Protein",
    "carbohydrate_g": "Carbohydrate",
    "fat_g": "Fat",
}
REFERENCE_UNAVAILABLE = (
    "Accuracy against reference: **Reference unavailable**. No independent reference exists "
    "for this photo, so no accuracy is shown."
)
CONFIDENCE_CAPTION = (
    "Heuristic, uncalibrated: rule-based labels from the result's structure, not measured "
    "accuracy. Model self-ratings and A/B agreement are not used. No probability is shown "
    "until calibration on separate reference data."
)
CORRECTIONS_CAPTION = (
    "User corrections are kept separate from the automatic result above, which is unchanged. "
    "Nutrients are not recalculated from corrections. They live only in this browser session."
)

STATE_BANNERS: dict[ResultStatus, tuple[str, str]] = {
    ResultStatus.COMPLETE: (
        "success",
        "Complete: every item was matched to a record with all four nutrients known.",
    ),
    ResultStatus.PARTIAL: (
        "warning",
        "Partial: some items or nutrients are unknown. Totals exclude them; they are not "
        "counted as zero.",
    ),
    ResultStatus.ABSTAINED: (
        "info",
        "Abstained: no food result was produced for this photo. No nutrition is estimated.",
    ),
    ResultStatus.FAILED: ("error", "Failed: the analysis did not produce a result."),
}


@dataclass(frozen=True)
class Outcome:
    """What one Analyze press produced: a validated result, or a request-level failure."""

    http_status: int | None
    result: AnalysisResult | None = None
    error_code: str | None = None
    message: str | None = None
    scan_id: str | None = None


def outcome_from_response(http_status: int | None, body: Any) -> Outcome:
    if http_status == 200:
        try:
            return Outcome(http_status, result=AnalysisResult.model_validate(body))
        except ValidationError as exc:
            return Outcome(
                http_status,
                error_code="invalid_schema",
                message=f"The API returned a result that fails the schema ({exc.error_count()} "
                "error(s)); it is not displayed.",
            )
    body = body if isinstance(body, dict) else {}
    return Outcome(
        http_status,
        error_code=str(body.get("code") or "error"),
        message=str(body.get("message") or "The API returned an error without a message."),
        scan_id=body.get("scan_id"),
    )


def level_text(level: ConfidenceLevel | None) -> str:
    return "not assessed" if level is None else level.value.capitalize()


def confidence_summary(confidence: Confidence) -> str:
    if confidence.type is ConfidenceType.UNAVAILABLE:
        return "Confidence: not assessed"
    if confidence.type is ConfidenceType.HEURISTIC_UNCALIBRATED:
        return f"Confidence: {level_text(confidence.label)} (heuristic, uncalibrated)"
    label = level_text(confidence.label)
    shown = f"Confidence: {label} (calibrated {confidence.calibration_version}"
    if confidence.probability is not None:
        shown += f", empirical pass rate {confidence.probability:.0%}"
    return shown + ")"


def totals_heading(result: AnalysisResult) -> str:
    status = result.totals.status
    if status is TotalsStatus.COMPLETE:
        return "Estimated totals (complete)"
    if status is TotalsStatus.PARTIAL:
        return (
            f"Estimated totals: PARTIAL ({result.totals.included_items} item(s) counted, "
            f"{result.totals.excluded_items} excluded)"
        )
    return "Totals unavailable"


def nutrient_row(nutrients) -> dict[str, str]:
    return {NUTRIENT_LABELS[k]: format_nutrient(k, getattr(nutrients, k)) for k in NUTRIENT_KEYS}


def portion_text(item: ResultItem) -> str:
    grams = "unknown" if item.portion_g is None else f"{item.portion_g:.0f} g"
    text = f"{grams} ({item.portion_method.value.replace('_', ' ')})"
    s = item.portion_scenarios
    if s is not None:
        text += f"; assumption range {s.low_g:.0f}/{s.base_g:.0f}/{s.high_g:.0f} g (low/base/high)"
    return text


def source_text(item: ResultItem) -> str:
    if not item.resolved:
        return f"unresolved (source: {item.food_source.value})"
    text = f"{item.food_source.value} {item.food_id}"
    if item.serving_id:
        text += f", serving {item.serving_id}"
    if item.match_method is not None:
        text += f"; match: {item.match_method.value.replace('_', ' ')}"
    return text


def _ms(value: float | None) -> str:
    return "unavailable" if value is None else f"{value:,.0f} ms"


def timing_lines(metrics: Metrics, wait_ms: float | None) -> list[str]:
    cost = metrics.estimated_cost_usd
    return [
        f"Backend analysis time (server_total_ms): {_ms(metrics.server_total_ms)}",
        f"UI-to-API wait (Python timer around the request; not click-to-render): {_ms(wait_ms)}",
        "Click-to-render (client_total_ms): unavailable (no browser-side timer yet)",
        f"External attempts: {metrics.external_attempts} · estimated cost: "
        + ("unknown" if cost is None else f"${cost:.4f}"),
    ]


# --- Streamlit rendering ------------------------------------------------------------------


def _banner(st, kind: str, text: str) -> None:
    getattr(st, kind)(text)


def _render_confidence(st, confidence: Confidence) -> None:
    st.markdown(f"**{confidence_summary(confidence)}**")
    if confidence.type is not ConfidenceType.UNAVAILABLE:
        cols = st.columns(3)
        for col, (name, level) in zip(
            cols,
            [
                ("Identity", confidence.identity),
                ("Portion", confidence.portion),
                ("Nutrition match", confidence.nutrition_match),
            ],
            strict=True,
        ):
            col.markdown(f"{name}: **{level_text(level)}**")
        st.caption(CONFIDENCE_CAPTION)
    for reason in confidence.reasons:
        st.caption(f"- {reason}")


def _render_item(st, index: int, item: ResultItem) -> None:
    state = "resolved" if item.resolved else "unresolved"
    with st.expander(f"{index + 1}. {item.name} ({state})", expanded=True):
        st.markdown(f"Preparation: {item.preparation or 'unknown'}")
        st.markdown(f"Portion: {portion_text(item)}")
        st.markdown(f"Source: {source_text(item)}")
        st.table(nutrient_row(item.nutrients))
        if item.visible_brand:
            st.markdown(f"Visible brand: {item.visible_brand}")
        if item.alternatives:
            st.markdown(f"Alternatives: {', '.join(item.alternatives)}")
        if item.evidence:
            st.caption(f"Evidence: {item.evidence}")
        for reason in item.uncertainty_reasons:
            st.caption(f"- {reason}")


def _render_corrections(st, result: AnalysisResult, corrections: dict[str, list[dict]]) -> None:
    st.markdown("**User corrections**")
    st.caption(CORRECTIONS_CAPTION)
    names = [f"{i + 1}. {item.name}" for i, item in enumerate(result.items)]
    with st.form(f"corrections-{result.scan_id}", clear_on_submit=True):
        target = st.selectbox("Item", names)
        name = st.text_input("Corrected food name (optional)")
        grams = st.number_input("Corrected portion in grams (optional)", min_value=0.0, value=None)
        note = st.text_input("Note (optional)")
        submitted = st.form_submit_button("Record correction")
        if submitted and (name.strip() or grams or note.strip()):
            corrections.setdefault(result.scan_id, []).append(
                {
                    "item": target,
                    "corrected_name": name.strip() or None,
                    "corrected_portion_g": grams or None,
                    "note": note.strip() or None,
                }
            )
    recorded = corrections.get(result.scan_id, [])
    if recorded:
        st.table(recorded)


def render_outcome(
    st, outcome: Outcome, wait_ms: float | None, corrections: dict[str, list[dict]]
) -> None:
    result = outcome.result
    if result is None:
        _banner(st, *STATE_BANNERS[ResultStatus.FAILED])
        st.error(f"{outcome.error_code}: {outcome.message}")
        st.caption(f"HTTP {outcome.http_status} · scan {outcome.scan_id or 'none'}")
        st.caption(timing_lines(Metrics(), wait_ms)[1])
        return

    if result.is_mock:
        st.warning("MOCK result (synthetic). Do not interpret as nutrition data.")
    _banner(st, *STATE_BANNERS[result.status])
    st.subheader(f"Status: {result.status.value}")
    if result.error is not None:
        st.error(f"{result.error.code.value}: {result.error.message}")
    for warning in result.warnings:
        st.info(warning)

    st.markdown(f"**{totals_heading(result)}**")
    if result.totals.status is not TotalsStatus.UNAVAILABLE:
        st.table(nutrient_row(result.totals.nutrients))
    st.caption(f"Basis: {result.nutrition_basis.value.replace('_', ' ')}")

    _render_confidence(st, result.confidence)
    st.markdown(REFERENCE_UNAVAILABLE)

    if result.items:
        st.markdown(f"**Food components ({len(result.items)})**")
        for index, item in enumerate(result.items):
            _render_item(st, index, item)

    st.markdown("**Timing and cost**")
    for line in timing_lines(result.metrics, wait_ms):
        st.caption(line)
    with st.expander("Provenance"):
        st.caption(f"scan {result.scan_id} · pipeline {result.pipeline_id}")
        st.caption(f"configuration {result.configuration_id or 'unknown'}")
        if result.confidence.rules_version:
            st.caption(f"confidence rules {result.confidence.rules_version}")
        if result.input is not None:
            st.caption(
                f"input {result.input.preprocessing_version} · "
                f"{result.input.processed_width_px}x{result.input.processed_height_px} px · "
                f"processed sha256 {result.input.processed_sha256[:12]}..."
            )
        m = result.model_provenance
        if m is not None:
            st.caption(
                f"model {m.model_served} (requested {m.model_requested}"
                + (", FALLBACK served" if m.fallback_served else "")
                + f") · prompt {m.prompt_version} · stop {m.stop_reason}"
            )

    if result.items and not result.is_mock:  # nothing real to correct in MOCK
        _render_corrections(st, result, corrections)
