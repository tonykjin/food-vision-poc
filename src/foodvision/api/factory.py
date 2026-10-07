"""Shared FastAPI factory. Each app registers only its own pipeline and settings."""

import uuid

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse

from foodvision import __version__
from foodvision.config import AppKind, AppSettings, load_settings
from foodvision.contracts.errors import ErrorCode, ErrorResponse
from foodvision.contracts.requests import AnalysisContext
from foodvision.contracts.results import (
    SCHEMA_VERSION,
    AnalysisResult,
    ConfidenceType,
    InputProvenance,
)
from foodvision.imaging.prepare import ImagePreparationError, prepare_image
from foodvision.imaging.profiles import BASELINE
from foodvision.measurement.budget import BudgetPolicy
from foodvision.measurement.confidence import assess_confidence
from foodvision.measurement.events import ScanStatus, Stage
from foodvision.measurement.sinks import InMemorySink
from foodvision.measurement.spans import ScanRecorder
from foodvision.pipelines.base import Pipeline
from foodvision.pipelines.mock import MockPipeline

MAX_UPLOAD_BYTES = 10 * 1024 * 1024

PIPELINE_IDS: dict[AppKind, dict[str, str]] = {
    AppKind.PROVIDER: {"mock": "A_mock", "live": "A_native"},
    AppKind.AGENT: {"mock": "B_mock", "live": "B_grounded"},
}

LIVE_ISSUE: dict[AppKind, str] = {
    AppKind.PROVIDER: "POC-08 (#8)",
    AppKind.AGENT: "POC-09/POC-10 (#9, #10)",
}


def live_pipeline(kind: AppKind, settings: AppSettings):
    """Return (pipeline, reason it is unavailable). Imports stay app-specific."""
    if kind is AppKind.PROVIDER:
        if settings.fatsecret_client_id is None or settings.fatsecret_client_secret is None:
            return (
                None,
                "fatsecret credentials are not configured (foodvision doctor --app provider)",
            )
        from foodvision.pipelines.provider_native import ProviderNativePipeline
        from foodvision.providers.fatsecret_client import FatsecretClient

        client = FatsecretClient(settings.fatsecret_client_id, settings.fatsecret_client_secret)
        return ProviderNativePipeline(client), None
    if settings.anthropic_api_key is None:
        return None, "ANTHROPIC_API_KEY is not configured (foodvision doctor --app agent)"
    from foodvision.pipelines.agent_recognition import RecognitionOnlyPipeline
    from foodvision.providers.claude_vision import ClaudeVisionProvider, VisionConfig

    provider = ClaudeVisionProvider(
        settings.anthropic_api_key,
        VisionConfig(
            model=settings.vision_model,
            effort=settings.vision_effort,
            max_tokens=settings.vision_max_tokens,
            refusal_fallback=settings.vision_refusal_fallback,
        ),
    )
    if settings.pipeline_mode == "recognition_only":
        return RecognitionOnlyPipeline(provider), None
    if settings.database_url is None:
        return None, (
            "DATABASE_URL (an fv_inference login) is not configured for grounded matching; "
            "set it, or set PIPELINE_MODE=recognition_only"
        )
    from sqlalchemy import create_engine

    from foodvision.pipelines.agent_grounded import GroundedPipeline

    versions = settings.catalog_source_versions
    engine = create_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
    return GroundedPipeline(
        provider,
        engine,
        source_versions=[v.strip() for v in versions.split(",") if v.strip()] if versions else None,
    ), None


