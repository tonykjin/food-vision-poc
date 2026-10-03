# USDA Food Catalog (POC-07)

App B's grounding catalog is a **documented subset** of USDA FoodData Central (FDC), imported into `food_catalog`. FDC data are public domain / CC0. Cite: *U.S. Department of Agriculture, Agricultural Research Service. FoodData Central. fdc.nal.usda.gov.*

Sources checked 2026-10-02:
- https://fdc.nal.usda.gov/download-datasets/
- https://fdc.nal.usda.gov/api-guide/
- https://fdc.nal.usda.gov/Foundation_Foods_Documentation/
- https://fdc.nal.usda.gov/GBFPD_Documentation/

## What is imported

The definition lives in [`catalog/usda-subset-v1.json`](../catalog/usda-subset-v1.json).

| Source | How | `source_version` | Foods (local import 2026-10-02) |
|---|---|---|---|
| Foundation Foods, April 2026 JSON | Download, SHA-256 checked | `fdc-foundation-2026-04-30` | 363 (plus 32 null entries skipped) |
| SR Legacy, April 2018 final JSON | Download, SHA-256 checked | `fdc-sr-legacy-2018-04` | 7,793 |
| Branded, 4 documented FDC IDs | API `POST /v1/foods` | `fdc-api-branded-<UTC date>` | 4 |

**Kept per food:**
- FDC ID, data type, source release, and retrieval time (API only)
- publication date, name, category, brand
- preparation text and parsed state
- reference basis, and the FDC nutrient ID and name for each core nutrient
- portions that have a recorded gram weight

**Not imported:**
- **Branded bulk download** (195 MB zipped, 3.1 GB unzipped). Branded data comes through the instrumented API fallback for documented IDs only.
- **FNDDS** (no pilot need yet).
- **Nutrients beyond energy, protein, fat and carbohydrate.**

### Nutrient rules

- **Energy (kcal):** FDC ID 2048 (Atwater specific), then 2047 (Atwater general), then 1008. Foundation dropped 1008 in Oct 2020; SR Legacy and Branded use 1008. kJ (1062) is never used.
- **Protein:** 1003.
- **Fat:** 1004, then 1085 (NLEA).
- **Carbohydrate:** 1005 (by difference), then 1050 (by summation).
- **Negative source values are rejected, never clamped to 0.** Foundation reports carbohydrate by difference as low as −0.705 g for some raw meats. The next documented ID is used, otherwise the value is stored as unknown (NULL). The database also refuses negative amounts.
- **Basis:** Foundation and SR Legacy are per 100 g edible portion. Branded is per 100 g or per 100 ml, "depending on which was received from the data provider" (GBFPD documentation).

### Portion rules

- A portion is stored **only when the source gives its gram weight**. SR "1 cup" (cooked long-grain rice, 158 g), Foundation RACC reference amounts, and a branded label serving in grams (MINUTE white rice, 46 g) all qualify.
- A branded serving in ml (whole milk, 240 ml) gets **no** gram portion: there's no density, so no grams. It's counted as `branded_serving_ml_no_density`.
- `calculate_nutrition` refuses any household measure that isn't recorded with grams, for example "1 bowl".

### Preparation state

Parsed from the FDC name by whole-word matching (`catalog/preparation.py`). Dry rice is labeled "raw", "uncooked" or "dry".

| State | Words | Example |
|---|---|---|
| `uncooked` | raw, uncooked, dry, unprepared | "Rice, white, long-grain, regular, raw" |
| `cooked` | cooked, prepared, boiled, roasted, fried, … | "…, cooked" |
| `not_stated` | neither | "Oil, olive, salad or cooking" |
| `ambiguous` | both kinds of words | "Beans, raw, then boiled" (example) |

"Precooked or instant, dry" counts as **uncooked**, because "precooked" isn't the word "cooked".

## Commands

Catalog writes need the owner role; the inference role can only read `food_catalog`.

```powershell
$env:MIGRATION_DATABASE_URL = "postgresql+psycopg://foodvision:<compose password>@127.0.0.1:5432/foodvision"
uv run alembic upgrade head

# 1. Download the two files listed in catalog/usda-subset-v1.json into data/fdc/ (git-ignored)
# 2. Import. Re-running replaces the same records (idempotent):
uv run foodvision import-usda --dataset data/fdc/FoodData_Central_foundation_food_json_2026-04-30.zip --version fdc-foundation-2026-04-30
uv run foodvision import-usda --dataset data/fdc/FoodData_Central_sr_legacy_food_json_2018-04.zip --version fdc-sr-legacy-2018-04

# 3. Branded FDC IDs documented in the manifest, via the API (reads USDA_API_KEY, never prints it)
uv run foodvision import-usda-api

# 4. Counts, missing nutrients and probe searches (see catalog/pilot-probes.json)
uv run foodvision catalog-report
```

