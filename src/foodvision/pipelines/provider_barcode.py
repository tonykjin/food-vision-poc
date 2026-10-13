"""App A `A_barcode` pipeline: a product barcode read locally -> fatsecret barcode lookup (#50).

Routing (`ProviderRoutedPipeline`): the App A API reads product barcodes from the upload
before analysis. Exactly one barcode -> `A_barcode`; several different ones -> a typed failure
(we never guess which product was meant); none -> `A_native` image recognition, unchanged.
The benchmark calls `analyze` without barcodes, so `A_native` results stay pure.

Normalization (docs checked 2026-10-13, food.find_id_for_barcode v2):
- The result is ONE serving as labeled for the product (the default serving, else the first),
  never scaled and never an estimate of the amount eaten: nutrition_basis=per_label_serving,
  portion_method=label_serving.
- A serving without a gram weight (e.g. ml for drinks) stays unresolved: no density is assumed.
- Error 211, or the v1-style `food_id` "0", is a typed `no_match`.
Results are restricted fatsecret content, handled exactly like `A_native` (only food_id and
serving_id are storable). No model is ever called.
"""

from typing import Any

from foodvision.contracts.errors import ErrorCode, ErrorDetail
from foodvision.contracts.requests import AnalysisContext
from foodvision.contracts.results import (
    AnalysisResult,
    FoodSource,
    MatchMethod,
    NutritionBasis,
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
from foodvision.pipelines.provider_native import (
    GRAM_UNITS,
    RESTRICTED_NOTICE,
    ProviderNativePipeline,
    _number,
    _nutrients,
)
from foodvision.providers.fatsecret_client import NO_FOOD_DETECTED, FatsecretClient

PIPELINE_ID = "A_barcode"
CONFIGURATION_ID = "A_barcode-fatsecret-barcode-v2"
LABEL_SERVING_NOTICE = (
    "Nutrition is for one serving as labeled for this product, not the amount eaten."
)


def _failed(context: AnalysisContext, code: ErrorCode, message: str, retryable=False):
    return AnalysisResult(
        scan_id=context.scan_id,
        pipeline_id=PIPELINE_ID,
        configuration_id=CONFIGURATION_ID,
        is_mock=False,
        status=ResultStatus.FAILED,
        nutrition_basis=NutritionBasis.PER_LABEL_SERVING,
        error=ErrorDetail(code=code, message=message, retryable=retryable),
        warnings=[RESTRICTED_NOTICE],
    )


def _servings(food: dict[str, Any]) -> list[dict[str, Any]]:
    servings = (food.get("servings") or {}).get("serving") or []
    if isinstance(servings, dict):
        servings = [servings]
    return [s for s in servings if isinstance(s, dict)]


def normalize_food(food: dict[str, Any], gtin13: str) -> ResultItem:
    servings = _servings(food)
    serving = next((s for s in servings if str(s.get("is_default")) == "1"), None)
    serving = serving or (servings[0] if servings else None)
    brand = (food.get("brand_name") or "").strip()
    product = (food.get("food_name") or "").strip()
    name = " ".join(part for part in (brand, product) if part) or f"product {gtin13}"
    food_id = food.get("food_id")
    reasons = [f"identified by barcode {gtin13}"]

    if serving is None:
        nutrients, grams = _nutrients({}), None
        reasons.append("no serving record for this product")
    else:
        nutrients = _nutrients(serving)  # one labeled serving: never scaled
        grams = None
        if (serving.get("metric_serving_unit") or "").lower() in GRAM_UNITS:
            grams = _number(serving.get("metric_serving_amount"))
        elif serving.get("metric_serving_unit"):
            reasons.append("serving given in non-gram units; grams unknown")
        description = (serving.get("serving_description") or "").strip()
        reasons.append(f"one labeled serving ({description or 'size not described'})")
    if nutrients.missing():
        reasons.append(f"missing or invalid: {', '.join(nutrients.missing())}")
    if grams is None:
        reasons.append("serving weight unknown")
    reasons.append("amount eaten unknown")

    resolved = bool(food_id is not None and grams is not None and grams > 0)
    return ResultItem(
        name=name,
        resolved=resolved,
        portion_g=grams if grams and grams > 0 else None,
        portion_method=PortionMethod.LABEL_SERVING if grams else PortionMethod.UNKNOWN,
        food_source=FoodSource.FATSECRET,
        food_id=str(food_id) if food_id is not None else None,
        match_method=MatchMethod.PROVIDER if food_id is not None else None,
        serving_id=str(serving["serving_id"]) if serving and serving.get("serving_id") else None,
        nutrients=nutrients,
        uncertainty_reasons=reasons,
        visible_brand=brand or None,
    )


def normalize_barcode_response(
    payload: dict[str, Any], gtin13: str, context: AnalysisContext
) -> AnalysisResult:
    error = payload.get("error") if isinstance(payload.get("error"), dict) else None
    legacy_id = payload.get("food_id")
    legacy_missing = isinstance(legacy_id, dict) and str(legacy_id.get("value")) == "0"
    if (error is not None and str(error.get("code")) == str(NO_FOOD_DETECTED)) or legacy_missing:
        return _failed(
            context,
            ErrorCode.NO_MATCH,
            f"Barcode {gtin13} was read, but fatsecret has no product for it (US data). "
            "Photograph the food itself instead.",
        )
    food = payload.get("food")
    if not isinstance(food, dict):
        return _failed(context, ErrorCode.INVALID_SCHEMA, "Barcode response has no food record.")
    item = normalize_food(food, gtin13)
    totals = sum_totals([item.nutrients if item.resolved else None])
    complete = totals.status is TotalsStatus.COMPLETE
    warnings = [RESTRICTED_NOTICE, LABEL_SERVING_NOTICE]
    if not complete:
        warnings.append("Totals are partial: unresolved items or unknown nutrients excluded.")
    return AnalysisResult(
        scan_id=context.scan_id,
        pipeline_id=PIPELINE_ID,
        configuration_id=CONFIGURATION_ID,
        is_mock=False,
        status=ResultStatus.COMPLETE if complete else ResultStatus.PARTIAL,
        nutrition_basis=NutritionBasis.PER_LABEL_SERVING,
        items=[item],
        totals=totals,
        warnings=warnings,
    )


class ProviderBarcodePipeline:
    is_mock = False
    pipeline_id = PIPELINE_ID
    configuration_id = CONFIGURATION_ID

    def __init__(self, client: FatsecretClient) -> None:
        self.client = client

    def analyze_barcode(
        self, gtin13: str, context: AnalysisContext, recorder: ScanRecorder
    ) -> AnalysisResult:
        try:
            response = self.client.find_barcode(gtin13, recorder)
        except BudgetExceeded as exc:
            return _failed(context, exc.code, f"Scan budget exhausted ({exc.reason}).")
        except AttemptError as exc:
            retryable = exc.code in (ErrorCode.TIMEOUT, ErrorCode.QUOTA)
            detail = exc.detail() if hasattr(exc, "detail") else exc.outcome.value
            return _failed(
                context, exc.code, f"fatsecret barcode lookup failed ({detail}).", retryable
            )
        with recorder.span(Stage.VALIDATION):
            return normalize_barcode_response(response, gtin13, context)


class ProviderRoutedPipeline:
    """App A as served by its API: barcode lookup when one barcode is read, else A_native."""

    is_mock = False
    reads_barcodes = True
    pipeline_id = ProviderNativePipeline.pipeline_id
    configuration_id = ProviderNativePipeline.configuration_id

    def __init__(self, client: FatsecretClient) -> None:
        self.native = ProviderNativePipeline(client)
        self.barcode = ProviderBarcodePipeline(client)

    def analyze(
        self,
        image: PreparedImage,
        context: AnalysisContext,
        recorder: ScanRecorder,
        barcodes: list[str] | tuple[str, ...] = (),
    ) -> AnalysisResult:
        if not barcodes:
            return self.native.analyze(image, context, recorder)
        # Label telemetry with the pipeline that actually ran.
        recorder.pipeline_id, recorder.configuration_id = PIPELINE_ID, CONFIGURATION_ID
        if len(barcodes) > 1:
            return _failed(
                context,
                ErrorCode.INVALID_IMAGE,
                f"{len(barcodes)} different product barcodes were read; "
                "photograph one product's barcode.",
            )
        return self.barcode.analyze_barcode(barcodes[0], context, recorder)
