# Reference collection protocol (POC-12)

How to collect, reference and review benchmark meals. Plan §11 sets the targets: start with **30 real development groups**, then grow toward 100 development, 100 calibration and 100 test groups.

**Never** fill gaps with made-up meals, copy app output into a reference, or count the synthetic examples in `benchmarks/examples/` as collected data.

## 1. One-time setup

1. Create a private folder **outside Git**, for example `C:\Users\tonyj\food-vision-private\benchmark\`, with `photos\` and `groups\` inside it. A cloud-synced folder (OneDrive, Dropbox) copies participants' photos to that service; decide deliberately before using one.
2. Create `.env.evaluator.local` in the repo root (it's git-ignored) with:
   - `BENCHMARK_DATA_DIR=` the private folder above
   - `EVALUATOR_DATABASE_URL=` an `fv_evaluator` login (only needed for `load-manifest`). In `psql` on the local database: `CREATE ROLE <name> LOGIN IN ROLE fv_evaluator;` then `\password <name>`. Never reuse an app's `DATABASE_URL`.
3. Equipment:
   - A digital kitchen scale with **1 g resolution** and at least 3 kg capacity. Check it before each session with something of known weight, such as an unopened 500 g package; note any difference over 2 g.
   - A phone camera.

## 2. Weighing (before anyone eats)

Use a printed or phone copy of `collection-form.md`, one per meal.

1. **Name the group:** `yyyymmdd-short-name-nn` in lowercase, for example `20261012-chicken-rice-01`. Every photo of this meal belongs to this one group.
2. **Weigh each component separately**, in a tared bowl or on the tared plate, and write down the grams:
   - **Edible part only.** Remove bones, pits, peels and inedible skins first. If that isn't possible before eating, weigh the served item now and the inedible leftovers afterwards; edible grams = served − leftovers.
   - **Added fats and sauces are components too.** Weigh the oil or butter used: weigh the bottle or pack before and after, or pour into a tared spoon. Weigh dressings and sauces on their own.
   - Note the **preparation state** of each component: raw, boiled, steamed, grilled, fried, baked, roasted, sautéed or cooked.
3. **Packaged items:** if the whole package is eaten, the label's net weight can be used (measurement `label_declared`). Otherwise weigh the eaten amount. Photograph the nutrition label **separately as reference evidence**. It is never a benchmark photo.
4. **Homemade mixed dishes** (stews, casseroles, curries) get a recipe reference:
   - Weigh every **raw** ingredient.
   - Weigh the **cooked yield**: the pot with food minus the empty pot.
   - Weigh the **served portion**.
5. **Leftovers:** if anything isn't eaten, weigh it per component and subtract. The reference is what was eaten.

## 3. Photographing (after plating, before eating)

The photo is the only input the apps get, so it must look like a normal meal photo.

1. Use the phone's main camera at 1x: no zoom, filters, portrait mode or edits. Use even light (daylight or ordinary room light) and avoid flash glare.
2. Take **shot 1 from directly above**, about 40-50 cm away, with the whole plate in frame and a little margin. Nothing cropped.
3. Take **shot 2 at about 45°** from the side, so depth is visible.
4. **Never show the answer.** No scale, scale display, written weights, labels, receipts or recipe notes may be in the frame. Cutlery that is normally there is fine; don't add rulers or other reference objects.
5. Keep the original files. Convert iPhone HEIC to JPEG; the apps accept JPEG, PNG and WebP. Copy them into `photos\` under the private folder.
6. The **same dish cooked again** on another day is a new group with the **same `family_id`** (for example `chicken-rice-recipe`), so all versions stay in one split.

## 4. Reference values (choose them independently)

Pick source values **without looking at any app's output** for this meal.

- **Generic foods:** search FoodData Central (https://fdc.nal.usda.gov) for the record matching the identity **and** preparation (for example "Rice, white, long-grain, regular, enriched, cooked", not the dry rice). Record:
  - the FDC ID (`fdc:168878`), the data type and the release
  - the per 100 g values for energy (kcal), protein, carbohydrate (by difference) and total fat, exactly as shown
- **Packaged foods:** the label values, either per serving with the serving size in grams or per 100 g as printed, plus the label's date or batch. This gives grade B.
- **Restaurant items:** the published menu nutrition with the menu date. Grade B.
- Leave a nutrient **out** (or `null`) if the source doesn't give it. Never write 0 for "unknown".
- A per 100 ml or per-ml-serving source only works with a density. Without one, the tools report an error rather than guessing.

## 5. Grades

| Grade | Requirement | Used for |
|---|---|---|
| A | Every component (or recipe ingredient, yield and served portion) **weighed**, and generic source values reviewed | Primary numeric accuracy |
| B | Exact label or menu values with a reliable eaten amount (weighed or the full package) | Primary numeric accuracy |
| C | Any amount estimated rather than weighed | Qualitative discussion only; excluded from primary accuracy |

`validate-manifest` rejects a grade that the recorded measurements don't support.

**Difficult or unsupported inputs** (a label-only photo, a non-food photo) use `expected_outcome: "abstain"` with no nutrient reference, because abstaining is the correct answer for them.

## 6. Writing the group file

1. Copy the closest example from `benchmarks/examples/` into `groups\<group_id>.json` in the private folder. Replace every `SYNTHETIC` value and set `"is_synthetic": false`.
2. Photos: set `file` (relative to the private folder, for example `photos/20261012-chicken-rice-01-top.jpg`) and its SHA-256 (PowerShell: `(Get-FileHash <file>).Hash.ToLower()`).
   - `rights`: `owned` for team photos, or `consented` with the consent form reference.
   - `retain_until`: the date agreed for keeping the photo.
3. Leave `split` as `null`. `assign-splits` sets it, so nobody chooses which meals become test meals.
4. Keep `review.status` as `draft` until reviewed.

## 7. Review

1. The reviewer checks four things against the form and the photos:
   - identity and preparation
   - the grams and the leftover arithmetic
   - that the source record matches the identity **and** preparation
   - that nothing in the photo reveals the answer
2. The reviewer adds `{"reviewer": "<name>", "reviewed_on": "<date>"}` and sets `status` to `reviewed`.
3. Plan §11 asks for a **second reviewer** on difficult identities or recipes. Only one reviewer is available right now, so single-reviewer groups are flagged in every report. Add a second reviewer when one becomes available.

## 8. Commands

```powershell
uv run foodvision validate-manifest --manifest <private>\groups   # errors, human work, progress
uv run foodvision assign-splits --manifest <private>\groups --dry-run
uv run foodvision assign-splits --manifest <private>\groups        # writes splits into the files
uv run foodvision load-manifest --manifest <private>\groups --reference-version pilot-v1
```

`load-manifest` loads only reviewed groups with a split. It records the version as `pilot-v1@<manifest hash>`, so every evaluation names the exact reference data it used. It refuses invalid manifests and any login that isn't an evaluator login.
