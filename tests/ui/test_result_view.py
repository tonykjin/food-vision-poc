"""Shared result cards (POC-11): pure helpers and both Streamlit apps in every state.

Results are SYNTHETIC. Pages run headless via AppTest; the stored automatic result is injected
through session state because AppTest cannot drive a file upload (covered by human checks).
"""

import re
from pathlib import Path

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from foodvision.contracts.errors import ErrorCode, ErrorDetail
from foodvision.contracts.results import (
    AnalysisResult,
    FoodSource,
    MatchMethod,
    Metrics,
    Nutrients,
    PortionMethod,
    PortionScenarios,
    ResultItem,
    ResultStatus,
)
from foodvision.measurement.confidence import assess_confidence
from foodvision.nutrition.calculator import sum_totals
from foodvision.ui.analyze_page import CORRECTIONS_KEY, RESULT_KEY
from foodvision.ui.result_view import (
    CONFIDENCE_CAPTION,
    REFERENCE_UNAVAILABLE,
    confidence_summary,
    outcome_from_response,
    portion_text,
    timing_lines,
    totals_heading,
)

APPS = Path(__file__).resolve().parents[2] / "apps"
SCRIPTS = [("provider_ui.py", "provider", "A_native"), ("agent_ui.py", "agent", "B_grounded")]


def grounded(name="SYNTHETIC rice", nutrients=None, **kw) -> ResultItem:
    fields = dict(
        name=name,
        preparation="boiled",
        resolved=True,
        portion_g=150,
        portion_method=PortionMethod.IMAGE_ESTIMATED,
        food_source=FoodSource.USDA,
        food_id="fdc:1",
        match_method=MatchMethod.DETERMINISTIC_RANKING,
        nutrients=nutrients
        or Nutrients(energy_kcal=195, protein_g=4, carbohydrate_g=42, fat_g=0.4),
        portion_scenarios=PortionScenarios(low_g=120, base_g=150, high_g=180),
    )
    fields.update(kw)
    return ResultItem(**fields)


def unresolved(name="SYNTHETIC mystery stew") -> ResultItem:
    return ResultItem(
        name=name,
        resolved=False,
        portion_g=200,
        portion_method=PortionMethod.IMAGE_ESTIMATED,
        uncertainty_reasons=["no catalog match (no_candidates)"],
    )


def finished(*items, status=None, **kw) -> AnalysisResult:
    totals = sum_totals([i.nutrients if i.resolved else None for i in items])
    if status is None:
        status = ResultStatus.COMPLETE if totals.status == "complete" else ResultStatus.PARTIAL
    r = AnalysisResult(
        scan_id="scan1",
        pipeline_id="B_grounded",
        is_mock=False,
        status=status,
        items=list(items),
        totals=totals,
        metrics=Metrics(server_total_ms=1234.5, external_attempts=2, estimated_cost_usd=0.05),
        **kw,
    )
    r.confidence = assess_confidence(r)
    return r


COMPLETE = finished(grounded())
PARTIAL = finished(grounded(), unresolved())
ABSTAINED = finished(status=ResultStatus.ABSTAINED, warnings=["No food was recognized."])
FAILED = finished(
    status=ResultStatus.FAILED, error=ErrorDetail(code=ErrorCode.TIMEOUT, message="timed out")
)


# --- pure helpers ---------------------------------------------------------------------------


def test_outcome_validates_the_contract():
    ok = outcome_from_response(200, COMPLETE.model_dump(mode="json"))
    assert ok.result is not None and ok.result.status is ResultStatus.COMPLETE
    bad = outcome_from_response(200, {"status": "great"})
    assert bad.result is None and bad.error_code == "invalid_schema"
    http = outcome_from_response(
        503, {"code": "authentication", "message": "no key", "scan_id": "s"}
    )
    assert (http.error_code, http.scan_id) == ("authentication", "s")
    unreachable = outcome_from_response(None, None)
    assert unreachable.result is None and unreachable.http_status is None


def test_partial_totals_heading_names_partial_and_exclusions():
    assert totals_heading(PARTIAL) == "Estimated totals: PARTIAL (1 item(s) counted, 1 excluded)"
    assert totals_heading(ABSTAINED) == "Totals unavailable"


def test_confidence_summary_is_labeled_uncalibrated_and_has_no_percent():
    text = confidence_summary(COMPLETE.confidence)
    assert text == "Confidence: Medium (heuristic, uncalibrated)" and "%" not in text
    assert confidence_summary(FAILED.confidence) == "Confidence: not assessed"


def test_portion_scenarios_are_labeled_assumptions():
    assert "assumption range 120/150/180 g (low/base/high)" in portion_text(grounded())
    assert portion_text(unresolved(name="x").model_copy(update={"portion_g": None})).startswith(
        "unknown"
    )


def test_timing_marks_client_latency_unavailable():
    lines = timing_lines(Metrics(server_total_ms=1234.5), None)
    assert lines[0] == "Backend analysis time (server_total_ms): 1,234 ms"
    assert "client_total_ms): unavailable" in lines[2]
    assert "estimated cost: unknown" in lines[3]


# --- both apps, every state -----------------------------------------------------------------


def page(monkeypatch, script, app, pipeline_id, stored) -> AppTest:
    health = {"status": "ok", "app": app, "mode": "live", "pipeline_id": pipeline_id}
    monkeypatch.setattr(httpx, "get", lambda *a, **k: type("R", (), {"json": lambda s: health})())
    at = AppTest.from_file(str(APPS / script))
    if stored is not None:
        at.session_state[RESULT_KEY] = stored
    at.run()
    assert not at.exception
    return at


