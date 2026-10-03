"""Shared FastAPI factory. Each app registers only its own pipeline and settings."""

import time
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
        started = time.perf_counter_ns()
        scan_id = uuid.uuid4().hex
        data = await image.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            return error(
                413,
                ErrorCode.IMAGE_TOO_LARGE,
                f"Upload exceeds {MAX_UPLOAD_BYTES} bytes.",
                scan_id,
            )
        try:
            prepared = prepare_image(data, BASELINE)
        except ImagePreparationError as exc:
            status = 413 if exc.code is ErrorCode.IMAGE_TOO_LARGE else 400
            return error(status, exc.code, str(exc), scan_id)
        if pipeline is None:
            return error(
                501,
                ErrorCode.NOT_IMPLEMENTED,
                f"The live {kind.value} pipeline is not implemented yet ({LIVE_ISSUE[kind]}). "
                "Set MOCK_MODE=true for a synthetic MOCK result.",
                scan_id,
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
        result = pipeline.analyze(prepared, context)
        result.input = InputProvenance(
            original_sha256=prepared.original_sha256,
            processed_sha256=prepared.processed_sha256,
            preprocessing_version=prepared.transform_version,
            processed_width_px=prepared.processed_size[0],
            processed_height_px=prepared.processed_size[1],
        )
        result.metrics.server_total_ms = (time.perf_counter_ns() - started) / 1_000_000
        return result

    return app
