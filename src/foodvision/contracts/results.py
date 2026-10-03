"""Placeholder result contract for POC-02 scaffolding.

POC-03 (#3) replaces this with the full plan §7 contract (portion methods, sources,
confidence, failure codes, validation rules). Unknown nutrients stay None, never 0.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class ResultStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    ABSTAINED = "abstained"
    FAILED = "failed"


class Nutrients(BaseModel):
    energy_kcal: float | None = None
    protein_g: float | None = None
    carbohydrate_g: float | None = None
    fat_g: float | None = None


class ResultItem(BaseModel):
    name: str
    portion_g: float | None = Field(default=None, ge=0)
    nutrients: Nutrients = Field(default_factory=Nutrients)
    uncertainty_reasons: list[str] = Field(default_factory=list)


class ResultMetrics(BaseModel):
    server_total_ms: float | None = None
    external_attempts: int = 0
    estimated_cost_usd: float | None = None


class AnalysisResult(BaseModel):
    schema_version: str = "0.1-placeholder"
    scan_id: str
    pipeline_id: str
    is_mock: bool
    status: ResultStatus
    items: list[ResultItem] = Field(default_factory=list)
    totals: Nutrients = Field(default_factory=Nutrients)
    warnings: list[str] = Field(default_factory=list)
    metrics: ResultMetrics = Field(default_factory=ResultMetrics)