def stored(result: AnalysisResult) -> dict:
    return {"http_status": 200, "body": result.model_dump(mode="json"), "wait_ms": 1500.0}


def texts(at: AppTest) -> str:
    parts = []
    for kind in ("markdown", "caption", "error", "warning", "info", "success", "subheader"):
        parts += [e.value for e in getattr(at, kind)]
    parts += [str(t.value) for t in at.table]
    parts += [e.label for e in at.expander]
    return "\n".join(parts)


@pytest.mark.parametrize(("script", "app", "pipeline_id"), SCRIPTS)
def test_idle_state(monkeypatch, script, app, pipeline_id):
    at = page(monkeypatch, script, app, pipeline_id, None)
    assert "Upload a food photo and press Analyze." in texts(at)


@pytest.mark.parametrize(("script", "app", "pipeline_id"), SCRIPTS)
def test_complete_state_shows_same_fields_in_both_apps(monkeypatch, script, app, pipeline_id):
    out = texts(page(monkeypatch, script, app, pipeline_id, stored(COMPLETE)))
    for expected in (
        "Complete:",
        "Estimated totals (complete)",
        "Confidence: Medium (heuristic, uncalibrated)",
        "Identity: **High**",
        "Portion: **Medium**",
        "Nutrition match: **High**",
        "Reference unavailable",
        "Backend analysis time (server_total_ms): 1,234 ms",
        "client_total_ms): unavailable",
        "1. SYNTHETIC rice (resolved)",
        "USDA fdc:1; match: deterministic ranking",
        "User corrections",
    ):
        assert expected in out, expected


@pytest.mark.parametrize(("script", "app", "pipeline_id"), SCRIPTS)
def test_partial_state_labels_totals_and_keeps_unknown(monkeypatch, script, app, pipeline_id):
    out = texts(page(monkeypatch, script, app, pipeline_id, stored(PARTIAL)))
    assert "Partial:" in out and "PARTIAL (1 item(s) counted, 1 excluded)" in out
    assert "SYNTHETIC mystery stew (unresolved)" in out
    assert "unknown" in out  # the unresolved item's nutrients
    assert not re.search(r"(?<![\d.])0 kcal", out)  # unknown is never shown as zero


@pytest.mark.parametrize(("script", "app", "pipeline_id"), SCRIPTS)
@pytest.mark.parametrize("result", [ABSTAINED, FAILED], ids=["abstained", "failed"])
def test_abstained_and_failed_states(monkeypatch, script, app, pipeline_id, result):
    at = page(monkeypatch, script, app, pipeline_id, stored(result))
    out = texts(at)
    assert f"Status: {result.status.value}" in out
    assert "Totals unavailable" in out and "Confidence: not assessed" in out
    assert "User corrections" not in out  # nothing to correct
    if result is FAILED:
        assert "timeout: timed out" in out


@pytest.mark.parametrize(("script", "app", "pipeline_id"), SCRIPTS)
def test_http_error_renders_as_failed(monkeypatch, script, app, pipeline_id):
    body = {
        "code": "authentication",
        "message": "fatsecret credentials are not configured",
        "scan_id": "s9",
    }
    out = texts(
        page(
            monkeypatch,
            script,
            app,
            pipeline_id,
            {"http_status": 503, "body": body, "wait_ms": 20.0},
        )
    )
    assert "Failed:" in out and "authentication: fatsecret credentials" in out
    assert "HTTP 503 · scan s9" in out


@pytest.mark.parametrize(("script", "app", "pipeline_id"), SCRIPTS)
def test_no_percentage_or_accuracy_claim_anywhere(monkeypatch, script, app, pipeline_id):
    for result in (COMPLETE, PARTIAL, ABSTAINED, FAILED):
        out = texts(page(monkeypatch, script, app, pipeline_id, stored(result)))
        assert "%" not in out
        # Only the fixed disclaimers may mention accuracy; nothing may claim it.
        claims = out.replace(REFERENCE_UNAVAILABLE, "").replace(CONFIDENCE_CAPTION, "")
        assert not re.search(r"accura", claims, re.IGNORECASE)


def test_corrections_are_kept_separate_from_the_automatic_result(monkeypatch):
    original = stored(COMPLETE)
    at = page(monkeypatch, "agent_ui.py", "agent", "B_grounded", original)
    at.text_input[0].input("SYNTHETIC brown rice")
    at.number_input[0].set_value(90.0)
    at.button[0].click().run()  # the form's submit button
    assert not at.exception
    corrections = at.session_state[CORRECTIONS_KEY]["scan1"]
    assert corrections == [
        {
            "item": "1. SYNTHETIC rice",
            "corrected_name": "SYNTHETIC brown rice",
            "corrected_portion_g": 90.0,
            "note": None,
        }
    ]
    assert at.session_state[RESULT_KEY] == original  # automatic result untouched
    out = texts(at)
    assert "1. SYNTHETIC rice (resolved)" in out and "195 kcal" in out  # not recalculated
    assert "SYNTHETIC brown rice" in out  # correction shown beside it


def test_mock_result_offers_no_corrections(monkeypatch):
    mock = AnalysisResult(
        scan_id="m",
        pipeline_id="B_mock",
        is_mock=True,
        status=ResultStatus.PARTIAL,
        items=[ResultItem(name="MOCK item", resolved=False, food_source=FoodSource.MOCK)],
    )
    out = texts(page(monkeypatch, "agent_ui.py", "agent", "B_mock", stored(mock)))
    assert "MOCK result (synthetic)" in out and "User corrections" not in out
