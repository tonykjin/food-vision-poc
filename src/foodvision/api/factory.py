"""Shared FastAPI factory. Each app registers only its own pipeline and settings."""

import uuid

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse

from foodvision import __version__
from foodvision.config import AppKind, AppSettings, load_settings
from foodvision.contracts.errors import ErrorCode, ErrorResponse
from foodvision.contracts.requests import AnalysisContext
from foodvision.contracts.results import SCHEMA_VERSION, AnalysisResult, InputProvenance
from foodvision.imaging.prepare import ImagePreparationError, prepare_image
from foodvision.imaging.profiles import BASELINE
from foodvision.measurement.budget import BudgetPolicy
from foodvision.measurement.events import ScanStatus, Stage
from foodvision.measurement.sinks import InMemorySink
from foodvision.measurement.spans import ScanRecorder
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


def create_app(kind: AppKind, settings: AppSettings | None = None) -> FastAPI:
    settings = settings if settings is not None else load_settings(kind)
    mode = "mock" if settings.mock_mode else "live"
    pipeline_id = PIPELINE_IDS[kind][mode]
    pipeline = MockPipeline(pipeline_id) if settings.mock_mode else None

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
            "live_pipeline_implemented": False,
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
