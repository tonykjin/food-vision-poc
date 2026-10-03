"""Pipeline interface shared by App A and App B pipelines."""

from typing import Protocol

from foodvision.contracts.requests import AnalysisContext
from foodvision.contracts.results import AnalysisResult
from foodvision.imaging.prepare import PreparedImage
from foodvision.measurement.spans import ScanRecorder


class Pipeline(Protocol):
    pipeline_id: str
    is_mock: bool

    def analyze(
        self, image: PreparedImage, context: AnalysisContext, recorder: ScanRecorder
    ) -> AnalysisResult: ...
