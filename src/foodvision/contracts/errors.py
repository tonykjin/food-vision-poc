"""Typed failure codes and error payloads (plan §7)."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ErrorCode(StrEnum):
    INVALID_IMAGE = "invalid_image"
    IMAGE_TOO_LARGE = "image_too_large"
    AUTHENTICATION = "authentication"
    QUOTA = "quota"
    TIMEOUT = "timeout"
    REFUSED = "refused"
    EMPTY_RECOGNITION = "empty_recognition"
    INVALID_SCHEMA = "invalid_schema"
    NO_MATCH = "no_match"
    MISSING_PORTION_BASIS = "missing_portion_basis"
    UNSUPPORTED_UNIT = "unsupported_unit"
    INVALID_SELECTION = "invalid_selection"
    PROVIDER_ERROR = "provider_error"
    NOT_IMPLEMENTED = "not_implemented"


class ErrorDetail(BaseModel):
    """Failure carried inside a `failed` AnalysisResult."""

    model_config = ConfigDict(extra="forbid")

    code: ErrorCode
    message: str
    retryable: bool = False


class ErrorResponse(BaseModel):
    """HTTP error body for requests rejected before a result exists."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str
    code: ErrorCode
    message: str
    scan_id: str
    pipeline_id: str
    is_mock: bool
