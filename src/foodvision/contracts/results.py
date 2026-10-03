"""Shared analysis result contract, schema 1.0 (plan §7).

Units are explicit in field names. Unknown nutrients are None, never 0. Unsupported enum
values, unknown fields, negative or non-finite numbers are rejected. Cross-field rules keep
partial results from presenting as complete. Selection membership (is this food ID one
the tools returned?) is checked in `foodvision.matching.selection`, not by this schema.
"""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from foodvision.contracts.errors import ErrorDetail

SCHEMA_VERSION = "1.0"

NonNegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]

NUTRIENT_KEYS: tuple[str, ...] = ("energy_kcal", "protein_g", "carbohydrate_g", "fat_g")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResultStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    ABSTAINED = "abstained"
    FAILED = "failed"


class TotalsStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class NutritionBasis(StrEnum):
    ESTIMATED_VISIBLE_PORTION = "estimated_visible_portion"
    KNOWN_WEIGHT_DIAGNOSTIC = "known_weight_diagnostic"


class PortionMethod(StrEnum):
    IMAGE_ESTIMATED = "image_estimated"
    PROVIDER_SUGGESTED = "provider_suggested"
    MEASURED_WEIGHT = "measured_weight"
    UNKNOWN = "unknown"


class FoodSource(StrEnum):
    USDA = "USDA"
    FATSECRET = "fatsecret"
    MODEL_ESTIMATE = "model_estimate"  # B_direct only; no database grounding
    MOCK = "mock"
    NONE = "none"


class ConfidenceType(StrEnum):
    HEURISTIC_UNCALIBRATED = "heuristic_uncalibrated"
    EMPIRICAL_CALIBRATED = "empirical_calibrated"
    UNAVAILABLE = "unavailable"


class ConfidenceLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Nutrients(Strict):
    energy_kcal: NonNegative | None = None
    protein_g: NonNegative | None = None
    carbohydrate_g: NonNegative | None = None
    fat_g: NonNegative | None = None

    def missing(self) -> list[str]:
        return [key for key in NUTRIENT_KEYS if getattr(self, key) is None]


class ResultItem(Strict):
    name: str = Field(min_length=1)
    preparation: str | None = None
    resolved: bool
    portion_g: Positive | None = None
    portion_method: PortionMethod = PortionMethod.UNKNOWN
    food_source: FoodSource = FoodSource.NONE
    food_id: str | None = None
    serving_id: str | None = None
    nutrients: Nutrients = Field(default_factory=Nutrients)
    uncertainty_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _resolved_needs_source_and_portion(self) -> Self:
        if self.resolved:
            if self.portion_g is None or self.portion_method is PortionMethod.UNKNOWN:
                raise ValueError("a resolved item needs portion_g and a known portion_method")
            if self.food_source is FoodSource.NONE:
                raise ValueError("a resolved item needs a food_source")
            if self.food_source in (FoodSource.USDA, FoodSource.FATSECRET) and not self.food_id:
                raise ValueError("database-grounded items need a food_id")
        return self


class Totals(Strict):
    status: TotalsStatus
    nutrients: Nutrients = Field(default_factory=Nutrients)
    included_items: int = Field(default=0, ge=0)
    excluded_items: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _status_matches_content(self) -> Self:
        missing = self.nutrients.missing()
        if self.status is TotalsStatus.COMPLETE and (missing or self.excluded_items):
            raise ValueError("complete totals cannot have unknown nutrients or excluded items")
        if self.status is TotalsStatus.UNAVAILABLE and len(missing) != len(NUTRIENT_KEYS):
            raise ValueError("unavailable totals must not carry nutrient values")
        return self


class Confidence(Strict):
    type: ConfidenceType = ConfidenceType.UNAVAILABLE
    label: ConfidenceLevel | None = None
    identity: ConfidenceLevel | None = None
    portion: ConfidenceLevel | None = None
    nutrition_match: ConfidenceLevel | None = None
    reasons: list[str] = Field(default_factory=list)
    probability: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None = None
    calibration_version: str | None = None

    @model_validator(mode="after")
    def _probability_requires_calibration(self) -> Self:
        calibrated = self.type is ConfidenceType.EMPIRICAL_CALIBRATED
        if self.probability is not None and not (calibrated and self.calibration_version):
            raise ValueError("probability requires empirical calibration and calibration_version")
        if calibrated and not self.calibration_version:
            raise ValueError("empirical_calibrated confidence needs a calibration_version")
        return self


class InputProvenance(Strict):
    """Which exact image bytes the pipeline saw (plan §7 required internal fields)."""

    original_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    processed_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    preprocessing_version: str
    processed_width_px: int = Field(gt=0)
    processed_height_px: int = Field(gt=0)


class Metrics(Strict):
    server_total_ms: NonNegative | None = None
    external_attempts: int = Field(default=0, ge=0)
    estimated_cost_usd: NonNegative | None = None


class AnalysisResult(Strict):
    schema_version: str = SCHEMA_VERSION
    scan_id: str
    pipeline_id: str
    configuration_id: str | None = None
    is_mock: bool
    status: ResultStatus
    nutrition_basis: NutritionBasis = NutritionBasis.ESTIMATED_VISIBLE_PORTION
    items: list[ResultItem] = Field(default_factory=list)
    totals: Totals = Field(default_factory=lambda: Totals(status=TotalsStatus.UNAVAILABLE))
    confidence: Confidence = Field(default_factory=Confidence)
    warnings: list[str] = Field(default_factory=list)
    error: ErrorDetail | None = None
    input: InputProvenance | None = None
    metrics: Metrics = Field(default_factory=Metrics)

    @model_validator(mode="after")
    def _status_is_consistent(self) -> Self:
        unresolved = any(not item.resolved for item in self.items)
        if self.status is ResultStatus.FAILED:
            if self.error is None:
                raise ValueError("a failed result needs an error")
        elif self.error is not None:
            raise ValueError("only failed results carry an error")
        if self.status is ResultStatus.COMPLETE:
            if not self.items or unresolved or self.totals.status is not TotalsStatus.COMPLETE:
                raise ValueError("complete needs resolved items and complete totals")
            if self.is_mock:
                raise ValueError("a MOCK result can never be complete")
        elif self.totals.status is TotalsStatus.COMPLETE:
            raise ValueError(f"a {self.status} result cannot have complete totals")
        if unresolved and self.totals.status is TotalsStatus.COMPLETE:
            raise ValueError("unresolved items cannot produce complete totals")
        if self.status in (ResultStatus.ABSTAINED, ResultStatus.FAILED) and (
            self.totals.status is not TotalsStatus.UNAVAILABLE
        ):
            raise ValueError(f"{self.status} results must have unavailable totals")
        return self
