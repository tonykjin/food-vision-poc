"""Synthetic MOCK pipeline for launching and testing the apps without providers.

It calls no provider or model and is not a nutrition estimate. Its single item is
unresolved, so nutrients stay None and totals are unavailable; the contract also
forbids a MOCK result from ever being `complete`.
"""

from foodvision.contracts.requests import AnalysisContext
from foodvision.contracts.results import (
    AnalysisResult,
    FoodSource,
    ResultItem,
    ResultStatus,
)
from foodvision.imaging.prepare import PreparedImage

MOCK_WARNING = (
    "MOCK MODE: synthetic result. No provider or model was called. "
    "This is not a nutrition estimate."
)


class MockPipeline:
    is_mock = True

    def __init__(self, pipeline_id: str) -> None:
        self.pipeline_id = pipeline_id

    def analyze(self, image: PreparedImage, context: AnalysisContext) -> AnalysisResult:
        return AnalysisResult(
            scan_id=context.scan_id,
            pipeline_id=self.pipeline_id,
            configuration_id=f"{self.pipeline_id}-synthetic",
            is_mock=True,
            status=ResultStatus.PARTIAL,
            items=[
                ResultItem(
                    name="MOCK item (synthetic, not a recognized food)",
                    resolved=False,
                    food_source=FoodSource.MOCK,
                    uncertainty_reasons=["MOCK: no recognition was performed"],
                )
            ],
            warnings=[MOCK_WARNING, "All nutrients unknown (null) in MOCK mode."],
        )
