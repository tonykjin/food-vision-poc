"""App A `A_native` pipeline: fatsecret image recognition -> shared result contract.

No LLM or model fallback exists in App A. Normalization rules (docs checked 2026-10-02):
- `eaten.total_nutritional_content` is already the total for the detected portion: it is used
  as-is and never scaled again.
- Only if those totals are missing, a matching per-serving record from `food.servings` (the
  suggested serving) is scaled once: amount × suggested units / serving units.
- Numbers arrive as strings; blank, non-numeric, negative or non-finite values become unknown.
- An ml portion has no gram weight here, so that item stays unresolved (not counted).
- No foods, or error 211 ("No food item detected", also returned for nutrition-label-only
  images), is a typed `empty_recognition` failure.
Results are restricted fatsecret content: shown transiently, never persisted, logged or
exported while rights are pending (only food_id/serving_id are storable).
"""

import math
from typing import Any

from foodvision.contracts.errors import ErrorCode, ErrorDetail
from foodvision.contracts.requests import AnalysisContext
from foodvision.contracts.results import (
    AnalysisResult,
    FoodSource,
    MatchMethod,
    Nutrients,
    PortionMethod,
    ResultItem,
    ResultStatus,
    TotalsStatus,
)
from foodvision.imaging.prepare import PreparedImage
from foodvision.measurement.budget import BudgetExceeded
from foodvision.measurement.events import Stage
from foodvision.measurement.retry import AttemptError
from foodvision.measurement.spans import ScanRecorder
from foodvision.nutrition.calculator import sum_totals
from foodvision.providers.fatsecret_client import NO_FOOD_DETECTED, FatsecretClient
from foodvision.providers.fatsecret_limits import FatsecretPayloadTooLarge, build_request_body

PIPELINE_ID = "A_native"
CONFIGURATION_ID = "A_native-fatsecret-image-v2"
ATTRIBUTION_HTML = '<a href="https://platform.fatsecret.com">Powered by fatsecret Platform API</a>'
RESTRICTED_NOTICE = (
    "fatsecret results are shown transiently and are not stored "
    "(only food_id and serving_id are storable)."
)
NUTRIENT_FIELDS = {
    "energy_kcal": "calories",
    "protein_g": "protein",
    "carbohydrate_g": "carbohydrate",
    "fat_g": "fat",
}
GRAM_UNITS = {"g", "gram", "grams"}


def _number(value: Any) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _nutrients(source: dict[str, Any], factor: float = 1.0) -> Nutrients:
    values = {}
    for key, field in NUTRIENT_FIELDS.items():
        amount = _number(source.get(field))
        values[key] = None if amount is None else amount * factor
    return Nutrients(**values)


def _suggested_serving_scaled(item: dict[str, Any]) -> tuple[Nutrients, float | None] | None:
    """Per-serving facts × (suggested units / serving units), applied exactly once."""
    suggested = item.get("suggested_serving") or {}
    servings = ((item.get("food") or {}).get("servings") or {}).get("serving") or []
    if isinstance(servings, dict):
        servings = [servings]
    match = next(
        (s for s in servings if str(s.get("serving_id")) == str(suggested.get("serving_id"))),
        None,
    )
    units, serving_units = _number(suggested.get("number_of_units")), None
    if match is not None:
        serving_units = _number(match.get("number_of_units"))
    if match is None or not units or not serving_units:
        return None
    factor = units / serving_units
    grams = None
    if (match.get("metric_serving_unit") or "").lower() in GRAM_UNITS:
        amount = _number(match.get("metric_serving_amount"))
        grams = None if amount is None else amount * factor
    return _nutrients(match, factor), grams


