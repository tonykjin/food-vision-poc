"""Controlled catalog tools for App B (plan §9 B2): search_foods, get_food, get_portions,
calculate_nutrition. They read only food_catalog, never benchmark labels.

Retrieval is lexical (PostgreSQL full-text search), no embeddings:
1. strict: every query word must match (AND); 2. relaxed: any word (OR), flagged as such.
Relaxed matches must still contain at least half of the query words.
Filters are applied before ranking:
- preparation: a cooked request never returns an uncooked (raw/dry) record and vice versa;
  records that state no preparation are allowed but rank after stated matches;
  ambiguous records are excluded when a preparation is requested.
- data type: generic (Foundation, then SR Legacy) and Branded are separate pools; Branded is
  searched only when a visible brand is given, and is never mixed into generic results.
Ranking: stated-preparation match, then commodity categories before prepared/restaurant
ones, then head-noun coverage (FDC names read "Head, qualifiers": for "olive oil",
"Oil, olive" beats "Mayonnaise, ..., with olive oil"), then more query words matched,
then more known core nutrients (Foundation lacks energy for some oils/fats), then ts_rank,
data-type precedence and shorter names.
At most five candidates are returned; no match is a typed outcome with a reason.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from sqlalchemy import Connection, text

from foodvision.catalog.preparation import PreparationState
from foodvision.contracts.results import FoodSource, Nutrients
from foodvision.nutrition.calculator import (
    BasisKind,
    FoodRecord,
    Portion,
    ReferenceBasis,
    SourceNutrient,
    calculate_item,
)
from foodvision.nutrition.units import MissingPortionBasisError, QuantityUnit

MAX_CANDIDATES = 5
GENERIC_TYPES = ("Foundation", "SR Legacy")  # precedence order
ID_PREFIX = "fdc:"


class NoMatchReason(StrEnum):
    EMPTY_QUERY = "empty_query"
    NO_LEXICAL_MATCH = "no_lexical_match"
    NO_COMPATIBLE_PREPARATION = "no_compatible_preparation"
    NO_BRANDED_MATCH = "no_branded_match"


class UnknownFoodError(LookupError):
    pass


@dataclass(frozen=True)
class Candidate:
    food_id: str  # "fdc:<FDC ID>"
    name: str
    data_type: str
    category: str | None
    brand: str | None
    preparation_state: str
    source_version: str
    match_mode: str  # "strict" (all words) or "relaxed" (any word)
    rank: float


@dataclass(frozen=True)
class SearchOutcome:
    query: str
    candidates: list[Candidate] = field(default_factory=list)
    no_match_reason: NoMatchReason | None = None

    @property
    def matched(self) -> bool:
        return bool(self.candidates)


@dataclass(frozen=True)
class CatalogPortion:
    portion_name: str
    gram_weight: float
    portion_source: str


def _fdc_id(food_id: str) -> str:
    if not food_id.startswith(ID_PREFIX) or not food_id[len(ID_PREFIX) :].isdigit():
        raise UnknownFoodError(f"not a catalog food ID: {food_id!r}")
    return food_id[len(ID_PREFIX) :]


# Prepared/processed/restaurant categories rank after base commodity categories, so a
# generic "chicken breast" request is not answered first by fast food or deli meat.
DEPRIORITIZED_CATEGORIES = (
    "Fast Foods",
    "Restaurant Foods",
    "Sausages and Luncheon Meats",
    "Meals, Entrees, and Side Dishes",
    "Snacks",
    "Baby Foods",
    "American Indian/Alaska Native Foods",
)

_SEARCH_SQL = """
WITH qlex AS (SELECT tsvector_to_array(to_tsvector('english', :q)) AS lexemes),
hits AS (
  SELECT r.*, ts_rank(r.search_vector, {tsquery}) AS rank,
         (SELECT count(*) FROM unnest(qlex.lexemes) l
          WHERE r.search_vector @@ to_tsquery('simple', l)) AS matched,
         cardinality(qlex.lexemes) AS total,
         (SELECT count(*) FROM food_catalog.food_nutrients n
          WHERE n.food_id = r.food_id AND n.amount IS NOT NULL) AS known_nutrients,
         (SELECT count(*) FROM unnest(tsvector_to_array(
             to_tsvector('english', split_part(r.name, ',', 1)))) h
          WHERE h = ANY(qlex.lexemes))::float
         / greatest(1, cardinality(tsvector_to_array(
             to_tsvector('english', split_part(r.name, ',', 1))))) AS head_coverage
  FROM food_catalog.food_records r, qlex
  WHERE r.provider = 'USDA'
    AND r.search_vector @@ {tsquery}
    AND r.data_type = ANY(CAST(:data_types AS text[]))
    AND (CAST(:source_versions AS text[]) IS NULL
         OR r.source_version = ANY(CAST(:source_versions AS text[])))
    AND (CAST(:category AS text) IS NULL OR r.category ILIKE CAST(:category AS text))
    AND (CAST(:brand AS text) IS NULL OR r.brand ILIKE CAST(:brand AS text))
    AND (CAST(:prep AS text) IS NULL
         OR r.preparation_state IN (CAST(:prep AS text), 'not_stated'))
)
SELECT provider_food_id, name, data_type, category, brand, preparation_state,
       source_version, rank
FROM hits
WHERE matched * 2 >= total
ORDER BY (preparation_state = coalesce(CAST(:prep AS text), preparation_state)) DESC,
         (category = ANY(CAST(:deprioritized AS text[]))) ASC,
         head_coverage DESC,
         matched DESC,
         known_nutrients DESC,
         rank DESC,
         array_position(CAST(:data_types AS text[]), data_type),
         length(name),
         provider_food_id
