"""App A end to end with a fake fatsecret HTTP layer (SYNTHETIC fixtures, no network)."""

import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr
from tests.conftest import synthetic_image

from foodvision.api.factory import create_app
from foodvision.config import AppKind, ProviderSettings
from foodvision.contracts.results import AnalysisResult
from foodvision.measurement.confidence import RULES_VERSION
from foodvision.measurement.storage_policy import DataSource, Purpose, StoragePolicy, filter_result
from foodvision.pipelines.provider_native import ProviderNativePipeline
from foodvision.providers.fatsecret_client import IMAGE_URL, FatsecretClient

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "fatsecret"
IMAGE = synthetic_image(size=(1600, 900))


def app_with(image_responses):
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if str(request.url) != IMAGE_URL:
            return httpx.Response(200, json={"access_token": "t", "expires_in": 86400})
        return image_responses.pop(0)

    client = FatsecretClient(
        SecretStr("id"),
        SecretStr("secret"),
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    settings = ProviderSettings(_env_file=None, mock_mode=False)
    app = create_app(AppKind.PROVIDER, settings, pipeline=ProviderNativePipeline(client))
    return TestClient(app), sent


def fixture(name):
    return httpx.Response(200, json=json.loads((FIXTURES / name).read_text(encoding="utf-8")))


def post(client):
    return client.post("/v1/analyze", files={"image": ("m.jpg", IMAGE, "image/jpeg")})


def test_analyze_uses_shared_prep_contract_and_measurement():
    client, sent = app_with([fixture("two_items.json")])
    response = post(client)
    result = AnalysisResult.model_validate(response.json())
    assert result.pipeline_id == "A_native" and not result.is_mock
    assert result.items[0].nutrients.energy_kcal == 300.0
    assert result.input.processed_width_px == 512  # shared baseline image prep
    body = json.loads(sent[-1].content)
    assert set(body) == {"image_b64", "include_food_data"}  # no eaten_foods hints in baseline
    (record,) = client.app.state.telemetry.records
    assert record.attempts == 2 and record.model_calls == 0  # token + image; no LLM
    assert result.metrics.external_attempts == 2


def test_telemetry_and_persisted_form_contain_no_restricted_content():
    client, _ = app_with([fixture("two_items.json")])
    result = AnalysisResult.model_validate(post(client).json())
    record = client.app.state.telemetry.records[0]
    stored = filter_result(result, DataSource.FATSECRET, StoragePolicy(), Purpose.PERSIST)
    # Structural checks, not bare-number substrings (random IDs and timestamps contain digits).
    assert "SYNTHETIC item" not in record.model_dump_json()
    assert not {"items", "totals", "warnings"} & set(record.model_dump())
    assert "SYNTHETIC item" not in json.dumps(stored)
    for item in stored["items"]:
        assert set(item) == {"resolved", "portion_method", "food_source", "food_id", "serving_id"}
    assert "nutrients" not in stored["totals"]
    assert stored["items"][0]["food_id"] == "9000001"  # food_id is storable


def test_label_only_image_is_a_typed_failure():
    client, _ = app_with([fixture("error_211.json")])
    response = post(client)
    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error"]["code"] == "empty_recognition"
    assert client.app.state.telemetry.records[0].error_code == "empty_recognition"


def test_provider_auth_failure_is_typed_and_hides_provider_text():
    error = {"error": {"code": "21", "message": "SENTINEL ip 203.0.113.9"}}
    client, _ = app_with([httpx.Response(200, json=error)])
    body = post(client).json()
    assert body["status"] == "failed" and body["error"]["code"] == "authentication"
    assert "fatsecret code 21" in body["error"]["message"]
    assert "SENTINEL" not in json.dumps(body)


def test_api_applies_shared_heuristic_confidence():
    client, _ = app_with([fixture("two_items.json")])
    result = AnalysisResult.model_validate(post(client).json())
    c = result.confidence
    assert c.type == "heuristic_uncalibrated" and c.probability is None
    assert c.rules_version == RULES_VERSION
    assert all(i.match_method == "provider" for i in result.items if i.resolved)
    assert c.nutrition_match in ("medium", "low")  # a provider match is never rated high
    assert c.portion != "high"  # image-only portions are never high
