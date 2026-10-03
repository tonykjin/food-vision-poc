"""App B recognition-only pipeline (POC-09): vision hypotheses -> shared result contract.

Until USDA matching and grounded calculation land (POC-10), every item is unresolved: nutrients
stay unknown, totals unavailable, and the result is labeled partial. If the model reports no
food, the scan abstains. Model self-assessment is never turned into a confidence value.
"""

from foodvision.contracts.errors import ErrorCode, ErrorDetail
from foodvision.contracts.requests import AnalysisContext
from foodvision.contracts.results import (
    AnalysisResult,
    FoodSource,
    ModelProvenance,
    PortionMethod,
    PortionScenarios,
    ResultItem,
    ResultStatus,
)
from foodvision.imaging.prepare import PreparedImage
from foodvision.measurement.budget import BudgetExceeded
from foodvision.measurement.events import Stage
from foodvision.measurement.retry import AttemptError
from foodvision.measurement.spans import ScanRecorder
from foodvision.providers.claude_vision import ClaudeVisionProvider, RecognitionResponse
from foodvision.recognition.hypotheses import FoodHypothesis, Preparation

PIPELINE_ID = "B_recognition_only"
RECOGNITION_ONLY = (
    "Recognition only: foods are not yet matched to USDA records, so no nutrients are "
    "calculated (grounded matching arrives with POC-10)."
)
NOT_MATCHED = "not yet matched to a USDA record; nutrients not calculated"


def _provenance(response: RecognitionResponse) -> ModelProvenance:
    return ModelProvenance(
        provider=response.provider,
        model_requested=response.model_requested,
        model_served=response.model_served,
        fallback_served=response.fallback_served,
        prompt_version=response.prompt_version,
        prompt_sha256=response.prompt_sha256,
        sdk_version=response.sdk_version,
        effort=response.effort,
        stop_reason=response.stop_reason,
        request_id=response.request_id,
    )


def hypothesis_item(h: FoodHypothesis) -> ResultItem:
    reasons = [*h.uncertainty, f"portion assumptions: {h.portion_assumptions}", NOT_MATCHED]
    if h.is_composite:
        reasons.insert(0, "composite dish: components not separable")
    return ResultItem(
        name=h.display_name,
        preparation=None if h.preparation is Preparation.UNKNOWN else h.preparation.value,
        resolved=False,
        portion_g=h.portion_grams_base,
        portion_method=PortionMethod.IMAGE_ESTIMATED,
        food_source=FoodSource.NONE,
        portion_scenarios=PortionScenarios(
            low_g=h.portion_grams_low, base_g=h.portion_grams_base, high_g=h.portion_grams_high
        ),
        alternatives=list(h.alternatives),
        evidence=h.evidence,
        visible_brand=h.visible_brand,
        uncertainty_reasons=reasons,
    )


class RecognitionOnlyPipeline:
    is_mock = False
    pipeline_id = PIPELINE_ID

    def __init__(self, provider: ClaudeVisionProvider) -> None:
        self.provider = provider
        self.configuration_id = f"{PIPELINE_ID}:{provider.configuration_id}"

    def _failed(self, context: AnalysisContext, code: ErrorCode, message: str, retryable=False):
        return AnalysisResult(
            scan_id=context.scan_id,
            pipeline_id=PIPELINE_ID,
            configuration_id=self.configuration_id,
            is_mock=False,
            status=ResultStatus.FAILED,
            error=ErrorDetail(code=code, message=message, retryable=retryable),
        )

    def analyze(
        self, image: PreparedImage, context: AnalysisContext, recorder: ScanRecorder
    ) -> AnalysisResult:
        try:
            response = self.provider.recognize(image, recorder)
        except BudgetExceeded as exc:
            return self._failed(context, exc.code, f"Scan budget exhausted ({exc.reason}).")
        except AttemptError as exc:
            detail = getattr(exc, "detail", "") or exc.outcome.value
            retryable = exc.code in (ErrorCode.TIMEOUT, ErrorCode.QUOTA)
            return self._failed(context, exc.code, f"Vision request failed ({detail}).", retryable)

        with recorder.span(Stage.VALIDATION):
            output = response.output
            warnings = []
            if response.fallback_served:
                warnings.append(
                    f"Answered by fallback model {response.model_served} after a refusal by "
                    f"{response.model_requested}; not the configured model."
                )
            common = dict(
                scan_id=context.scan_id,
                pipeline_id=PIPELINE_ID,
                configuration_id=self.configuration_id,
                is_mock=False,
                model_provenance=_provenance(response),
            )
            if not output.image_assessment.is_food_image or not output.items:
                return AnalysisResult(
                    status=ResultStatus.ABSTAINED,
                    warnings=[*warnings, "No food was recognized in the image."],
                    **common,
                )
            return AnalysisResult(
                status=ResultStatus.PARTIAL,
                items=[hypothesis_item(h) for h in output.items],
                warnings=[RECOGNITION_ONLY, *warnings],
                **common,
            )