def normalize_item(item: dict[str, Any]) -> ResultItem:
    eaten = item.get("eaten") or {}
    suggested = item.get("suggested_serving") or {}
    reasons: list[str] = []
    name = (item.get("food_entry_name") or eaten.get("food_name_singular") or "").strip()
    food_id = item.get("food_id")
    totals = eaten.get("total_nutritional_content")

    if isinstance(totals, dict):
        nutrients = _nutrients(totals)  # already the eaten total: no scaling
        grams = None
        if (eaten.get("metric_description") or "").lower() in GRAM_UNITS:
            grams = _number(eaten.get("total_metric_amount"))
        elif eaten.get("metric_description"):
            reasons.append("portion reported in non-gram units; grams unknown")
    else:
        scaled = _suggested_serving_scaled(item)
        if scaled is None:
            nutrients, grams = Nutrients(), None
            reasons.append("no eaten totals and no matching serving record")
        else:
            nutrients, grams = scaled
            reasons.append("computed once from the suggested per-serving record")

    if nutrients.missing():
        reasons.append(f"missing or invalid: {', '.join(nutrients.missing())}")
    if grams is None:
        reasons.append("portion weight unknown")
    reasons.append("portion estimated by provider from the image")
    resolved = bool(name and food_id is not None and grams is not None and grams > 0)
    return ResultItem(
        name=name or "unnamed fatsecret item",
        resolved=resolved,
        portion_g=grams if grams and grams > 0 else None,
        portion_method=PortionMethod.PROVIDER_SUGGESTED if grams else PortionMethod.UNKNOWN,
        food_source=FoodSource.FATSECRET,
        food_id=str(food_id) if food_id is not None else None,
        match_method=MatchMethod.PROVIDER if food_id is not None else None,
        serving_id=str(suggested["serving_id"]) if suggested.get("serving_id") else None,
        nutrients=nutrients,
        uncertainty_reasons=reasons,
    )


def _failed(context: AnalysisContext, code: ErrorCode, message: str, retryable=False):
    return AnalysisResult(
        scan_id=context.scan_id,
        pipeline_id=PIPELINE_ID,
        configuration_id=CONFIGURATION_ID,
        is_mock=False,
        status=ResultStatus.FAILED,
        error=ErrorDetail(code=code, message=message, retryable=retryable),
        warnings=[RESTRICTED_NOTICE],
    )


def normalize_response(payload: dict[str, Any], context: AnalysisContext) -> AnalysisResult:
    error = payload.get("error") if isinstance(payload.get("error"), dict) else None
    if error is not None and str(error.get("code")) == str(NO_FOOD_DETECTED):
        return _failed(
            context,
            ErrorCode.EMPTY_RECOGNITION,
            "No food item detected (fatsecret 211). Nutrition-label-only images are rejected "
            "by design.",
        )
    raw_items = payload.get("food_response")
    if raw_items is None:
        return _failed(context, ErrorCode.INVALID_SCHEMA, "Response has no food_response.")
    if isinstance(raw_items, dict):
        raw_items = [raw_items]
    items = [normalize_item(i) for i in raw_items if isinstance(i, dict)]
    if not items:
        return _failed(context, ErrorCode.EMPTY_RECOGNITION, "No foods were recognized.")
    totals = sum_totals([i.nutrients if i.resolved else None for i in items])
    status = (
        ResultStatus.COMPLETE if totals.status is TotalsStatus.COMPLETE else ResultStatus.PARTIAL
    )
    warnings = [RESTRICTED_NOTICE]
    if totals.status is not TotalsStatus.COMPLETE:
        warnings.append("Totals are partial: unresolved items or unknown nutrients excluded.")
    return AnalysisResult(
        scan_id=context.scan_id,
        pipeline_id=PIPELINE_ID,
        configuration_id=CONFIGURATION_ID,
        is_mock=False,
        status=status,
        items=items,
        totals=totals,
        warnings=warnings,
    )


class ProviderNativePipeline:
    is_mock = False
    pipeline_id = PIPELINE_ID
    configuration_id = CONFIGURATION_ID

    def __init__(self, client: FatsecretClient) -> None:
        self.client = client

    def analyze(
        self, image: PreparedImage, context: AnalysisContext, recorder: ScanRecorder
    ) -> AnalysisResult:
        try:
            # Baseline: no eaten_foods hints; region/language are Premier-only (US default).
            payload = build_request_body(image.data, include_food_data=True)
        except FatsecretPayloadTooLarge as exc:
            return _failed(context, exc.code, "Prepared image exceeds fatsecret request limits.")
        try:
            response = self.client.recognize(payload.body, recorder)
        except BudgetExceeded as exc:
            return _failed(context, exc.code, f"Scan budget exhausted ({exc.reason}).")
        except AttemptError as exc:
            retryable = exc.code in (ErrorCode.TIMEOUT, ErrorCode.QUOTA)
            detail = exc.detail() if hasattr(exc, "detail") else exc.outcome.value
            return _failed(context, exc.code, f"fatsecret request failed ({detail}).", retryable)
        with recorder.span(Stage.VALIDATION):
            return normalize_response(response, context)
