"""Opt-in live fatsecret smoke test: one owned image, at most one token + one image request.

Never runs in CI. Requires ENABLE_LIVE_API_TESTS=true (shell or the app's env file) and
--confirm-one-request on every run. Prints a
payload-free summary only (status, codes, counts, field presence, timings): no food names,
nutrient values, tokens or provider messages are printed or written anywhere.
"""

import uuid
from pathlib import Path

from foodvision.config import AppKind, load_settings
from foodvision.contracts.requests import AnalysisContext
from foodvision.imaging.prepare import ImagePreparationError, prepare_image
from foodvision.imaging.profiles import BASELINE
from foodvision.measurement.budget import BudgetPolicy
from foodvision.measurement.events import ScanStatus
from foodvision.measurement.spans import ScanRecorder

# One token request + one image request, no retries.
SMOKE_BUDGET = BudgetPolicy(
    deadline_s=45, max_model_calls=0, max_attempts=2, max_retries_per_request=0
)


def smoke_fatsecret(image_path: str, confirmed: bool) -> int:
    settings = load_settings(AppKind.PROVIDER)
    if not settings.enable_live_api_tests:
        print(
            "Refusing: set ENABLE_LIVE_API_TESTS=true (shell or .env.provider.local) "
            "to allow one live fatsecret request."
        )
        return 2
    if not confirmed:
        print("Refusing: pass --confirm-one-request (one token + one image request, no retries).")
        return 2
    if settings.fatsecret_client_id is None or settings.fatsecret_client_secret is None:
        print("Refusing: FATSECRET_CLIENT_ID/SECRET missing (foodvision doctor --app provider).")
        return 2
    try:
        prepared = prepare_image(Path(image_path).read_bytes(), BASELINE)
    except (OSError, ImagePreparationError) as exc:
        print(f"Image rejected before any request: {type(exc).__name__}")
        return 2

    from foodvision.pipelines.provider_native import ProviderNativePipeline
    from foodvision.providers.fatsecret_client import FatsecretClient

    scan_id = uuid.uuid4().hex
    recorder = ScanRecorder(scan_id, "A_native", budget=SMOKE_BUDGET, is_mock=False)
    pipeline = ProviderNativePipeline(
        FatsecretClient(settings.fatsecret_client_id, settings.fatsecret_client_secret)
    )
    context = AnalysisContext(
        scan_id=scan_id,
        original_sha256=prepared.original_sha256,
        processed_sha256=prepared.processed_sha256,
        preprocessing_version=prepared.transform_version,
        pipeline_id="A_native",
    )
    result = pipeline.analyze(prepared, context, recorder)
    record = recorder.finish(
        ScanStatus(result.status.value), result.error.code if result.error else None
    )
    print("fatsecret live smoke (payload-free summary)")
    print(f"  status             {result.status.value}")
    print(f"  error_code         {result.error.code.value if result.error else '-'}")
    if result.error:
        print(f"  error_detail       {result.error.message}")  # our text: codes only
    resolved = sum(i.resolved for i in result.items)
    print(f"  items              {len(result.items)} ({resolved} resolved)")
    print(f"  food_id present    {all(i.food_id for i in result.items) if result.items else '-'}")
    print(
        f"  serving_id present {all(i.serving_id for i in result.items) if result.items else '-'}"
    )
    for key in ("energy_kcal", "protein_g", "carbohydrate_g", "fat_g"):
        known = sum(getattr(i.nutrients, key) is not None for i in result.items)
        print(f"  {key:<18} known for {known}/{len(result.items)} items")
    print(f"  totals status      {result.totals.status.value}")
    for attempt in record.attempt_records:
        print(
            f"  attempt            {attempt.operation} {attempt.outcome.value} "
            f"{attempt.http_status_class or '-'} {attempt.duration_ms:.0f} ms"
        )
    print(f"  server_total_ms    {record.server_total_ms:.0f}")
    print("Nothing was stored. Record these results by hand in docs/provider-readiness.md.")
    return 0 if result.status.value != "failed" else 1


# Recognition-only: one model call. Grounded: recognition + at most one selection call.
# No retries in either case.
VISION_SMOKE_BUDGET = BudgetPolicy(
    deadline_s=120, max_model_calls=1, max_attempts=1, max_retries_per_request=0
)
GROUNDED_SMOKE_BUDGET = BudgetPolicy(
    deadline_s=120, max_model_calls=2, max_attempts=2, max_retries_per_request=0
)


