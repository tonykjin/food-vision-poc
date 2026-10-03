"""Catalog import and retrieval on real FDC fixture records (CC0), queried as the inference role.

Expected values are computed by hand from the fixture records, e.g. SR Legacy 168878 cooked
long-grain rice is 130 kcal / 100 g with a recorded 1 cup = 158 g portion.
"""

from pathlib import Path

import pytest
from sqlalchemy import func, select

from foodvision.catalog.preparation import PreparationState as Prep
from foodvision.catalog.usda_import import import_entries, load_dataset
from foodvision.data.models import food_nutrients, food_portions, food_records
from foodvision.matching.retrieval import (
    MAX_CANDIDATES,
    CatalogTools,
    NoMatchReason,
    UnknownFoodError,
)
from foodvision.nutrition.units import MissingPortionBasisError, UnsupportedUnitError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "fdc"
VERSIONS = {
    "FoundationFoods": "fixture-foundation",
    "SRLegacyFoods": "fixture-sr-legacy",
    "BrandedFoods": "fixture-branded",
}


def import_all(conn):
    reports = {}
    for key, version in VERSIONS.items():
        data_type, entries = load_dataset(FIXTURES / f"{key}.json")
        reports[key] = import_entries(conn, entries, data_type=data_type, source_version=version)
    return reports


@pytest.fixture(scope="module")
def catalog(migrated_db):
    from sqlalchemy import create_engine

    engine = create_engine(migrated_db)
    with engine.begin() as conn:
        first = import_all(conn)
    with engine.begin() as conn:
        second = import_all(conn)
        counts = {
            t.name: conn.execute(select(func.count()).select_from(t)).scalar_one()
            for t in (food_records, food_nutrients, food_portions)
        }
    engine.dispose()
    return first, second, counts


@pytest.fixture
def tools(catalog, login_as):
    with login_as("fv_inference").connect() as conn:
        yield CatalogTools(conn, source_versions=list(VERSIONS.values()))


def ids(outcome):
    return [c.food_id for c in outcome.candidates]


def test_import_is_idempotent_and_reports_gaps(catalog):
    first, second, counts = catalog
    foundation = first["FoundationFoods"]
    assert (foundation.inserted, foundation.null_entries) == (5, 1)
    assert foundation.rejected_negative["carbohydrate:1005"] == 1
    assert foundation.missing_nutrients["energy"] == 1  # olive oil, extra virgin
    assert first["BrandedFoods"].portions_skipped["branded_serving_ml_no_density"] == 1
    assert all(r.inserted == 0 and r.replaced > 0 for r in second.values())
    assert counts == {
        "food_records": 17,
        "food_nutrients": 68,
        "food_portions": counts["food_portions"],
    }
    assert counts["food_portions"] > 0


def test_cooked_rice_never_returns_dry_rice(tools):
    outcome = tools.search_foods("white rice", Prep.COOKED)
    assert outcome.matched and len(outcome.candidates) <= MAX_CANDIDATES
    assert {"fdc:168878", "fdc:169710"} <= set(ids(outcome))
    assert not {"fdc:168877", "fdc:169709", "fdc:2512381"} & set(ids(outcome))
    assert all(c.preparation_state in ("cooked", "not_stated") for c in outcome.candidates)


def test_dry_rice_never_returns_cooked_rice(tools):
    outcome = tools.search_foods("white rice", Prep.UNCOOKED)
    assert {"fdc:168877", "fdc:169709", "fdc:2512381"} <= set(ids(outcome))
    assert not {"fdc:168878", "fdc:169710"} & set(ids(outcome))


def test_raw_vs_cooked_chicken_and_commodity_before_fast_food(tools):
    cooked = ids(tools.search_foods("chicken breast", Prep.COOKED))
    assert "fdc:171477" in cooked and "fdc:331960" in cooked
    assert not {"fdc:171077", "fdc:2646170", "fdc:2727569"} & set(cooked)
    assert cooked.index("fdc:171477") < cooked.index("fdc:170356")  # Fast Foods ranks after
    raw = ids(tools.search_foods("chicken breast", Prep.UNCOOKED))
    assert {"fdc:171077", "fdc:2646170"} <= set(raw)
    assert not {"fdc:171477", "fdc:331960", "fdc:170356"} & set(raw)


