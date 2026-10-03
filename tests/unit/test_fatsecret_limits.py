"""fatsecret request size is measured on the serialized JSON body, not raw image bytes."""

import base64
import json
import math
import random

import pytest
from tests.conftest import noise_jpeg

from foodvision.imaging.prepare import prepare_image
from foodvision.providers.fatsecret_limits import (
    IMAGE_B64_MAX_CHARS,
    REQUEST_BODY_MAX_CHARS,
    SAFETY_MARGIN,
    FatsecretPayloadTooLarge,
    build_request_body,
)


def blob(n: int) -> bytes:
    return random.Random(n).randbytes(n)


def test_documented_limits():
    assert IMAGE_B64_MAX_CHARS == 999_982
    assert REQUEST_BODY_MAX_CHARS == 1_048_576


def test_baseline_photo_fits_and_body_is_larger_than_raw_bytes():
    prepared = prepare_image(noise_jpeg((3000, 2000)))  # worst case: incompressible noise
    payload = build_request_body(prepared.data, include_food_data=True)
    assert payload.image_b64_chars == 4 * math.ceil(len(prepared.data) / 3)
    assert payload.body_chars > payload.image_b64_chars > payload.image_bytes
    body = json.loads(payload.body)
    assert base64.b64decode(body["image_b64"]) == prepared.data
    assert body["include_food_data"] is True


def test_rejected_within_margin_even_below_hard_limit():
    # 700,000 bytes -> 933,336 b64 chars: under 999,982 but over the 90% margin.
    with pytest.raises(FatsecretPayloadTooLarge, match="image_b64"):
        build_request_body(blob(700_000))
    assert 4 * math.ceil(700_000 / 3) < IMAGE_B64_MAX_CHARS
    assert 4 * math.ceil(700_000 / 3) > IMAGE_B64_MAX_CHARS * SAFETY_MARGIN


def test_extra_parameters_count_toward_body_limit():
    image = blob(650_000)  # 866,668 b64 chars, within the image_b64 margin
    build_request_body(image)
    eaten = [{"food_id": str(i), "food_name": "x" * 40} for i in range(1_500)]
    with pytest.raises(FatsecretPayloadTooLarge, match="request body"):
        build_request_body(image, eaten_foods=eaten)


def test_oversize_request_never_reaches_the_sender():
    sent: list[bytes] = []

    def send(body: bytes) -> None:  # stands in for the billed HTTP call (POC-08)
        sent.append(body)

    with pytest.raises(FatsecretPayloadTooLarge):
        send(build_request_body(blob(900_000), include_food_data=True).body)
    assert sent == []
