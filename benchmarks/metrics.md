# Benchmark metric definitions (`metrics-v1`)

Implemented in `src/foodvision/benchmark/metrics.py` and taken from plan §10-§11. **Freeze these before looking at results.** A change needs a new version and a reason recorded here, never "the numbers look better".

## Units of analysis

- **Attempt:** one fresh analysis of one photo by one configuration. With 3 repeats, each photo has 3 attempts per configuration. Every attempt stays in its denominator, including failures, abstentions, partial results, timeouts and exceptions.
- **Group:** one meal or product (several photos and all repeats). Intervals resample **groups**, never single repeats.
- **Scorable reference:** expected outcome `estimate`, grade A or B, and all four reference nutrients known. Grade C and abstain-expected groups are reported separately.
- **Scored output:** the first automatic result. Corrections are never part of a batch.

## Nutrient errors (energy kcal, protein, carbohydrate, fat in g)

| Metric | Formula | Computed over |
|---|---|---|
| Absolute error | \|predicted − reference\| | complete results with all four totals known, on scorable references |
| Signed error | predicted − reference (shows systematic over- or underestimation) | same |
| Relative error | \|predicted − reference\| / reference, **only when reference ≥ the floor** (50 kcal; 3 g). Below the floor it isn't computed and the absolute error stands | same |

Partial results are never scored as whole-meal estimates. They're reported as a count and as item coverage (counted items / all items).

## Useful-result event: `useful-v1` (**PROPOSED, not yet approved**)

An attempt is useful when the result is **complete**, all four totals are known, and:
- energy error ≤ max(50 kcal, 15% of the reference)
- each macro error ≤ max(3 g, 20% of the reference)

These are the plan's initial business thresholds. They must be approved and frozen before the locked test (plan §11, §15).

**Useful-result pass rate** = useful attempts / **all** attempts on scorable references. Failed, abstained and partial attempts count as non-passes. The scorable-output error above is a separate statistic.

## Other metrics

- **Status rates:** complete, partial, abstained and failed counts per configuration and category. Runs stopped by a batch cap are listed as *not run*, and the batch is marked incomplete.
- **Abstention:**
  - Correct abstentions on abstain-expected groups: an `abstained` status, or `failed` with `empty_recognition` (fatsecret 211).
  - Abstentions on real food are counted separately.
- **Items** (mapping `lexical-v1`, automatic and **unreviewed**): greedy one-to-one matching by name-token overlap (Jaccard ≥ 0.5). Reported:
  - item precision and recall
  - preparation accuracy among matched items that state a preparation (unstated ones are counted separately)
  - portion absolute error in grams

  Ambiguous mappings need human review before conclusions are drawn. An LLM is never the judge.
- **Latency:** p50/p95 of `server_total_ms` over all attempts, and over complete attempts. Linear interpolation (Hyndman-Fan type 7). Client click-to-render time isn't measured.
- **Repeatability:**
  - share of repeated photos whose repeats all have the same status
  - median per-photo sample SD of energy across complete repeats, and the median coefficient of variation
- **Cost:** known estimated cost, the number of attempts with unknown cost (fatsecret has no price table), and cost per attempt and per useful attempt. Both are shown as unavailable when any cost is unknown, never as $0.
- **Agreement:** A vs B on the same photo and repeat: the median absolute energy difference, and the share within the energy tolerance of each other. **Agreement is not accuracy**: both apps can agree and be wrong.
- **Paired difference:** useful pass rate of the first configuration minus the second, over groups scorable for both.
- **Intervals:** 95% percentile bootstrap, 2,000 resamples of whole groups, seed 13. None when fewer than 2 groups.

## Storage rights

Status counts, latency and cost are payload-free and always saved. Accuracy, item, repeatability, agreement and paired metrics are **derived metrics**:
- While fatsecret rights are pending, App A's derived metrics and the A/B comparison are printed during the run but **never written**.
- Saved reports show them as `UNAVAILABLE`, never as empty or zero.
- Saved App A run records keep only payload-free fields and the storable `food_id`/`serving_id`.
