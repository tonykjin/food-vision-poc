"""Placeholder typed errors for POC-02. POC-03 (#3) adds the full plan §7 failure codes."""

from enum import StrEnum

from pydantic import BaseModel


class ErrorCode(StrEnum):
    INVALID_IMAGE = "invalid_image"
    IMAGE_TOO_LARGE = "image_too_large"
    NOT_IMPLEMENTED = "not_implemented"


class ErrorResponse(BaseModel):
    code: ErrorCode
    message: str
    scan_id: str
    pipeline_id: str
    is_mock: bool