def create_app(
    kind: AppKind, settings: AppSettings | None = None, pipeline: Pipeline | None = None
) -> FastAPI:
    settings = settings if settings is not None else load_settings(kind)
    mode = "mock" if settings.mock_mode else "live"
    pipeline_id = PIPELINE_IDS[kind][mode]
    unavailable_reason = None
    if pipeline is None:
        if settings.mock_mode:
            pipeline = MockPipeline(pipeline_id)
        else:
            pipeline, unavailable_reason = live_pipeline(kind, settings)

    app = FastAPI(title=f"Food Vision {kind.value} API", version=__version__)
    app.state.telemetry = InMemorySink()
    budget = BudgetPolicy(
        deadline_s=settings.max_scan_seconds,
        max_model_calls=settings.max_model_calls_per_scan,
        max_attempts=settings.max_external_attempts_per_scan,
        max_cost_usd=settings.max_scan_cost_usd,
    )

    def error(status: int, code: ErrorCode, message: str, scan_id: str) -> JSONResponse:
        body = ErrorResponse(
            schema_version=SCHEMA_VERSION,
            code=code,
            message=message,
            scan_id=scan_id,
            pipeline_id=pipeline_id,
            is_mock=settings.mock_mode,
        )
        return JSONResponse(status_code=status, content=body.model_dump(mode="json"))

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "app": kind.value,
            "mode": mode,
            "pipeline_id": pipeline_id,
            "live_pipeline_implemented": True,
            "ready": pipeline is not None,
            "version": __version__,
            "schema_version": SCHEMA_VERSION,
        }

    @app.post(
        "/v1/analyze",
        response_model=AnalysisResult,
        responses={
            400: {"model": ErrorResponse},
            413: {"model": ErrorResponse},
            501: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    async def analyze(image: UploadFile = File(...)):  # noqa: B008
        scan_id = uuid.uuid4().hex
        recorder = ScanRecorder(
            scan_id,
            pipeline_id,
            budget=budget,
            configuration_id=getattr(pipeline, "configuration_id", None),
            is_mock=settings.mock_mode,
            sink=app.state.telemetry,
        )

        def fail(status: int, code: ErrorCode, message: str) -> JSONResponse:
            recorder.finish(ScanStatus.FAILED, code)  # failed scans are recorded, not dropped
            return error(status, code, message, scan_id)

        data = await image.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            return fail(413, ErrorCode.IMAGE_TOO_LARGE, f"Upload exceeds {MAX_UPLOAD_BYTES} bytes.")
        try:
            with recorder.span(Stage.IMAGE_PREPARE):
                prepared = prepare_image(data, BASELINE)
        except ImagePreparationError as exc:
            return fail(413 if exc.code is ErrorCode.IMAGE_TOO_LARGE else 400, exc.code, str(exc))
        if pipeline is None and unavailable_reason is not None:
            return fail(503, ErrorCode.AUTHENTICATION, unavailable_reason)
        if pipeline is None:
            return fail(
                501,
                ErrorCode.NOT_IMPLEMENTED,
                f"The live {kind.value} pipeline is not implemented yet ({LIVE_ISSUE[kind]}). "
                "Set MOCK_MODE=true for a synthetic MOCK result.",
            )
        context = AnalysisContext(
            scan_id=scan_id,
            original_sha256=prepared.original_sha256,
            processed_sha256=prepared.processed_sha256,
            preprocessing_version=prepared.transform_version,
            pipeline_id=pipeline_id,
            region=settings.region,
            language=settings.language,
        )
        result = pipeline.analyze(prepared, context, recorder)
        if result.confidence.type is ConfidenceType.UNAVAILABLE:
            # Same structural rules for both apps; never from model or provider self-ratings.
            result.confidence = assess_confidence(result)
        result.input = InputProvenance(
            original_sha256=prepared.original_sha256,
            processed_sha256=prepared.processed_sha256,
            preprocessing_version=prepared.transform_version,
            processed_width_px=prepared.processed_size[0],
            processed_height_px=prepared.processed_size[1],
        )
        record = recorder.finish(
            ScanStatus(result.status.value), result.error and result.error.code
        )
        result.metrics.server_total_ms = record.server_total_ms
        result.metrics.external_attempts = record.attempts
        result.metrics.estimated_cost_usd = record.estimated_cost_usd
        return result

    return app