def test_generic_and_branded_are_separate_pools(tools):
    generic = tools.search_foods("white rice")
    assert generic.matched and all(c.data_type != "Branded" for c in generic.candidates)
    branded = tools.search_foods("white rice", brand="MINUTE")
    assert ids(branded) == ["fdc:2397108"] and branded.candidates[0].data_type == "Branded"
    missing = tools.search_foods("white rice", brand="NO SUCH BRAND")
    assert missing.no_match_reason is NoMatchReason.NO_BRANDED_MATCH


def test_complete_records_rank_before_records_missing_energy(tools):
    olive = ids(tools.search_foods("olive oil"))
    assert olive.index("fdc:171413") < olive.index("fdc:748608")


@pytest.mark.parametrize(
    ("query", "region", "reason"),
    [
        ("chicken tikka masala", "US", NoMatchReason.NO_LEXICAL_MATCH),
        ("xyzzy", "US", NoMatchReason.NO_LEXICAL_MATCH),
        ("   ", "US", NoMatchReason.EMPTY_QUERY),
        ("white rice", "FR", NoMatchReason.NO_LEXICAL_MATCH),
    ],
)
def test_typed_no_match(tools, query, region, reason):
    outcome = tools.search_foods(query, region=region)
    assert not outcome.matched and outcome.no_match_reason is reason


def test_not_stated_records_stay_eligible(tools):
    outcome = tools.search_foods("olive oil", Prep.COOKED)
    assert "fdc:171413" in ids(outcome)  # preparation not stated: eligible, ranked after stated


def test_no_compatible_preparation(owner, login_as):
    with owner.begin() as conn:  # SYNTHETIC record: only a raw version exists
        import_entries(
            conn,
            [
                {
                    "fdcId": 990000001,
                    "description": "SYNTHETIC zzqfruit, raw",
                    "dataType": "SR Legacy",
                    "foodNutrients": [],
                    "foodPortions": [],
                }
            ],
            data_type="SR Legacy",
            source_version="fixture-synthetic",
            is_synthetic=True,
        )
    with login_as("fv_inference").connect() as conn:
        tools = CatalogTools(conn, source_versions=["fixture-synthetic"])
        assert tools.search_foods("zzqfruit", Prep.UNCOOKED).matched
        outcome = tools.search_foods("zzqfruit", Prep.COOKED)
    assert outcome.no_match_reason is NoMatchReason.NO_COMPATIBLE_PREPARATION


def test_calculate_nutrition_with_recorded_portions(tools):
    cup = tools.calculate_nutrition("fdc:168878", portion_name="1 cup")  # 158 g
    assert cup.energy_kcal == pytest.approx(205.4)  # 130 × 1.58
    assert cup.protein_g == pytest.approx(4.2502)  # 2.69 × 1.58
    assert tools.calculate_nutrition("fdc:168878", grams=150).energy_kcal == pytest.approx(195.0)
    serving = tools.calculate_nutrition("fdc:2397108", portion_name="1 serving (label: 1/2 cup)")
    assert serving.energy_kcal == pytest.approx(170.2)  # 370 × 0.46
    two = tools.calculate_nutrition("fdc:168878", portion_name="1 cup", count=2)
    assert two.energy_kcal == pytest.approx(410.8)


def test_household_measure_without_gram_weight_is_refused(tools):
    with pytest.raises(MissingPortionBasisError):
        tools.calculate_nutrition("fdc:168878", portion_name="1 bowl")
    assert tools.get_portions("fdc:2385707") == []  # milk: 240 ml label serving, no grams
    with pytest.raises(UnsupportedUnitError):  # per-100 ml record, gram portion, no density
        tools.calculate_nutrition("fdc:2385707", grams=240)


def test_rejected_negative_stays_unknown_in_calculation(tools):
    result = tools.calculate_nutrition("fdc:2727569", grams=100)
    assert result.carbohydrate_g is None and result.protein_g == pytest.approx(21.4)


@pytest.mark.parametrize("food_id", ["fdc:999999999", "fdc:abc", "168878", "usda:168878"])
def test_unknown_or_invented_ids_rejected(tools, food_id):
    with pytest.raises(UnknownFoodError):
        tools.get_food(food_id)
