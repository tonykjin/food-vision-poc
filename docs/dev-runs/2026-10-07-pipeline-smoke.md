# Development pipeline smoke batch (2026-10-07)

**This is not an accuracy result.** It checks that real photos produce real provider outputs end to end through the benchmark runner.
- The only photo is a user-approved third-party stock image (`third_party_smoke_only`).
- The reference is **invented** (`syn-smoke-chicken-plate`, `is_synthetic: true`), so every accuracy-type number against it is meaningless and none is reported here.
- No real meals have been collected (0/30), and this is not held-out data.

## Runs

| Batch | Configs | Scans | Commit | B configuration | Known cost |
|---|---|---:|---|---|---:|
| `20261007T213622Z-ba2b02` (baseline) | A_native, B_grounded | 6 | `0b2c0a9` | `...:max-items-5` | $0.184 (B); A unknown, within the fatsecret 25k quota |
| `20261007T213945Z-20fb14` (after fix) | B_grounded only (A config unchanged) | 3 | `92ed8f1` | `...:max-items-8` | $0.197 (B) |

Both runs used the development split, 1 photo, 3 repeats, caps of $10 and 200 scans, and the same B model, prompt and effort (`claude-opus-5-5`, `recognize-food-v2`, `choose-food-match-v1`, medium). The only configuration difference is the item cap (5 → 8). Total spend: $0.38 Anthropic plus 3 fatsecret image requests. Full transient output was shown in the terminal; saved files are in `work/eval-smoke/` (git-ignored, rights-filtered).

## Findings by problem type

| Area | App A (payload-free facts only; fatsecret rights pending) | App B |
|---|---|---|
| Recognition | 3/3 complete; identical outputs across repeats | 7 foods listed every time; consistent names (chicken breast, sauce, rice, broccoli, corn, red bell pepper, parsley) |
| Preparation | provider states none | stated for 7/7 items; chicken alternated between grilled and sautéed across repeats |
| Portions | provider-suggested | stable across repeats (chicken 160-170 g, rice 160 g, broccoli 70-75 g) |
| Retrieval | n/a (provider) | **Sauce:** the model rejected all candidates (`no_match`) 3/3. Candidates for "creamy butter sauce" included nut butters because of the word "butter"; one plausible record ("Sauce, white, thin, ... with butter") was offered. **Pepper and parsley:** good records exist; they were only lost to the item cap (fixed). |
| Nutrition arithmetic | provider totals | no errors; resolved items were calculated in code |
| Latency | p50 4.7 s, p95 5.0 s | p50 22.8-23.8 s, p95 24.8-26.2 s: **above the provisional 15 s p95** |
| Coverage | complete 3/3 | **partial 3/3 → 0 scorable whole-meal results.** Item coverage 60% before the fix, 86% after |
| Uncertainty | n/a | heuristic labels only; nothing calibrated |

## Fix backlog (evidence-ranked)

1. **Done:** raise the B item cap from 5 to 8 ([#37](https://github.com/tonykjin/food-vision-poc/pull/37)). It was a structural defect: plates with 6+ foods could never be complete. Effect: coverage 60% → 86%; cost +$0.004 per scan; latency unchanged within noise.
2. **Open, needs more examples:** sauce and condiment retrieval. Lexical matching on "butter" pulls nut butters. With one example, any change would be tuned to this plate. Revisit with real meals.
3. **Open, needs evidence:** B latency (about 23 s) vs the 15 s p95 target. Options (lower effort, a different model) change quality and need a measured comparison on real meals, so no change now.

## Not shown

App A accuracy-type numbers (transient only while fatsecret rights are pending), and any B accuracy (invented reference). Repeatability on one photo isn't a repeatability study.
