import pytest

from foodvision.config import FOREIGN_SECRETS

APP_VARIABLES = {
    "MOCK_MODE",
    "DATABASE_URL",
    "USDA_API_KEY",
    "FATSECRET_CLIENT_ID",
    "FATSECRET_CLIENT_SECRET",
    "ANTHROPIC_API_KEY",
    "VISION_MODEL",
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
