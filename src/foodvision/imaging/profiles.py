"""Versioned image preparation profiles (plan §8 A2).

The baseline is shared by App A and App B so both pipelines receive byte-identical input.
Any other resolution is a separately named experiment profile, never a silent override.
"""

import hashlib
import json
from typing import Literal

from PIL import __version__ as PILLOW_VERSION
from pydantic import BaseModel, ConfigDict, Field

PREP_ALGORITHM_VERSION = "prep-v1"


class PrepProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    max_long_edge_px: int = Field(gt=0)
    output_format: Literal["JPEG"] = "JPEG"
    jpeg_quality: int = Field(default=85, ge=1, le=95)
    max_input_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    max_input_pixels: int = Field(default=40_000_000, gt=0)
    allowed_input_formats: tuple[str, ...] = ("JPEG", "PNG", "WEBP")
    flatten_background_rgb: tuple[int, int, int] = (255, 255, 255)

    @property
    def transform_version(self) -> str:
        """Stable ID for these exact settings, the algorithm version and the Pillow version."""
        settings = self.model_dump(exclude={"name"})
        digest = hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:10]
        return f"{PREP_ALGORITHM_VERSION}:{self.name}:{digest}:pillow-{PILLOW_VERSION}"


BASELINE = PrepProfile(name="baseline", max_long_edge_px=512)

PROFILES: dict[str, PrepProfile] = {
    BASELINE.name: BASELINE,
    # Separately configured experiment for App B only (plan §8 A2 step 4). Never the baseline.
    "b_hires_1024": PrepProfile(name="b_hires_1024", max_long_edge_px=1024),
}


def get_profile(name: str) -> PrepProfile:
    try:
        return PROFILES[name]
    except KeyError:
        raise ValueError(
            f"unknown image prep profile {name!r}; known: {sorted(PROFILES)}"
        ) from None
