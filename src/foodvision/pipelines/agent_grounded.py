"""App B `B_grounded` pipeline (POC-10): recognize -> retrieve -> select -> calculate.

- Model call 1 recognizes foods. Model call 2 happens only when deterministic ranking leaves
  items ambiguous, and covers all of them in one request. The shared budget (2 model calls,
  8 attempts, deadline, optional cost cap) is enforced by the Measurement Kit.
- Retrieval uses only the controlled USDA tools over `food_catalog`, through a database login
  that is checked at runtime to have no access to benchmark labels.
- The preparation filter is applied before ranking (in retrieval). A chosen ID must be one of
  that item's retrieved candidates or `no_match`; anything else leaves the item unresolved.
- Nutrients are calculated in code from the record and the image-estimated base grams. The
  low/high grams stay labeled assumptions, never a statistical interval.
- Unresolved items are excluded from totals (never zero) and make the result partial.
"""

from dataclasses import dataclass, field

from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from foodvision.contracts.errors import ErrorCode, ErrorDetail
from foodvision.contracts.requests import AnalysisContext
from foodvision.contracts.results import (
    AnalysisResult,
    FoodSource,
    MatchMethod,
    ModelProvenance,
    ResultItem,
    ResultStatus,
    TotalsStatus,
)
from foodvision.data.access import InferenceIsolationError, assert_inference_isolation
from foodvision.imaging.prepare import PreparedImage
from foodvision.matching.match_selection import (
    SELECTION_SCHEMA,
    SelectionOutput,
    is_clear_winner,
    load_selection_prompt,
    selection_request,
)
from foodvision.matching.retrieval import Candidate, CatalogTools
from foodvision.matching.selection import (
    InvalidSelectionError,
    validate_grounded_items,
    validate_selection,
)
from foodvision.measurement.budget import BudgetExceeded
from foodvision.measurement.events import Stage
from foodvision.measurement.retry import AttemptError
from foodvision.measurement.spans import ScanRecorder
from foodvision.nutrition.calculator import sum_totals
from foodvision.nutrition.units import NutritionError
from foodvision.pipelines.agent_recognition import hypothesis_item
from foodvision.providers.claude_vision import ClaudeVisionProvider
from foodvision.recognition.hypotheses import FoodHypothesis

PIPELINE_ID = "B_grounded"
MAX_ITEMS_PER_SCAN = 5  # plan §10: bound item count per scan
MAX_ALTERNATIVE_QUERIES = 2


@dataclass
class _Item:
    hypothesis: FoodHypothesis
    candidates: list[Candidate] = field(default_factory=list)
    chosen: str | None = None
    method: MatchMethod | None = None
    reasons: list[str] = field(default_factory=list)


