"""CI check: both apps, started as real uvicorn processes in MOCK mode, serve the shared contract.

Run after starting:
  MOCK_MODE=true uvicorn foodvision.api.provider_app:app --port 8001
  MOCK_MODE=true uvicorn foodvision.api.agent_app:app --port 8002
Uses a synthetic image only; no provider is called and no credentials are needed.
"""

import io
import sys
import time

import httpx
from PIL import Image

from foodvision.contracts.results import AnalysisResult

APPS = {"provider": ("http://127.0.0.1:8001", "A_mock"), "agent": ("http://127.0.0.1:8002", "B_mock")}


def synthetic_jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (640, 480), (200, 180, 150)).save(buffer, format="JPEG")
    return buffer.getvalue()


def wait_for(url: str, seconds: float = 60) -> dict:
    deadline = time.monotonic() + seconds
    while True:
        try:
            return httpx.get(f"{url}/health", timeout=2).json()
        except httpx.HTTPError:
            if time.monotonic() > deadline:
                raise
            time.sleep(1)


def main() -> int:
    image = synthetic_jpeg()
    for app, (url, pipeline_id) in APPS.items():
        health = wait_for(url)
        assert health["app"] == app and health["mode"] == "mock", health
        assert health["pipeline_id"] == pipeline_id, health
        response = httpx.post(
            f"{url}/v1/analyze", files={"image": ("synthetic.jpg", image, "image/jpeg")}, timeout=30
        )
        assert response.status_code == 200, response.status_code
        result = AnalysisResult.model_validate(response.json())  # the shared contract
        assert result.is_mock and result.pipeline_id == pipeline_id
        assert result.status == "partial" and result.totals.status == "unavailable"
        assert all(v is None for v in result.totals.nutrients.model_dump().values())
        assert result.confidence.type == "unavailable"
        bad = httpx.post(
            f"{url}/v1/analyze", files={"image": ("x.jpg", b"not an image", "image/jpeg")}
        )
        assert bad.status_code == 400 and bad.json()["code"] == "invalid_image"
        print(f"{app}: mock flow OK ({pipeline_id}, {result.metrics.server_total_ms:.0f} ms)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
