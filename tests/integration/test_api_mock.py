import pytest
from fastapi.testclient import TestClient
from tests.conftest import synthetic_image

from foodvision.api.factory import MAX_UPLOAD_BYTES, create_app
from foodvision.config import AgentSettings, AppKind, ProviderSettings
from foodvision.contracts.results import SCHEMA_VERSION, AnalysisResult
from foodvision.pipelines.mock import MOCK_WARNING

SETTINGS = {AppKind.PROVIDER: ProviderSettings, AppKind.AGENT: AgentSettings}
FAKE_IMAGE = synthetic_image(size=(1600, 900))


def client(kind: AppKind, mock: bool) -> TestClient:
    settings = SETTINGS[kind](_env_file=None, mock_mode=mock)
    return TestClient(create_app(kind, settings))


@pytest.mark.parametrize("kind", list(AppKind))
def test_health_reports_app_and_mode(kind):
    body = client(kind, mock=True).get("/health").json()
    assert body["status"] == "ok"
    assert body["app"] == kind.value
    assert body["mode"] == "mock"
    assert body["live_pipeline_implemented"] is True
    assert body["ready"] is True


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
    assert body["totals"]["status"] == "unavailable"
    assert all(value is None for value in body["totals"]["nutrients"].values())
    for item in body["items"]:
        assert "MOCK" in item["name"]
        assert item["resolved"] is False
        assert item["food_source"] == "mock"
        assert all(value is None for value in item["nutrients"].values())
    assert body["metrics"]["server_total_ms"] >= 0


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


@pytest.mark.parametrize("kind", list(AppKind))
def test_both_entry_points_serve_the_shared_contract(kind):
    app_client = client(kind, mock=True)
    response = app_client.post("/v1/analyze", files={"image": ("m.jpg", FAKE_IMAGE, "image/jpeg")})
    parsed = AnalysisResult.model_validate(response.json())
    assert parsed.schema_version == SCHEMA_VERSION
    assert app_client.get("/health").json()["schema_version"] == SCHEMA_VERSION
    schemas = app_client.get("/openapi.json").json()["components"]["schemas"]
    assert {"AnalysisResult", "ErrorResponse", "Totals", "ResultItem"} <= set(schemas)
    assert set(schemas["AnalysisResult"]["properties"]) == set(AnalysisResult.model_fields)


@pytest.mark.parametrize("module", ["provider_app", "agent_app"])
def test_real_entry_point_modules_use_shared_models(module, monkeypatch):
    import importlib

    monkeypatch.setenv("MOCK_MODE", "true")
    app_module = importlib.reload(importlib.import_module(f"foodvision.api.{module}"))
    response = TestClient(app_module.app).post(
        "/v1/analyze", files={"image": ("m.jpg", FAKE_IMAGE, "image/jpeg")}
    )
    assert AnalysisResult.model_validate(response.json()).is_mock is True


def test_both_apps_receive_the_same_processed_copy():
    provenance = []
    for kind in AppKind:
        response = client(kind, mock=True).post(
            "/v1/analyze", files={"image": ("m.jpg", FAKE_IMAGE, "image/jpeg")}
        )
        provenance.append(response.json()["input"])
    a, b = provenance
    assert a == b
    assert (a["processed_width_px"], a["processed_height_px"]) == (512, 288)


@pytest.mark.parametrize("kind", list(AppKind))
def test_undecodable_upload_rejected_even_in_live_mode(kind):
    response = client(kind, mock=False).post(
        "/v1/analyze", files={"image": ("x.jpg", b"not an image", "image/jpeg")}
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_image"


@pytest.mark.parametrize("kind", list(AppKind))
def test_every_scan_is_recorded_including_failures(kind):
    app_client = client(kind, mock=True)
    sink = app_client.app.state.telemetry
    ok = app_client.post("/v1/analyze", files={"image": ("m.jpg", FAKE_IMAGE, "image/jpeg")})
    bad = app_client.post("/v1/analyze", files={"image": ("x.jpg", b"nope", "image/jpeg")})
    assert bad.status_code == 400
    success, failure = sink.records
    assert success.scan_id == ok.json()["scan_id"]
    assert success.status == "partial" and success.is_mock
    assert {"image_prepare", "mock"} <= set(success.stage_ms)
    assert success.attempts == 0 and success.estimated_cost_usd == 0.0
    assert ok.json()["metrics"]["server_total_ms"] == success.server_total_ms
    assert failure.scan_id == bad.json()["scan_id"]
    assert failure.status == "failed" and failure.error_code == "invalid_image"
    assert failure.client_total_ms is None


@pytest.mark.parametrize("kind", list(AppKind))
def test_live_mode_without_credentials_is_typed_503(kind):
    app_client = client(kind, mock=False)
    assert app_client.get("/health").json()["ready"] is False
    response = app_client.post("/v1/analyze", files={"image": ("m.jpg", FAKE_IMAGE, "image/jpeg")})
    assert response.status_code == 503
    assert response.json()["code"] == "authentication"
    (record,) = app_client.app.state.telemetry.records
    assert record.status == "failed" and record.error_code == "authentication"
