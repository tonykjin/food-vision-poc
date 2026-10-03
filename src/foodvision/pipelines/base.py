"""Pipeline interface shared by App A and App B pipelines."""

from typing import Protocol

from foodvision.contracts.requests import AnalysisContext
from foodvision.contracts.results import AnalysisResult


class Pipeline(Protocol):
    pipeline_id: str
    is_mock: bool

    def analyze(self, image_bytes: bytes, context: AnalysisContext) -> AnalysisResult: ...
