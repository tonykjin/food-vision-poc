"""Extract small test fixtures from official FoodData Central data (public domain / CC0).

Usage (from the repo root, after downloading the files listed in catalog/usda-subset-v1.json
into data/fdc/):

    uv run python scripts/extract_fdc_fixtures.py

Generic records come from the downloads; Branded records come from the FDC API with the
public DEMO_KEY (no project secret). Records are copied unchanged except that foodNutrients
is trimmed to the nutrient IDs the importer reads (plus kJ 1062 to prove it is ignored).
"""

import json
import zipfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures" / "fdc"
KEEP_NUTRIENTS = {1003, 1004, 1005, 1008, 1050, 1062, 1085, 2047, 2048}

FIXTURES = {
    "FoundationFoods": (
        "FoodData_Central_foundation_food_json_2026-04-30.zip",
        [2512381, 2646170, 2727569, 331960, 748608],
    ),
    "SRLegacyFoods": (
        "FoodData_Central_sr_legacy_food_json_2018-04.zip",
        [168877, 168878, 169709, 169710, 171077, 171477, 170356, 171413],
    ),
}
BRANDED_IDS = [2397108, 2059175, 2092152, 2385707]


def trim(food: dict) -> dict:
    food = dict(food)
    food["foodNutrients"] = [
        n
        for n in food.get("foodNutrients") or []
        if n and (n.get("nutrient") or {}).get("id") in KEEP_NUTRIENTS
    ]
    food.pop("inputFoods", None)
    return food


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for key, (archive, ids) in FIXTURES.items():
        with zipfile.ZipFile(ROOT / "data" / "fdc" / archive) as z:
            foods = next(iter(json.loads(z.read(z.namelist()[0])).values()))
        by_id = {f["fdcId"]: f for f in foods if f}
        records = [trim(by_id[i]) for i in ids]
        if key == "FoundationFoods":
            records.append(None)  # the real download contains null entries
        path = OUT / f"{key}.json"
        path.write_text(json.dumps({key: records}, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)} ({len(records)} entries)")
    response = httpx.post(
        "https://api.nal.usda.gov/fdc/v1/foods",
        params={"api_key": "DEMO_KEY"},
        json={"fdcIds": BRANDED_IDS, "format": "full"},
        timeout=30,
    )
    response.raise_for_status()
    branded = [trim(f) for f in response.json()]
    path = OUT / "BrandedFoods.json"
    path.write_text(json.dumps({"BrandedFoods": branded}, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)} ({len(branded)} entries)")


if __name__ == "__main__":
    main()
