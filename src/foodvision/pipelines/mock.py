"""Synthetic MOCK pipeline for launching and testing the apps without providers.

It calls no provider or model and is not a nutrition estimate. Nutrients stay None
(unknown) so no invented values can be mistaken for real output.
"""

from foodvision.contracts.results import AnalysisResult, ResultItem, ResultStatus

MOCK_WARNING = (
    "MOCK MODE: synthetic result. No provider or model was called. "
    "This is not a nutrition estimate."
)


class MockPipeline:
    is_mock = True

    def __init__(self, pipeline_id: str) -> None:
        self.pipeline_id = pipeline_id

    def analyze(self, image_bytes: bytes, scan_id: str) -> AnalysisResult:
        return AnalysisResult(
            scan_id=scan_id,
            pipeline_id=self.pipeline_id,
            is_mock=True,
            status=ResultStatus.PARTIAL,
            items=[
                ResultItem(
                    name="MOCK item (synthetic, not a recognized food)",
                    uncertainty_reasons=["MOCK: no recognition was performed"],
                )
            ],
            warnings=[MOCK_WARNING, "All nutrients unknown (null) in MOCK mode."],
        )