Import refusals and reports:
- `import-usda` refuses an undocumented file, a `--version` that differs from the manifest, or a file whose SHA-256 doesn't match the documented release.
- `import-usda-api` refuses FDC IDs that aren't in the manifest.
- Reports are written to `work/catalog/` (git-ignored).

**API fallback limits** (api-guide): 1,000 requests per hour per IP, with HTTP 429 when exceeded.
- Each call uses the Measurement Kit retry engine: one transient retry, Retry-After honored, attempts recorded.
- Requests batch 20 IDs.
- The key travels as a query parameter and never appears in errors or records (tested).

## Retrieval tools

These live in `matching/retrieval.py` and read only `food_catalog`. Tests run them as a real `fv_inference` login.

- **`search_foods(query, preparation, region, limit≤5, category=, brand=)`**
  - PostgreSQL full-text search (English `tsvector` with a GIN index). There are no embeddings.
  - Strict mode requires every query word. Relaxed mode matches any word but still needs **at least half** of them.
  - **Preparation filter:**
    - A cooked request never returns uncooked records, and the reverse holds too.
    - Records that state no preparation stay eligible, but rank after stated matches.
  - **Branded vs generic:**
    - Generic search covers Foundation, then SR Legacy.
    - Branded records are searched **only** when a visible brand is given, and are never mixed into generic results.
  - **Ranking order:**
    1. stated preparation match
    2. commodity categories before Fast Foods, Restaurant, Luncheon Meats, Meals/Entrees, Snacks, Baby Foods and the regional category
    3. head-noun coverage
    4. query words matched
    5. known core nutrients
    6. `ts_rank`
    7. data-type precedence
    8. shorter name
  - **No match is typed:** `empty_query`, `no_lexical_match`, `no_compatible_preparation` or `no_branded_match`.
- **`get_food(food_id)`, `get_portions(food_id)`:** IDs look like `fdc:<FDC ID>`. Unknown or invented IDs raise `UnknownFoodError`. Pass `source_versions` to pin the catalog release.
- **`calculate_nutrition(food_id, grams=… | portion_name=…, count=1)`:** deterministic, via `nutrition/calculator.py`.

## Coverage and gaps

From the local import, 2026-10-02 (`catalog-report`):

- **Missing core nutrients (Foundation only):**
  - energy: 42 records (e.g. olive and canola oils, butter, dry beans "0% moisture", several raw vegetables)
  - carbohydrate: 52 records (including 10 negative values rejected)
  - fat: 15 records
  - protein: 11 records
  - SR Legacy and the 4 branded records are complete.
- **No gram portion:** 339 records.
- **Pilot probes** (`catalog/pilot-probes.json`, 22 searches): 21 matched; **"chicken tikka masala" has no match**. Composite restaurant dishes aren't in this subset; FNDDS would be the candidate source.
- **Ranking limits (lexical):**
  - The top-1 result isn't always the plainest record. For example, "olive oil" ranks a corn/peanut/olive blend first and "salmon, cooked" ranks salmon nuggets first, because FDC names fish "Fish, salmon, …".
  - In each case checked, a correct generic record is in the top 5.
  - App B's selection step (POC-10) chooses among the candidates. Don't treat the first candidate as the answer.
- **Region:** the catalog is the US FDC subset. Searches with any other `region` return `no_lexical_match`.

## Test fixtures

`tests/fixtures/fdc/` holds 17 real FDC records plus 1 null entry, unchanged except that `foodNutrients` is trimmed to the IDs the importer reads. Regenerate with `uv run python scripts/extract_fdc_fixtures.py`, which uses the public `DEMO_KEY` for branded.

Expected values below are computed by hand from the fixture records:

| FDC ID | Record | Fixture value | Expected in tests |
|---|---|---|---|
| 168878 | Rice, white, long-grain, regular, enriched, cooked (SR) | 130 kcal, 2.69 g protein /100 g; 1 cup = 158 g | 1 cup → 205.4 kcal, 4.2502 g protein; 150 g → 195 kcal |
| 2397108 | MINUTE white rice (Branded) | 370 kcal /100 g; serving 46 g | 1 serving → 170.2 kcal |
| 2512381 | Rice, white, long grain, unenriched, raw (Foundation) | 2048 = 370, 2047 = 359 | energy uses 2048 → 370 |
| 2727569 | Chicken, breast, meat and skin, raw (Foundation) | carbohydrate 1005 = −0.428 | carbohydrate unknown; protein 21.4 |
| 748608 | Oil, olive, extra virgin (Foundation) | only 1085 fat = 93.7 | energy, protein, carbohydrate unknown |
| 2385707 | LAND O LAKES whole milk (Branded) | per 100 ml; 240 ml serving | no portion; grams refused without density |
| 169709 / 169710 | Instant rice, "precooked … dry" / "… prepared" | n/a | uncooked / cooked |

These fixtures test arithmetic and retrieval behavior. They are **not** evidence of food-recognition accuracy.
