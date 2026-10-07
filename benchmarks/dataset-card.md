# Dataset card: food-vision pilot benchmark (pilot-v1)

**Status (2026-10-07): 0 real groups collected.** The tools are ready; collection hasn't started. Nothing here supports an accuracy claim until reviewed real groups exist. Run `uv run foodvision validate-manifest` on the private manifest for the current count.

## Purpose

Compare App A (fatsecret) and App B (vision model + USDA) on identical meal photos against independent references (plan §11). Image-only: weights are never given to the apps.

## Composition (planned vs collected)

| Category | Planned groups | Reference method | Collected (reviewed, A/B) |
|---|---:|---|---:|
| Single generic foods | 90 | Edible weight + reference composition | 0 |
| Separated mixed plates | 90 | Each component weighed + source values | 0 |
| Composite dishes | 60 | Full recipe, cooked yield, served weight | 0 |
| Branded/packaged, restaurant | 30 | Exact label/menu values + amount eaten | 0 |
| Difficult/unsupported | 30 | Expected abstention, or a reference where possible | 0 |

First milestone: **30 reviewed real development groups**. A group is one meal or product; several photos of it are one group, not several samples.

## Splits

- Development, calibration and test, assigned by `foodvision assign-splits`:
  - Families (the same recipe or product family) always share a split.
  - The order is a seeded hash (seed `pilot-v1`), not the collector's choice.
  - Splits never change once set.
- Development fills first, up to 30 groups. Later groups go to calibration or test by hash.
- **Caveat:** the development groups are collected earlier than the others, so a seasonal or menu drift between splits is possible. Category balance per split isn't enforced; it's reported, so imbalance is visible.

## References

- Reference nutrients are **calculated** from edible grams and source values with an explicit basis (per 100 g, per 100 ml with a density, or per serving with a size). They're never typed in, and unknown values stay unknown.
- Grades: A (weighed, reviewed source), B (label/menu with a reliable amount), C (estimated, excluded from primary accuracy).
- Labels and recipes are references, **not laboratory assays** of the photographed meal.

## Known limitations

- **Shared-source dependence:** generic references use USDA records, and so does App B, which can flatter App B. Label/menu and recipe subsets, plus scoring identity and grams separately, partly address this (plan §11).
- **Single reviewer:** only one reviewer is available; every single-reviewer group is flagged.
- **Small pilot, one region (US):** results may not generalize; rare categories may stay inconclusive.
- **Image retention:** photos are kept until each photo's `retain_until` date.

## Consent and access

- Only photos taken by the team (`owned`) or with signed consent (`consented`). Stock, web and third-party images can't be recorded.
- Private data (photos, group files, filled forms) lives outside Git in `BENCHMARK_DATA_DIR`.
- Loaded references sit in the `benchmark` schema, which the inference role can't read. Loading requires an `fv_evaluator` login and checks that boundary first.

## Versioning

Each load records `reference_version` as `<name>@<manifest sha256 prefix>`, and sample IDs include it, so earlier (locked) versions are never overwritten. The format is `benchmark-manifest-v1` (`src/foodvision/benchmark/manifest.py`). Synthetic examples are in `benchmarks/examples/`, marked `is_synthetic: true`, and are never counted.
