"""fatsecret image-recognition v2 request-size guard (no network, no credentials).

Limits from https://platform.fatsecret.com/docs/v2/image.recognition (checked 2026-10-02):
- `image_b64` "is limited to 999,982 characters"
- "The entire request body is limited to 1MB characters (1.048M)"
- jpg/png/webp "with a size of up to 1.09MB"

Raw image bytes are not the request size: base64 expands by 4/3 and the JSON body adds
field names and parameters. We measure the exact serialized body and keep a safety margin,
so an oversize request is rejected here, before any billed call.
"""

import base64
import json
from dataclasses import dataclass
from typing import Any

from foodvision.contracts.errors import ErrorCode

IMAGE_B64_MAX_CHARS = 999_982
REQUEST_BODY_MAX_CHARS = 1_048_576  # docs: "1MB characters (1.048M)"
IMAGE_MAX_BYTES = 1_090_000  # docs: "up to 1.09MB" (decimal reading; b64 limit binds first)
SAFETY_MARGIN = 0.90


class FatsecretPayloadTooLarge(ValueError):
    code = ErrorCode.IMAGE_TOO_LARGE


@dataclass(frozen=True)
class FatsecretPayload:
    body: bytes
    image_bytes: int
    image_b64_chars: int
    body_chars: int


def build_request_body(image: bytes, **params: Any) -> FatsecretPayload:
    """Serialize the exact JSON body and enforce all documented limits with a margin."""
    if len(image) > IMAGE_MAX_BYTES * SAFETY_MARGIN:
        raise FatsecretPayloadTooLarge(
            f"image is {len(image)} bytes; margin limit {int(IMAGE_MAX_BYTES * SAFETY_MARGIN)}"
        )
    image_b64 = base64.b64encode(image).decode("ascii")
    if len(image_b64) > IMAGE_B64_MAX_CHARS * SAFETY_MARGIN:
        raise FatsecretPayloadTooLarge(
            f"image_b64 is {len(image_b64)} chars; "
            f"margin limit {int(IMAGE_B64_MAX_CHARS * SAFETY_MARGIN)}"
        )
    body = json.dumps({"image_b64": image_b64, **params}, separators=(",", ":"))
    if len(body) > REQUEST_BODY_MAX_CHARS * SAFETY_MARGIN:
        raise FatsecretPayloadTooLarge(
            f"request body is {len(body)} chars; "
            f"margin limit {int(REQUEST_BODY_MAX_CHARS * SAFETY_MARGIN)}"
        )
    return FatsecretPayload(
        body=body.encode("utf-8"),
        image_bytes=len(image),
        image_b64_chars=len(image_b64),
        body_chars=len(body),
    )
