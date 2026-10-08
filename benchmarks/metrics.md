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

## Frozen evaluation, calibration and decision gates (POC-15)

**Procedure** (calibration and test splits refuse to run otherwise):
1. Commit everything, then `foodvision freeze --manifest <groups> --configs A_native,B_grounded --name <name>`. This writes `benchmarks/frozen/<name>.json`: commit, configuration IDs (model, effort, prompt hashes, item cap), confidence-rules / metrics / useful-result versions and tolerance, preprocessing version and manifest hash. It holds no labels, and it's hashed: an edited spec is rejected. Commit it.
2. `foodvision benchmark --split calibration --frozen <spec> ...` runs only if the code, configs, rules, tolerance and manifest all match the spec. Only `benchmarks/frozen/` and `docs/` may change after the freeze.
3. `foodvision calibrate --batch <calibration batch> --config B_grounded --version <name> --output <dir> [--save-db]` fits on the **calibration split only** (the DB table also rejects `test`). Per heuristic label (low/medium/high/not assessed) it reports attempts, **groups** and useful attempts:
   - The pass rate and a group-bootstrap 95% interval are shown **only with ≥ 30 groups** in the bucket; otherwise "insufficient data", and the label stays uncalibrated.
   - High-confidence attempts that weren't useful are listed for human review.
4. `foodvision benchmark --split test --frozen <spec> --allow-test-split ...` runs **once** per spec (a second test batch for the same spec is refused). If the held-out results motivate a change, freeze a **new** spec and collect new confirmatory data; never tune on the test set.
5. `foodvision gates --batch <test batch> --output <dir>` gives evidence for each plan §15 gate (`gates-v1`, **provisional**: the thresholds aren't approved yet).

**Gate verdicts** use the whole group-level 95% interval: GO if it meets the threshold, NO-GO if it misses it entirely, INCONCLUSIVE otherwise (including too few groups for an interval). The overall verdict is NO-GO if any automated gate is NO-GO, INCONCLUSIVE if any is inconclusive, else GO (provisional).

| Gate (plan §15) | Measure | Threshold |
|---|---|---|
| Typed result within deadline | attempts with complete/partial/abstained (or `empty_recognition`) within the per-scan deadline | ≥ 95% |
| No hidden exclusions | batch complete, nothing not run | yes |
| p95 server time | 95th percentile of `server_total_ms` per config | ≤ 15 s |
| B vs A useful rate | paired difference B − A over groups scorable for both | B no more than 5 points below A |
| Cost materiality | known cost per useful attempt per config | human decision |
| False-high confidence | review list from calibration | human review |

While fatsecret rights are pending, App A's calibration and the A-dependent gates (B vs A, A's cost per useful attempt, the overall verdict) are printed but saved as unavailable.
