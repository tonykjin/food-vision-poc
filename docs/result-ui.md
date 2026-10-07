# Shared result UI and heuristic confidence (POC-11)

Issue [#11](https://github.com/tonykjin/food-vision-poc/issues/11). Plan §11 "Confidence presentation".

## What both apps show

`apps/provider_ui.py` and `apps/agent_ui.py` both render `src/foodvision/ui/result_view.py`, so App A and App B show the same fields and states.

| Section | Content |
|---|---|
| State banner | `complete`, `partial`, `abstained` or `failed`. HTTP errors (400/413/503, unreachable API, schema-invalid body) render as failed. |
| Totals | "Estimated totals (complete)", "PARTIAL (n counted, m excluded)" or "Totals unavailable". Unknown nutrients read **unknown**, never 0. |
| Confidence | Overall plus identity, portion and nutrition match as Low/Medium/High with reasons, labeled **heuristic, uncalibrated**. No percentage. |
| Reference | Always "Reference unavailable" for a live scan; no accuracy is shown. |
| Food components | Per item: preparation, portion grams and method, low/base/high assumption range, source and record ID, match method, nutrients, alternatives, evidence, uncertainty reasons. |
| Timing and cost | `server_total_ms` (backend), the UI-to-API wait (Python timer, labeled not click-to-render), `client_total_ms` **unavailable**, external attempts, estimated cost (unknown stays unknown). |
| Provenance | Scan, pipeline, configuration, confidence rules version, input prep version and hash, model served. |
| User corrections | A form beside the result (not shown for MOCK or results with no items). |

## Confidence rules (`confidence-rules-v2`)

`measurement/confidence.py` is applied by the shared API factory to every result, so both apps use identical rules. It reads only structural result fields. It never uses model self-ratings, provider scores, A/B agreement or reference labels, and never produces a probability.

| Dimension | Low | Medium | High |
|---|---|---|---|
| Identity | none | alternatives listed, preparation unknown, or 4+ items in the image | otherwise |
| Portion | weight unknown, or high/low assumption ratio ≥ 2 | estimated from the image or suggested by the provider | measured weight only (diagnostic mode) |
| Nutrition match | unresolved item, missing nutrient, fallback top candidate, or **model-estimated nutrients (B_direct, no database record; added in v2)** | provider match (App A) or model choice among ambiguous candidates | deterministic clear winner among retrieved USDA candidates |

The overall label is the lowest of the three; each dimension takes the worst item. Image-only portions are never High, so no image-only scan can be High overall. MOCK, failed and abstained results are "not assessed".

To support these rules, `ResultItem.match_method` (`provider`, `deterministic_ranking`, `model_selection`, `fallback_top_candidate`) and `Confidence.rules_version` were added. Both are optional, so schema 1.0 is unchanged for existing consumers. A non-assessed confidence can't carry levels.

These labels are not measured accuracy. POC-15 (#15) measures pass rates per bucket on separate calibration data; until then nothing is calibrated.

## Automatic result vs corrections

The automatic result is stored in session state once per Analyze press and is never edited. Corrections (name, grams, note) are stored separately per scan ID and listed beside it. Nothing is recalculated from them, and they live only in that browser session: they aren't persisted, so no fatsecret-derived content is stored.

## Not done

- **Browser click-to-render timing** isn't measured; `client_total_ms` stays unavailable (needs a browser-side component).
- **Abstained and live partial screens** were checked headlessly only (synthetic results); a live App B partial result hasn't been viewed in the browser yet.
- Correction persistence (the `corrections` table) is out of scope.

## Browser verification (2026-10-07, Chrome, stock smoke image)

Each app was run with the other one stopped.

| State | App A (live fatsecret) | App B (live grounded) |
|---|---|---|
| Idle / upload | correct (attribution shown, no MOCK banner) | correct |
| Loading | "Analyzing..." spinner | not captured |
| Success | **complete** result: totals complete, Medium confidence on all three, "Reference unavailable", 5.9-7.9 s backend | not reached: the run failed (below) |
| Failure | bad file → Failed, `invalid_image`, HTTP 400, no provider call | live `invalid_schema` → Failed banner, "not assessed", cost shown. Fixed separately (prompt v2) |
| API down | "API not reachable" | not repeated |
| Photo changed | old result hidden: "The photo changed..." (after the fix) | same code |

Fixed after these checks: a stale result stayed next to a newly uploaded photo, and identical confidence reasons repeated per item (now one line listing the items). fatsecret values were only displayed, never recorded.