class GroundedPipeline:
    is_mock = False
    pipeline_id = PIPELINE_ID

    def __init__(
        self,
        provider: ClaudeVisionProvider,
        engine: Engine,
        *,
        source_versions: list[str] | None = None,
        max_items: int = MAX_ITEMS_PER_SCAN,
    ) -> None:
        self.provider = provider
        self.engine = engine
        self.source_versions = source_versions
        self.max_items = max_items
        self.selection_prompt = load_selection_prompt()
        self.configuration_id = (
            f"{PIPELINE_ID}:{provider.configuration_id}:"
            f"{self.selection_prompt[0]}@{self.selection_prompt[2][:12]}:max-items-{max_items}"
        )
        self._isolation_checked = False

    def _failed(self, context, code: ErrorCode, message: str, retryable=False, provenance=None):
        return AnalysisResult(
            scan_id=context.scan_id,
            pipeline_id=PIPELINE_ID,
            configuration_id=self.configuration_id,
            is_mock=False,
            status=ResultStatus.FAILED,
            error=ErrorDetail(code=code, message=message, retryable=retryable),
            model_provenance=provenance,
        )

    # --- retrieval -----------------------------------------------------------------

    def _retrieve(self, tools: CatalogTools, item: _Item, region: str) -> None:
        h = item.hypothesis
        prep = h.preparation.catalog_state()
        outcome = None
        if h.visible_brand:
            outcome = tools.search_foods(h.search_description, prep, region, brand=h.visible_brand)
            if not outcome.matched:
                item.reasons.append("visible brand not in catalog; generic records searched")
        if outcome is None or not outcome.matched:
            outcome = tools.search_foods(h.search_description, prep, region)
        queries = [h.display_name, *h.alternatives][: MAX_ALTERNATIVE_QUERIES + 1]
        for query in queries:
            if outcome.matched:
                break
            outcome = tools.search_foods(query, prep, region)
        item.candidates = list(outcome.candidates)
        if not outcome.matched:
            item.reasons.append(f"no catalog match ({outcome.no_match_reason})")

    # --- selection -----------------------------------------------------------------

    def _select(self, image, items: list[_Item], recorder: ScanRecorder) -> list[str]:
        warnings: list[str] = []
        ambiguous = {}
        for index, item in enumerate(items):
            if not item.candidates:
                continue
            if is_clear_winner(item.candidates):
                item.chosen = item.candidates[0].food_id
                item.method = MatchMethod.DETERMINISTIC_RANKING
                item.reasons.append("catalog record chosen by deterministic ranking")
            else:
                ambiguous[index] = (item.hypothesis, item.candidates)
        if not ambiguous:
            return warnings
        try:
            output, _ = self.provider.choose_matches(
                image,
                selection_request(ambiguous),
                SELECTION_SCHEMA,
                SelectionOutput.model_validate,
                self.selection_prompt,
                recorder,
            )
            answers = {}
            for s in output.selections:
                answers.setdefault(s.item_index, s)
        except (BudgetExceeded, AttemptError) as exc:
            reason = getattr(exc, "reason", None) or getattr(exc, "detail", None) or "failed"
            warnings.append(
                f"Selection call unavailable ({reason}); the top-ranked candidate was used "
                "for ambiguous items."
            )
            for index in ambiguous:
                items[index].chosen = items[index].candidates[0].food_id
                items[index].method = MatchMethod.FALLBACK_TOP_CANDIDATE
                items[index].reasons.append(
                    "ambiguous match: selection call unavailable, top-ranked candidate used"
                )
            return warnings

        for index in ambiguous:
            item, answer = items[index], answers.get(index)
            if answer is None:
                item.reasons.append("ambiguous match: no selection returned; left unresolved")
                continue
            try:
                chosen = validate_selection(answer.choice, [c.food_id for c in item.candidates])
            except InvalidSelectionError:
                item.reasons.append(
                    "selection rejected: ID not among the retrieved candidates; left unresolved"
                )
                continue
            if chosen is None:
                item.reasons.append("selection: no candidate fits (no_match)")
            else:
                item.chosen = chosen
                item.method = MatchMethod.MODEL_SELECTION
                item.reasons.append("catalog record chosen among candidates by the model")
        return warnings

    # --- calculation ---------------------------------------------------------------

    def _ground(self, tools: CatalogTools, item: _Item) -> ResultItem:
        base = hypothesis_item(item.hypothesis)
        reasons = [r for r in base.uncertainty_reasons if "not yet matched" not in r]
        reasons += item.reasons
        if item.chosen is None:
            return base.model_copy(update={"uncertainty_reasons": reasons})
        try:
            nutrients = tools.calculate_nutrition(
                item.chosen, grams=item.hypothesis.portion_grams_base
            )
        except NutritionError as exc:
            reasons.append(f"not calculated: {exc}")
            return base.model_copy(update={"uncertainty_reasons": reasons})
        candidate = next(c for c in item.candidates if c.food_id == item.chosen)
        reasons.append(f"matched record: {candidate.name} [{candidate.data_type}]")
        if nutrients.missing():
            reasons.append(f"catalog lacks: {', '.join(nutrients.missing())}")
        return base.model_copy(
            update={
                "resolved": True,
                "food_source": FoodSource.USDA,
                "food_id": item.chosen,
                "match_method": item.method,
                "nutrients": nutrients,
                "uncertainty_reasons": reasons,
            }
        )

    # --- orchestration -------------------------------------------------------------

    def analyze(
        self, image: PreparedImage, context: AnalysisContext, recorder: ScanRecorder
    ) -> AnalysisResult:
        try:
            response = self.provider.recognize(image, recorder)
        except BudgetExceeded as exc:
            return self._failed(context, exc.code, f"Scan budget exhausted ({exc.reason}).")
        except AttemptError as exc:
            detail = getattr(exc, "detail", "") or exc.outcome.value
            retryable = exc.code in (ErrorCode.TIMEOUT, ErrorCode.QUOTA)
            return self._failed(context, exc.code, f"Vision request failed ({detail}).", retryable)
        provenance = ModelProvenance(
            provider=response.provider,
            model_requested=response.model_requested,
            model_served=response.model_served,
            fallback_served=response.fallback_served,
            prompt_version=response.prompt_version,
            prompt_sha256=response.prompt_sha256,
            sdk_version=response.sdk_version,
            effort=response.effort,
            stop_reason=response.stop_reason,
            request_id=response.request_id,
        )
        output = response.output
        common = dict(
            scan_id=context.scan_id,
            pipeline_id=PIPELINE_ID,
            configuration_id=self.configuration_id,
            is_mock=False,
            model_provenance=provenance,
        )
        warnings = []
        if response.fallback_served:
            warnings.append(
                f"Recognition answered by fallback model {response.model_served}; "
                "not the configured model."
            )
        if not output.image_assessment.is_food_image or not output.items:
            return AnalysisResult(
                status=ResultStatus.ABSTAINED,
                warnings=[*warnings, "No food was recognized in the image."],
                **common,
            )

        items = [_Item(h) for h in output.items[: self.max_items]]
        overflow = output.items[self.max_items :]
        try:
            with self.engine.connect() as conn:
                if not self._isolation_checked:
                    assert_inference_isolation(conn)
                    self._isolation_checked = True
                tools = CatalogTools(conn, source_versions=self.source_versions)
                with recorder.span(Stage.LOOKUP):
                    for item in items:
                        self._retrieve(tools, item, context.region)
                warnings += self._select(image, items, recorder)
                with recorder.span(Stage.CALCULATION):
                    result_items = [self._ground(tools, item) for item in items]
        except InferenceIsolationError:
            return self._failed(
                context,
                ErrorCode.AUTHENTICATION,
                "Refusing to run: the catalog database login can reach benchmark labels.",
                provenance=provenance,
            )
        except SQLAlchemyError:
            return self._failed(
                context, ErrorCode.PROVIDER_ERROR, "Food catalog unavailable.", True, provenance
            )

        for h in overflow:
            extra = hypothesis_item(h)
            reasons = [r for r in extra.uncertainty_reasons if "not yet matched" not in r]
            extra = extra.model_copy(
                update={
                    "uncertainty_reasons": [
                        *reasons,
                        f"not matched: over the {self.max_items}-item limit per scan",
                    ]
                }
            )
            result_items.append(extra)

        with recorder.span(Stage.VALIDATION):
            returned = {c.food_id for item in items for c in item.candidates}
            try:
                validate_grounded_items(result_items, returned)
            except InvalidSelectionError:
                return self._failed(
                    context,
                    ErrorCode.INVALID_SELECTION,
                    "Internal check failed: a cited food ID was not returned by retrieval.",
                    provenance=provenance,
                )
            totals = sum_totals([i.nutrients if i.resolved else None for i in result_items])
            if totals.status is TotalsStatus.COMPLETE:
                status = ResultStatus.COMPLETE
            else:
                status = ResultStatus.PARTIAL
                warnings.append(
                    "Totals are partial: unresolved items or unknown nutrients are excluded, "
                    "not counted as zero."
                )
            warnings.append(
                "Portions are estimated from the image; low/high grams are assumptions, "
                "not a statistical interval."
            )
            return AnalysisResult(
                status=status, items=result_items, totals=totals, warnings=warnings, **common
            )
