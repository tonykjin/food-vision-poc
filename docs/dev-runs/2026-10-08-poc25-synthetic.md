# Prompt 25 proof-of-concept run on synthetic references (2026-10-08)

**Purpose: show that the frozen calibration and held-out flow runs end to end with live APIs.** It is **not** an accuracy result, a calibration or a go/no-go decision. At your direction (proof of concept, no real data):
- **Photos:** 8 meal photos from Wikimedia Commons (CC0, CC BY, CC BY-SA; attribution recorded per photo, rights `third_party_smoke_only`).
- **Reference grams:** invented from the photos.
- **Nutrient values:** real USDA FDC records from the local catalog.
- All groups are `is_synthetic`, so they never count toward the 30 real meals. Data is in git-ignored `data/benchmark-poc/`; outputs are in `work/eval-poc/`.

## What ran

| Step | Result |
|---|---|
| `foodvision freeze` (A_native, B_grounded) | spec `synthetic-poc-1`, sha `4426bbcacdcf` (git-ignored: synthetic specs are throwaway) |
| Calibration benchmark (4 groups × 2 configs × 3 repeats) | 24/24 scans returned; batch complete; passed the frozen-spec checks |
| Test benchmark, once, `--allow-test-split` | 24/24 scans returned; batch complete |
| `calibrate` B_grounded | saved: calibration split, every bucket "insufficient data" (most groups: 4 < 30) |
| `calibrate` A_native | computed and printed, **not saved** (fatsecret rights pending), as designed |
| `gates` on the test batch | saved copy marks the A-dependent gates and the overall verdict UNAVAILABLE (rights); the printed overall was INCONCLUSIVE (provisional) |

## Live behavior (payload-free facts and App B; App A accuracy numbers are display-only)

| | App A `A_native` | App B `B_grounded` |
|---|---|---|
| Statuses, calibration batch | 12 complete | 7 complete, 5 partial |
| Statuses, test batch | 12 complete | 5 complete, 7 partial |
| Failed / not run | 0 / 0 | 0 / 0 |
| p50 / p95 server time | 3.8-3.9 s / 5.7-6.3 s | 12.4-13.2 s / 15.0-20.5 s |
| Cost | unknown per call (24 + 24 requests against the 25k quota) | $0.443 + $0.498 = $0.94 |
| B confidence labels (calibration) | n/a | low 11, medium 1, high 0 |

## Gates as computed (provisional; on invented references, so not evidence)

- Typed result within deadline: A and B **GO** (100% of attempts).
- No hidden exclusions: **GO**.
- p95 ≤ 15 s: A **GO**; B **INCONCLUSIVE** (p95 20.5 s; interval 14.5-20.5 s).
- B − A useful rate, cost materiality, false-high review: depend on fatsecret-derived metrics or a human decision; not saved.

## What this shows and doesn't

- **Shows:** freeze → frozen calibration and test batches → calibrate → gates all work with live APIs. Rights filtering, the once-only test rule, group-based bucket counts and the 30-group threshold all behave as designed. Every request returned a typed result.
- **Doesn't show:** accuracy, calibration or a business decision. The references are invented, and 4 groups per split is far below the 30 groups per bucket the plan requires. No change is motivated by these results, so no new version is logged.
- **Worth noting for later:** B returned `partial` in about half the scans (some items unmatched or unresolved), and its p95 is above the 15 s target, consistent with the earlier smoke runs.
