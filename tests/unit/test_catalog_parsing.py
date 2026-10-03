"""Preparation parsing and nutrient selection on real FDC fixture records (CC0)."""

import json
from pathlib import Path

import pytest

from foodvision.catalog.preparation import PreparationState, preparation_state, preparation_text
from foodvision.catalog.usda_import import ImportReport, _select_nutrients, load_dataset

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "fdc"


def fixture(key: str) -> dict[int, dict]:
    return {f["fdcId"]: f for f in json.loads((FIXTURES / f"{key}.json").read_text())[key] if f}


@pytest.mark.parametrize(
    ("description", "state"),
    [
        ("Rice, white, long-grain, regular, raw, enriched", PreparationState.UNCOOKED),
        ("Rice, white, short-grain, enriched, uncooked", PreparationState.UNCOOKED),
        ("Rice, white, long-grain, regular, enriched, cooked", PreparationState.COOKED),
        # "precooked" is not "cooked": instant rice sold dry is uncooked.
        ("Rice, white, long-grain, precooked or instant, enriched, dry", PreparationState.UNCOOKED),
        (
            "Rice, white, long-grain, precooked or instant, enriched, prepared",
            PreparationState.COOKED,
        ),
        (
            "Chicken, broilers or fryers, breast, meat only, cooked, roasted",
            PreparationState.COOKED,
        ),
        ("Chicken breast tenders, breaded, uncooked", PreparationState.UNCOOKED),
        ("Oil, olive, salad or cooking", PreparationState.NOT_STATED),
        ("Beans, raw, then boiled", PreparationState.AMBIGUOUS),
    ],
)
def test_preparation_state(description, state):
    assert preparation_state(description) is state


def test_preparation_text_keeps_stated_parts():
    assert (
        preparation_text("Chicken, broilers or fryers, breast, meat only, cooked, roasted")
        == "cooked, roasted"
    )
    assert preparation_text("Oil, olive, salad or cooking") is None


def select(food: dict) -> tuple[dict, ImportReport]:
    report = ImportReport(source_version="test")
    rows = {r["nutrient"]: r for r in _select_nutrients(food["foodNutrients"], report)}
    return rows, report


def test_atwater_specific_energy_preferred_over_general():
    rows, report = select(fixture("FoundationFoods")[2512381])  # rice raw: 2048=370, 2047=359
    assert rows["energy"]["amount"] == 370 and rows["energy"]["source_nutrient_id"] == 2048
    assert report.nutrient_sources["energy:2048"] == 1


def test_negative_carbohydrate_is_rejected_not_clamped():
    rows, report = select(fixture("FoundationFoods")[2727569])  # carbohydrate -0.428
    assert rows["carbohydrate"]["amount"] is None
    assert report.rejected_negative["carbohydrate:1005"] == 1
    assert report.missing_nutrients["carbohydrate"] == 1
    assert rows["protein"]["amount"] == 21.4


def test_missing_nutrients_stay_null_and_fat_uses_documented_fallback():
    rows, report = select(fixture("FoundationFoods")[748608])  # olive oil: only NLEA fat
    assert rows["energy"]["amount"] is None and report.missing_nutrients["energy"] == 1
    assert rows["protein"]["amount"] is None and rows["carbohydrate"]["amount"] is None
    assert (rows["fat"]["amount"], rows["fat"]["source_nutrient_id"]) == (93.7, 1085)


def test_kilojoules_are_never_used_for_energy():
    food = {"foodNutrients": [{"nutrient": {"id": 1062, "unitName": "kJ"}, "amount": 544}]}
    rows, report = select(food)
    assert rows["energy"]["amount"] is None and report.missing_nutrients["energy"] == 1


def test_sr_legacy_uses_energy_1008():
    rows, _ = select(fixture("SRLegacyFoods")[168878])
    assert (rows["energy"]["amount"], rows["energy"]["source_nutrient_id"]) == (130, 1008)
    assert rows["protein"]["amount"] == 2.69 and rows["carbohydrate"]["amount"] == 28.2


def test_load_dataset_detects_type_and_keeps_nulls():
    data_type, entries = load_dataset(FIXTURES / "FoundationFoods.json")
    assert data_type == "Foundation" and None in entries
    assert load_dataset(FIXTURES / "BrandedFoods.json")[0] == "Branded"
