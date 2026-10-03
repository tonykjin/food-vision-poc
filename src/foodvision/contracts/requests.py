"""Internal analysis request context (plan §7 "Required internal fields")."""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from foodvision.contracts.results import SCHEMA_VERSION


class InputMode(StrEnum):
    IMAGE_ONLY = "image_only"
    # Separately named diagnostic experiment only (plan §3); never the primary benchmark.
    KNOWN_WEIGHT_DIAGNOSTIC = "known_weight_diagnostic"


Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class AnalysisContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    scan_id: str
    image_id: str | None = None
    original_sha256: Sha256Hex
    processed_sha256: Sha256Hex | None = None  # set by image preparation (POC-04)
    pipeline_id: str
    configuration_id: str | None = None
    input_mode: InputMode = InputMode.IMAGE_ONLY
    region: str = "US"
    language: str = "en"
    preprocessing_version: str | None = None
    known_weight_g: Annotated[float, Field(gt=0, allow_inf_nan=False)] | None = None

    @model_validator(mode="after")
    def _known_weight_only_in_diagnostic(self) -> Self:
        if (
            self.known_weight_g is not None
            and self.input_mode is not InputMode.KNOWN_WEIGHT_DIAGNOSTIC
        ):
            raise ValueError("known_weight_g is only allowed in the known_weight_diagnostic mode")
        return self