LIMIT :limit
"""
_STRICT = "websearch_to_tsquery('english', :q)"
_RELAXED = (
    "to_tsquery('english', array_to_string(tsvector_to_array(to_tsvector('english', :q)), ' | '))"
)


class CatalogTools:
    def __init__(self, conn: Connection, source_versions: Sequence[str] | None = None) -> None:
        self.conn = conn
        self.source_versions = list(source_versions) if source_versions else None

    def search_foods(
        self,
        query: str,
        preparation: PreparationState | None = None,
        region: str = "US",
        limit: int = MAX_CANDIDATES,
        *,
        category: str | None = None,
        brand: str | None = None,
    ) -> SearchOutcome:
        query = query.strip()
        if not query:
            return SearchOutcome(query, no_match_reason=NoMatchReason.EMPTY_QUERY)
        if region != "US":
            # Catalog is the US FDC subset; other regions are a documented gap.
            return SearchOutcome(query, no_match_reason=NoMatchReason.NO_LEXICAL_MATCH)
        prep = (
            preparation.value
            if preparation in (PreparationState.COOKED, PreparationState.UNCOOKED)
            else None
        )
        params = {
            "q": query,
            "data_types": ["Branded"] if brand else list(GENERIC_TYPES),
            "source_versions": self.source_versions,
            "category": f"%{category}%" if category else None,
            "brand": f"%{brand}%" if brand else None,
            "prep": prep,
            "limit": max(1, min(limit, MAX_CANDIDATES)),
            "deprioritized": list(DEPRIORITIZED_CATEGORIES),
        }
        for mode, tsquery in (("strict", _STRICT), ("relaxed", _RELAXED)):
            rows = self.conn.execute(text(_SEARCH_SQL.format(tsquery=tsquery)), params).all()
            if rows:
                return SearchOutcome(
                    query,
                    candidates=[
                        Candidate(
                            food_id=f"{ID_PREFIX}{r.provider_food_id}",
                            name=r.name,
                            data_type=r.data_type,
                            category=r.category,
                            brand=r.brand,
                            preparation_state=r.preparation_state,
                            source_version=r.source_version,
                            match_mode=mode,
                            rank=float(r.rank),
                        )
                        for r in rows
                    ],
                )
        if brand:
            return SearchOutcome(query, no_match_reason=NoMatchReason.NO_BRANDED_MATCH)
        if prep is not None:
            unfiltered = self.conn.execute(
                text(_SEARCH_SQL.format(tsquery=_RELAXED)), params | {"prep": None}
            ).first()
            if unfiltered is not None:
                return SearchOutcome(query, no_match_reason=NoMatchReason.NO_COMPATIBLE_PREPARATION)
        return SearchOutcome(query, no_match_reason=NoMatchReason.NO_LEXICAL_MATCH)

    def _record_row(self, food_id: str):
        rows = self.conn.execute(
            text(
                "SELECT food_id, provider_food_id, source_version, data_type, basis_kind, "
                "basis_quantity, basis_unit, density_g_per_ml FROM food_catalog.food_records "
                "WHERE provider = 'USDA' AND provider_food_id = :id "
                "AND (CAST(:versions AS text[]) IS NULL "
                "OR source_version = ANY(CAST(:versions AS text[])))"
            ),
            {"id": _fdc_id(food_id), "versions": self.source_versions},
        ).all()
        if len(rows) != 1:
            raise UnknownFoodError(
                f"{food_id} matches {len(rows)} catalog records; pin source_versions"
                if rows
                else f"{food_id} is not in the catalog"
            )
        return rows[0]

    def get_food(self, food_id: str) -> FoodRecord:
        row = self._record_row(food_id)
        nutrients = self.conn.execute(
            text(
                "SELECT nutrient, amount, unit FROM food_catalog.food_nutrients WHERE food_id = :f"
            ),
            {"f": row.food_id},
        ).all()
        source = FoodSource.USDA
        return FoodRecord(
            food_id=food_id,
            source=source,
            basis=ReferenceBasis(
                kind=BasisKind(row.basis_kind),
                quantity=float(row.basis_quantity),
                unit=QuantityUnit(row.basis_unit),
            ),
            nutrients={
                n.nutrient: SourceNutrient(
                    amount=None if n.amount is None else float(n.amount), unit=n.unit
                )
                for n in nutrients
            },
            density_g_per_ml=None if row.density_g_per_ml is None else float(row.density_g_per_ml),
        )

    def get_portions(self, food_id: str) -> list[CatalogPortion]:
        row = self._record_row(food_id)
        return [
            CatalogPortion(p.portion_name, float(p.gram_weight), p.portion_source)
            for p in self.conn.execute(
                text(
                    "SELECT portion_name, gram_weight, portion_source FROM "
                    "food_catalog.food_portions WHERE food_id = :f ORDER BY id"
                ),
                {"f": row.food_id},
            ).all()
        ]

    def calculate_nutrition(
        self,
        food_id: str,
        grams: float | None = None,
        portion_name: str | None = None,
        count: float = 1.0,
    ) -> Nutrients:
        """Deterministic nutrients for `grams`, or for `count` × a portion that has a recorded
        gram weight. A household measure without a gram weight in the data is refused."""
        if (grams is None) == (portion_name is None):
            raise ValueError("give exactly one of grams or portion_name")
        if portion_name is not None:
            match = [p for p in self.get_portions(food_id) if p.portion_name == portion_name]
            if not match:
                raise MissingPortionBasisError(
                    f"{food_id} has no portion {portion_name!r} with a recorded gram weight"
                )
            grams = match[0].gram_weight * count
        return calculate_item(self.get_food(food_id), Portion(amount=grams, unit=QuantityUnit.G))
