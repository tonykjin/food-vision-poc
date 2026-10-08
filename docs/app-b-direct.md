# App B `B_direct`: model-estimated nutrition, no database grounding (POC-14)

A **diagnostic** pipeline inside App B (plan §9 B5): the vision model identifies the foods **and estimates their nutrients itself**, in one call. It exists to measure what database grounding (`B_grounded`) adds. It is not the recommended production path.

## How it differs from `B_grounded`

| | `B_grounded` | `B_direct` |
|---|---|---|
| Model calls | 1 recognition + at most 1 selection | 1 |
| Nutrient source | USDA records, calculated in code | the model's estimate (`food_source: model_estimate`, no `food_id`) |
| Prompt | `recognize-food-v2` + `choose-food-match-v1` | `estimate-nutrition-direct-v1` (the v2 recognition text plus nutrient estimates and their limits) |
| Labeling | — | the warning "Model-estimated; no database grounding" on every result; the UI source reads "model estimate (no database grounding)" |
| Confidence (nutrition match) | rules by match method | always **Low** (`confidence-rules-v2`) |

Shared with `B_grounded`: the model, effort, image bytes (baseline prep), item limit (8), text limits, deadline and per-scan budgets. Totals are summed in code. A `null` estimate stays unknown and makes the totals partial; it is never 0. Out-of-range estimates (> 5000 kcal or > 500 g per item) fail as `invalid_schema` with the field path.

## Running it

- **App B:** `PIPELINE_MODE=direct` (no database needed). `/health` reports `pipeline_id: B_direct`.
- **Benchmark:** `--configs B_grounded,B_direct` compares both on identical bytes in one batch; the runner sets each config's mode.
- **Smoke (opt-in, one call):** set `PIPELINE_MODE=direct`, then run `uv run foodvision smoke-vision --image <photo> --confirm-one-request`.

## Live check (2026-10-07, user-authorized smoke, stock smoke image)

`complete`; 6 items, all four nutrients estimated; 1 call (`claude-opus-5-5`, no fallback, `end_turn`); 14.5 s; tokens 2,714/1,446; about $0.040. This shows the integration works, not that the estimates are accurate.
