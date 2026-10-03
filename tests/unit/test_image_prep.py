"""Shared image preparation, tested only with synthetic in-memory images."""

import hashlib
import io
import struct
import zlib

import pytest
from PIL import ExifTags, Image
from tests.conftest import noise_jpeg, synthetic_image

from foodvision.contracts.errors import ErrorCode
from foodvision.imaging.prepare import ImagePreparationError, prepare_image
from foodvision.imaging.profiles import BASELINE, PROFILES, PrepProfile, get_profile


def decode(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def png_header_only(width: int, height: int) -> bytes:
    """A PNG whose header claims the given size but carries almost no pixel data."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00"))
        + chunk(b"IEND", b"")
    )


def expect_error(data, code, reason, profile=BASELINE):
    with pytest.raises(ImagePreparationError) as info:
        prepare_image(data, profile)
    assert info.value.code is code
    assert info.value.reason == reason


# --- Rejected inputs ------------------------------------------------------------------


def test_empty_input():
    expect_error(b"", ErrorCode.INVALID_IMAGE, "empty")


@pytest.mark.parametrize("data", [b"not an image at all", b"\xff\xd8\xff" + b"\x00" * 50])
def test_undecodable_bytes(data):
    expect_error(data, ErrorCode.INVALID_IMAGE, "corrupt")


def test_truncated_jpeg_is_corrupt():
    data = noise_jpeg((200, 150))
    expect_error(data[: len(data) // 3], ErrorCode.INVALID_IMAGE, "corrupt")


@pytest.mark.parametrize("fmt", ["GIF", "BMP", "TIFF"])
def test_unsupported_formats(fmt):
    expect_error(synthetic_image(fmt=fmt), ErrorCode.INVALID_IMAGE, "unsupported_format")


def test_format_comes_from_content_not_extension():
    # PNG bytes are accepted as PNG regardless of any filename; GIF bytes are not.
    assert prepare_image(synthetic_image(fmt="PNG")).original_format == "PNG"


def test_pixel_limit_checked_from_header_before_decode():
    expect_error(png_header_only(10_000, 5_000), ErrorCode.IMAGE_TOO_LARGE, "pixel_limit")


def test_decompression_bomb_header_rejected():
    expect_error(png_header_only(50_000, 50_000), ErrorCode.IMAGE_TOO_LARGE, "pixel_limit")


def test_input_byte_limit():
    small = PrepProfile(name="tiny", max_long_edge_px=512, max_input_bytes=100)
    expect_error(noise_jpeg((50, 50)), ErrorCode.IMAGE_TOO_LARGE, "input_bytes", small)


# --- Orientation, aspect ratio, no upscaling ------------------------------------------


def test_exif_orientation_is_applied():
    image = Image.new("RGB", (40, 20), (0, 0, 255))
    image.paste((255, 0, 0), (0, 0, 20, 20))  # left half red
    exif = Image.Exif()
    exif[0x0112] = 6  # display rotated 90° clockwise
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif.tobytes(), quality=95)

    prepared = prepare_image(buffer.getvalue())
    assert prepared.exif_orientation == 6
    assert prepared.original_size == (40, 20)
    assert prepared.processed_size == (20, 40)
    out = decode(prepared.data).convert("RGB")
    top, bottom = out.getpixel((10, 5)), out.getpixel((10, 35))
    assert top[0] > 200 and top[2] < 60  # original left (red) is now on top
    assert bottom[2] > 200 and bottom[0] < 60
    assert out.getexif().get(0x0112) is None


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        ((1600, 900), (512, 288)),
        ((900, 1600), (288, 512)),
        ((5000, 40), (512, 4)),
        ((512, 300), (512, 300)),
        ((300, 200), (300, 200)),  # never upscaled
    ],
)
def test_aspect_ratio_preserved_without_crop_or_upscale(size, expected):
    prepared = prepare_image(synthetic_image(size=size))
    assert prepared.processed_size == expected
    assert decode(prepared.data).size == expected


def test_alpha_is_flattened_and_modes_converted():
    rgba = prepare_image(synthetic_image(fmt="PNG", mode="RGBA", color=(10, 20, 30, 0)))
    assert "flatten_alpha:white" in rgba.transforms
    assert decode(rgba.data).getpixel((5, 5))[0] > 240  # transparent -> white
    gray = prepare_image(synthetic_image(fmt="PNG", mode="L", color=128))
    assert decode(gray.data).mode == "RGB"


# --- Metadata removal -----------------------------------------------------------------


def test_location_and_all_exif_removed_from_outbound_copy():
    exif = Image.Exif()
    exif[ExifTags.Base.Make] = "SyntheticCam"
    exif[ExifTags.IFD.GPSInfo] = {1: "N", 2: (37.0, 46.0, 30.0), 3: "W", 4: (122.0, 25.0, 9.0)}
    data = synthetic_image(size=(800, 600), exif=exif.tobytes())
    assert decode(data).getexif().get_ifd(ExifTags.IFD.GPSInfo)  # precondition: GPS present

    out = decode(prepare_image(data).data)
    assert not out.getexif().get_ifd(ExifTags.IFD.GPSInfo)
    assert len(out.getexif()) == 0
    assert "exif" not in out.info and "icc_profile" not in out.info
    assert b"SyntheticCam" not in prepare_image(data).data


# --- Hashing and versioning -----------------------------------------------------------


def test_hashes_are_deterministic():
    data = noise_jpeg((1200, 900))
    first, second = prepare_image(data), prepare_image(data)
    assert first.original_sha256 == hashlib.sha256(data).hexdigest()
    assert first.processed_sha256 == hashlib.sha256(first.data).hexdigest()
    assert first.data == second.data
    assert first.processed_sha256 == second.processed_sha256


def test_baseline_is_512_and_versioned():
    assert BASELINE.max_long_edge_px == 512
    assert prepare_image(synthetic_image()).transform_version == BASELINE.transform_version
    assert BASELINE.transform_version.startswith("prep-v1:baseline:")


def test_other_resolutions_are_separately_named_and_versioned():
    hires = get_profile("b_hires_1024")
    assert hires.transform_version != BASELINE.transform_version
    assert prepare_image(synthetic_image(size=(1600, 900)), hires).processed_size == (1024, 576)
    tweaked = BASELINE.model_copy(update={"jpeg_quality": 90})
    assert tweaked.transform_version != BASELINE.transform_version
    assert set(PROFILES) == {"baseline", "b_hires_1024"}
    with pytest.raises(ValueError):
        get_profile("silent_override")