def smoke_vision(image_path: str, confirmed: bool) -> int:
    """Opt-in live App B check: one image, exactly one model request, payload-free output."""
    settings = load_settings(AppKind.AGENT)
    if not settings.enable_live_api_tests:
        print(
            "Refusing: set ENABLE_LIVE_API_TESTS=true (shell or .env.agent.local) "
            "to allow one live vision request."
        )
        return 2
    if not confirmed:
        print("Refusing: pass --confirm-one-request (one model request, no retries).")
        return 2
    if settings.anthropic_api_key is None:
        print("Refusing: ANTHROPIC_API_KEY missing (foodvision doctor --app agent).")
        return 2
    try:
        prepared = prepare_image(Path(image_path).read_bytes(), BASELINE)
    except (OSError, ImagePreparationError) as exc:
        print(f"Image rejected before any request: {type(exc).__name__}")
        return 2

    from foodvision.pipelines.agent_recognition import RecognitionOnlyPipeline
    from foodvision.providers.claude_vision import ClaudeVisionProvider, VisionConfig

    scan_id = uuid.uuid4().hex
    grounded = settings.pipeline_mode == "grounded" and settings.database_url is not None
    budget = GROUNDED_SMOKE_BUDGET if grounded else VISION_SMOKE_BUDGET
    recorder = ScanRecorder(scan_id, "B_live_smoke", budget=budget)
    config = VisionConfig(
        model=settings.vision_model,
        effort=settings.vision_effort,
        max_tokens=settings.vision_max_tokens,
        refusal_fallback=settings.vision_refusal_fallback,
    )
    vision = ClaudeVisionProvider(settings.anthropic_api_key, config)
    if grounded:
        from sqlalchemy import create_engine

        from foodvision.pipelines.agent_grounded import GroundedPipeline

        engine = create_engine(settings.database_url.get_secret_value())
        pipeline = GroundedPipeline(vision, engine)
    else:
        pipeline = RecognitionOnlyPipeline(vision)
    context = AnalysisContext(
        scan_id=scan_id,
        original_sha256=prepared.original_sha256,
        processed_sha256=prepared.processed_sha256,
        preprocessing_version=prepared.transform_version,
        pipeline_id=pipeline.pipeline_id,
    )
    result = pipeline.analyze(prepared, context, recorder)
    record = recorder.finish(
        ScanStatus(result.status.value), result.error.code if result.error else None
    )
    prov = result.model_provenance
    items = result.items
    print("vision live smoke (payload-free summary)")
    print(f"  pipeline           {result.pipeline_id}")
    print(f"  status             {result.status.value}")
    print(f"  error              {result.error.message if result.error else '-'}")
    if prov is not None:
        print(f"  model requested    {prov.model_requested}")
        print(f"  model served       {prov.model_served} (fallback: {prov.fallback_served})")
        print(f"  stop_reason        {prov.stop_reason}")
        print(f"  prompt             {prov.prompt_version} sha256 {prov.prompt_sha256[:12]}")
        print(f"  sdk                anthropic {prov.sdk_version}")
    print(f"  items              {len(items)} ({sum(i.resolved for i in items)} grounded)")
    print(f"  totals status      {result.totals.status.value}")
    for key in ("energy_kcal", "protein_g", "carbohydrate_g", "fat_g"):
        known = sum(getattr(i.nutrients, key) is not None for i in items)
        print(f"  {key:<18} known for {known}/{len(items)} items")
    print(f"  model calls        {record.model_calls}; blocked {record.blocked_attempts}")
    # Reason categories only (fixed phrases from our code), never food names or values.
    categories = {
        "no catalog match": "no catalog match",
        "selection no_match": "no candidate fits (no_match)",
        "selection rejected": "not among the retrieved candidates",
        "no selection returned": "no selection returned",
        "not calculated": "not calculated:",
        "over item limit": "item limit per scan",
        "top candidate fallback": "top-ranked candidate used",
        "chosen deterministically": "deterministic ranking",
        "chosen by model": "chosen among candidates by the model",
        "catalog lacks nutrient": "catalog lacks:",
    }
    for label, phrase in categories.items():
        count = sum(any(phrase in r for r in i.uncertainty_reasons) for i in items)
        if count:
            print(f"  reason             {label}: {count}")
    print(f"  preparation stated {sum(i.preparation is not None for i in items)}/{len(items)}")
    print(f"  brand present      {sum(i.visible_brand is not None for i in items)}/{len(items)}")
    print(f"  with alternatives  {sum(bool(i.alternatives) for i in items)}/{len(items)}")
    composite = sum(any("composite" in r for r in i.uncertainty_reasons) for i in items)
    print(f"  composite dishes   {composite}")
    for attempt in record.attempt_records:
        tokens = attempt.usage
        cost = attempt.cost.amount_usd
        print(
            f"  attempt            {attempt.operation} {attempt.outcome.value} "
            f"{attempt.duration_ms:.0f} ms; tokens in/out "
            f"{tokens.input_tokens if tokens else '-'}/{tokens.output_tokens if tokens else '-'}; "
            f"est. cost {'unknown' if cost is None else f'${cost:.4f}'}"
        )
    print("Nothing was stored. No food names or portion values were printed.")
    return 0 if result.status.value != "failed" else 1
