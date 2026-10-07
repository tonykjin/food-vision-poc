"""App B `B_direct` diagnostic pipeline (plan §9 B5, POC-14).

One model call returns visible foods and the model's own nutrient estimates. There is no food
database grounding: every item is labeled `model_estimate`, a warning says so, and confidence
rates nutrition match Low. Totals are summed in code; unknown estimates stay unknown and make
the totals partial. Useful for measuring what grounding adds, not a production path.
"""

from foodvision.contracts.errors import ErrorCode, ErrorDetail
from foodvision.contracts.requests import AnalysisContext
from foodvision.contracts.results import (
    AnalysisResult,
    FoodSource,
    ModelProvenance,
    Nutrients,
    ResultStatus,
    TotalsStatus,
)
from foodvision.imaging.prepare import PreparedImage
from foodvision.measurement.budget import BudgetExceeded
from foodvision.measurement.events import Stage
from foodvision.measurement.retry import AttemptError
from foodvision.measurement.spans import ScanRecorder
from foodvision.nutrition.calculator import sum_totals
from foodvision.pipelines.agent_recognition import NOT_MATCHED, hypothesis_item
from foodvision.providers.claude_vision import ClaudeVisionProvider
from foodvision.recognition.direct import DIRECT_PROMPT_VERSION

PIPELINE_ID = "B_direct"
DIRECT_LABEL = (
    "Model-estimated; no database grounding: nutrients are the vision model's own estimates, "
    "not calculated from food records."
)
MODEL_ESTIMATE_REASON = "nutrients estimated by the model (no database record)"


class DirectPipeline:
    is_mock = False
    pipeline_id = PIPELINE_ID

    def __init__(self, provider: ClaudeVisionProvider) -> None:
        self.provider = provider
        fallback = "fallback" if provider.config.refusal_fallback else "nofallback"
        self.configuration_id = (
            f"{PIPELINE_ID}:{provider.provider}:{provider.config.model}:"
            f"effort-{provider.config.effort}:"
            f"{DIRECT_PROMPT_VERSION}@{provider.direct_prompt_sha256[:12]}:{fallback}"
        )

    def _failed(self, context, code: ErrorCode, message: str, retryable=False):
        return AnalysisResult(
            scan_id=context.scan_id,
            pipeline_id=PIPELINE_ID,
            configuration_id=self.configuration_id,
            is_mock=False,
            status=ResultStatus.FAILED,
            error=ErrorDetail(code=code, message=message, retryable=retryable),
            warnings=[DIRECT_LABEL],
        )

    def analyze(
        self, image: PreparedImage, context: AnalysisContext, recorder: ScanRecorder
    ) -> AnalysisResult:
        try:
            output, provenance = self.provider.estimate_direct(image, recorder)
        except BudgetExceeded as exc:
            return self._failed(context, exc.code, f"Scan budget exhausted ({exc.reason}).")
        except AttemptError as exc:
            detail = getattr(exc, "detail", "") or exc.outcome.value
            retryable = exc.code in (ErrorCode.TIMEOUT, ErrorCode.QUOTA)
            return self._failed(context, exc.code, f"Vision request failed ({detail}).", retryable)

        with recorder.span(Stage.VALIDATION):
            common = dict(
                scan_id=context.scan_id,
                pipeline_id=PIPELINE_ID,
                configuration_id=self.configuration_id,
                is_mock=False,
                model_provenance=ModelProvenance(**provenance),
            )
            warnings = [DIRECT_LABEL]
            if provenance["fallback_served"]:
                warnings.append(
                    f"Answered by fallback model {provenance['model_served']}; "
                    "not the configured model."
                )
            if not output.image_assessment.is_food_image or not output.items:
                return AnalysisResult(
                    status=ResultStatus.ABSTAINED,
                    warnings=[*warnings, "No food was recognized in the image."],
                    **common,
                )
            items = []
            for h in output.items:
                base = hypothesis_item(h)
                reasons = [r for r in base.uncertainty_reasons if r != NOT_MATCHED]
                items.append(
                    base.model_copy(
                        update={
                            "resolved": True,
                            "food_source": FoodSource.MODEL_ESTIMATE,
                            "nutrients": Nutrients(**h.estimated_nutrients.model_dump()),
                            "uncertainty_reasons": [*reasons, MODEL_ESTIMATE_REASON],
                        }
                    )
                )
            totals = sum_totals([i.nutrients for i in items])
            if totals.status is TotalsStatus.COMPLETE:
                status = ResultStatus.COMPLETE
            else:
                status = ResultStatus.PARTIAL
                warnings.append(
                    "Totals are partial: the model gave no estimate for some nutrients "
                    "(unknown, not counted as zero)."
                )
            return AnalysisResult(
                status=status, items=items, totals=totals, warnings=warnings, **common
            )
