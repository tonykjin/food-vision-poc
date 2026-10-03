import pytest
from fastapi.testclient import TestClient

from foodvision.api.factory import MAX_UPLOAD_BYTES, create_app
from foodvision.config import AgentSettings, AppKind, ProviderSettings
from foodvision.pipelines.mock import MOCK_WARNING

SETTINGS = {AppKind.PROVIDER: ProviderSettings, AppKind.AGENT: AgentSettings}
FAKE_IMAGE = b"synthetic-bytes-not-decoded-until-POC-04"


def client(kind: AppKind, mock: bool) -> TestClient:
    settings = SETTINGS[kind](_env_file=None, mock_mode=mock)
    return TestClient(create_app(kind, settings))


@pytest.mark.parametrize("kind", list(AppKind))
def test_health_reports_app_and_mode(kind):
    body = client(kind, mock=True).get("/health").json()
    assert body["status"] == "ok"
    assert body["app"] == kind.value
    assert body["mode"] == "mock"
    assert body["live_pipeline_implemented"] is False


@pytest.mark.parametrize(
    ("kind", "pipeline_id"), [(AppKind.PROVIDER, "A_mock"), (AppKind.AGENT, "B_mock")]
)
def test_mock_result_is_labeled_and_has_no_invented_nutrients(kind, pipeline_id):
    response = client(kind, mock=True).post(
        "/v1/analyze", files={"image": ("meal.jpg", FAKE_IMAGE, "image/jpeg")}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["is_mock"] is True
    assert body["pipeline_id"] == pipeline_id
    assert body["status"] == "partial"
    assert MOCK_WARNING in body["warnings"]
    assert all(value is None for value in body["totals"].values())
    for item in body["items"]:
        assert "MOCK" in item["name"]
        assert all(value is None for value in item["nutrients"].values())
    assert body["metrics"]["server_total_ms"] >= 0


@pytest.mark.parametrize("kind", list(AppKind))
def test_live_mode_returns_typed_not_implemented(kind):
    response = client(kind, mock=False).post(
        "/v1/analyze", files={"image": ("meal.jpg", FAKE_IMAGE, "image/jpeg")}
    )
    assert response.status_code == 501
    body = response.json()
    assert body["code"] == "not_implemented"
    assert body["is_mock"] is False


@pytest.mark.parametrize("kind", list(AppKind))
def test_empty_upload_is_invalid_image(kind):
    response = client(kind, mock=True).post(
        "/v1/analyze", files={"image": ("empty.jpg", b"", "image/jpeg")}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_image"


def test_oversized_upload_is_rejected():
    response = client(AppKind.AGENT, mock=True).post(
        "/v1/analyze", files={"image": ("big.jpg", b"0" * (MAX_UPLOAD_BYTES + 1), "image/jpeg")}
    )
    assert response.status_code == 413
    assert response.json()["code"] == "image_too_large"


def test_missing_file_is_rejected():
    response = client(AppKind.PROVIDER, mock=True).post("/v1/analyze")
    assert response.status_code == 422
