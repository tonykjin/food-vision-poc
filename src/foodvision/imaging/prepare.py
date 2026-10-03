"""Shared image preparation: validate, orient, strip metadata, resize, re-encode, hash.

Decoding is by content, not extension. Pixel dimensions are checked from the header
before the full decode (decompression-bomb guard). The outbound copy is rebuilt from raw
pixels, so no EXIF (including GPS/location), XMP, ICC or comments survive.
Aspect ratio is preserved and images are never cropped or upscaled.
"""

import hashlib
import io
import warnings
from dataclasses import dataclass, field

from PIL import Image, ImageOps, UnidentifiedImageError

from foodvision.contracts.errors import ErrorCode
from foodvision.imaging.profiles import BASELINE, PrepProfile

EXIF_ORIENTATION_TAG = 0x0112


class ImagePreparationError(ValueError):
    def __init__(self, code: ErrorCode, reason: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.reason = reason


@dataclass(frozen=True)
class PreparedImage:
    data: bytes
    media_type: str
    original_sha256: str
    processed_sha256: str
    original_format: str
    original_size: tuple[int, int]  # as stored, before orientation
    processed_size: tuple[int, int]
    exif_orientation: int | None
    profile_name: str
    transform_version: str
    transforms: tuple[str, ...] = field(default_factory=tuple)


def _fail(code: ErrorCode, reason: str, message: str) -> ImagePreparationError:
    return ImagePreparationError(code, reason, message)


def _target_size(width: int, height: int, max_long_edge: int) -> tuple[int, int]:
    long_edge = max(width, height)
    if long_edge <= max_long_edge:
        return width, height
    scale = max_long_edge / long_edge
    return max(1, round(width * scale)), max(1, round(height * scale))


def prepare_image(data: bytes, profile: PrepProfile = BASELINE) -> PreparedImage:
    if not data:
        raise _fail(ErrorCode.INVALID_IMAGE, "empty", "Uploaded file is empty.")
    if len(data) > profile.max_input_bytes:
        raise _fail(
            ErrorCode.IMAGE_TOO_LARGE,
            "input_bytes",
            f"Upload is {len(data)} bytes; the limit is {profile.max_input_bytes}.",
        )
    original_sha256 = hashlib.sha256(data).hexdigest()

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(data))
            fmt = image.format or "unknown"
            if fmt not in profile.allowed_input_formats:
                raise _fail(
                    ErrorCode.INVALID_IMAGE,
                    "unsupported_format",
                    f"Format {fmt} is not supported; "
                    f"use {', '.join(profile.allowed_input_formats)}.",
                )
            width, height = image.size
            if width * height > profile.max_input_pixels:
                raise _fail(
                    ErrorCode.IMAGE_TOO_LARGE,
                    "pixel_limit",
                    f"Image is {width}x{height} px; "
                    f"the limit is {profile.max_input_pixels} pixels.",
                )
            image.seek(0)  # first frame only for animated inputs
            image.load()
    except ImagePreparationError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise _fail(
            ErrorCode.IMAGE_TOO_LARGE,
            "pixel_limit",
            f"Image header exceeds the decompression-bomb limit ({profile.max_input_pixels} px).",
        ) from None
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, EOFError) as exc:
        raise _fail(
            ErrorCode.INVALID_IMAGE, "corrupt", f"Could not decode image: {type(exc).__name__}."
        ) from None

    transforms: list[str] = []
    orientation = image.getexif().get(EXIF_ORIENTATION_TAG)
    oriented = ImageOps.exif_transpose(image)
    if orientation not in (None, 1):
        transforms.append(f"exif_orientation:{orientation}")

    if oriented.mode in ("RGBA", "LA", "PA") or (
        oriented.mode == "P" and "transparency" in oriented.info
    ):
        background = Image.new("RGB", oriented.size, profile.flatten_background_rgb)
        background.paste(oriented.convert("RGBA"), mask=oriented.convert("RGBA").getchannel("A"))
        oriented = background
        transforms.append("flatten_alpha:white")
    elif oriented.mode != "RGB":
        transforms.append(f"convert:{oriented.mode}->RGB")
        oriented = oriented.convert("RGB")

    target = _target_size(*oriented.size, profile.max_long_edge_px)
    if target != oriented.size:
        oriented = oriented.resize(target, Image.Resampling.LANCZOS)
        transforms.append(f"resize:{target[0]}x{target[1]}")

    # Rebuild from raw pixels so no metadata from the source can be carried over.
    clean = Image.frombytes("RGB", oriented.size, oriented.tobytes())
    buffer = io.BytesIO()
    clean.save(buffer, format=profile.output_format, quality=profile.jpeg_quality, optimize=False)
    processed = buffer.getvalue()
    transforms.append(f"encode:{profile.output_format}:q{profile.jpeg_quality}:strip_metadata")

    return PreparedImage(
        data=processed,
        media_type="image/jpeg",
        original_sha256=original_sha256,
        processed_sha256=hashlib.sha256(processed).hexdigest(),
        original_format=fmt,
        original_size=(width, height),
        processed_size=clean.size,
        exif_orientation=orientation,
        profile_name=profile.name,
        transform_version=profile.transform_version,
        transforms=tuple(transforms),
    )
