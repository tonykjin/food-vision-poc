import pytest

from foodvision.config import FOREIGN_SECRETS

APP_VARIABLES = {
    "MOCK_MODE",
    "ENABLE_LIVE_API_TESTS",
    "DATABASE_URL",
    "USDA_API_KEY",
    "FATSECRET_CLIENT_ID",
    "FATSECRET_CLIENT_SECRET",
    "ANTHROPIC_API_KEY",
    "VISION_MODEL",
    "ENABLE_BARCODE_LOOKUP",
    *{name for names in FOREIGN_SECRETS.values() for name in names},
}


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Run every test without real env files or provider variables from the host."""
    for name in APP_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)


def synthetic_image(
    size=(64, 48), fmt="JPEG", color=(200, 120, 40), mode="RGB", exif=None, **save_kwargs
) -> bytes:
    """Generate a synthetic test image in memory (no private photos in the repo)."""
    import io

    from PIL import Image

    image = Image.new(mode, size, color)
    buffer = io.BytesIO()
    if exif is not None:
        save_kwargs["exif"] = exif
    image.save(buffer, format=fmt, **save_kwargs)
    return buffer.getvalue()


def barcode_image(*codes: tuple[str, str], fmt="PNG") -> bytes:
    """Synthetic image with generated barcodes side by side; codes are (text, zxing format)."""
    import io

    import numpy as np
    import zxingcpp
    from PIL import Image

    tiles = [
        Image.fromarray(
            np.array(
                zxingcpp.write_barcode_to_image(
                    zxingcpp.create_barcode(text, getattr(zxingcpp.BarcodeFormat, kind)),
                    scale=3,
                )
            )
        )
        for text, kind in codes
    ]
    gap = 60  # quiet zone so neighbouring symbols don't merge
    width = sum(t.width for t in tiles) + gap * (len(tiles) + 1)
    canvas = Image.new("L", (width, max(t.height for t in tiles) + 2 * gap), 255)
    x = gap
    for tile in tiles:
        canvas.paste(tile, (x, gap))
        x += tile.width + gap
    buffer = io.BytesIO()
    canvas.convert("RGB").save(buffer, format=fmt)
    return buffer.getvalue()


@pytest.fixture
def jpeg_bytes() -> bytes:
    return synthetic_image()


def noise_jpeg(size, seed=1) -> bytes:
    """Incompressible synthetic JPEG: a worst case for encoded size."""
    import io
    import random

    from PIL import Image

    rng = random.Random(seed)
    image = Image.frombytes("RGB", size, rng.randbytes(size[0] * size[1] * 3))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()
