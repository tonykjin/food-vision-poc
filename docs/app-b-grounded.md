# App B: grounded matching (POC-10)

Pipeline `B_grounded` (the default `PIPELINE_MODE`): **recognize → retrieve → select → calculate**. It builds on the vision adapter ([`app-b-vision.md`](app-b-vision.md)) and the USDA catalog ([`catalog.md`](catalog.md)).

| Step | What happens | Model call? |
|---|---|---|
| Recognize | Claude returns validated food hypotheses (≤ 8) | **Call 1** |
| Retrieve | Per item (first 5), `search_foods` in `food_catalog` with the **preparation filter applied before ranking**. A visible brand searches the branded pool; if that finds nothing, generic records are searched and the item says so. If needed, the display name and up to 2 alternatives are tried | No |
| Select | A deterministic rule accepts a **clear winner**: a single candidate, or a top candidate that is strict, preparation-matched, commodity-category and head-noun-complete while the runner-up is structurally worse. **All ambiguous items go to one batched call**, which may answer only with an ID from that item's candidates or `no_match` | **Call 2**, only if anything is ambiguous |
| Calculate | `calculate_nutrition(food_id, grams = base estimate)` in code. Low/high grams stay labeled assumptions | No |

## Guarantees (tested)

**Model calls and budgets**
- At most 2 model calls per scan, enforced by the Measurement Kit budget along with total attempts, deadline and the optional cost cap.
- If recognition used up the budget (for example, a retry after a 529), the selection call is refused. Ambiguous items then fall back to the top-ranked candidate, and the item and result both say so.

**Selection**
- **IDs:** a selected ID must be one of that item's retrieved candidates.
- **Unknown IDs:** an invented ID, or one from a filtered-out preparation (e.g. cooked rice when raw was seen), leaves the item **unresolved**. It's never substituted.
- **Final check:** before returning, every grounded item is re-checked against the set of IDs retrieval returned.

**Nutrients**
- **Calculated in code**, never taken from model prose.
- **A per-100 ml record without a density** stays unresolved (`not calculated`).
- **A nutrient the record lacks** stays unknown. Totals exclude unresolved items and unknown nutrients (never zero) and are marked partial.
- **Item cap:** items beyond 5 per scan are listed, unresolved, with an "over the item limit" reason, not dropped.

**Isolation**
- **No tools:** the model gets no tools at all (structured output only): no shell, no web.
- **Data, not instructions:** candidate records go to the model as JSON data, and both prompts state that such text is data, never instructions.
- **Database login:** the pipeline reads the catalog through `DATABASE_URL`. On first use it checks the real role and **refuses** a superuser or any login that can reach `benchmark` (tested with a real `fv_evaluator` login).

## Setup

Grounded mode needs `DATABASE_URL` in `.env.agent.local` pointing at an **`fv_inference` login**, never the owner or evaluator. In `psql` against the local Compose database:

```sql
CREATE ROLE app_b_inference LOGIN IN ROLE fv_inference;
\password app_b_inference
```

Then add this line to `.env.agent.local` yourself:

```
DATABASE_URL=postgresql+psycopg://app_b_inference:<password>@127.0.0.1:5432/foodvision
```

Without it, App B reports not-ready with HTTP 503. Set `PIPELINE_MODE=recognition_only` to get hypotheses only. Pin catalog releases for frozen runs with `CATALOG_SOURCE_VERSIONS`.

## Live smoke results (2026-10-03 UTC, user-authorized)

The steak photo, real imported catalog. Each run used a temporary `fv_inference` login with a random password, dropped afterwards. Payload-free summaries only:

| Run | Items | Grounded | Unresolved reason | Calls | Latency (recognize + select) | Est. cost |
|---|---|---|---|---|---|---|
| 1 | 5 | 2 | not recorded (added after run 1) | 2 | 11.0 s + 7.9 s | $0.050 |
| 2 | 5 | 3 (1 deterministic, 2 by model) | 2 × model `no_match` | 2 | 10.9 s + 6.4 s | $0.048 |

**What these runs show:**
- The full loop works with the real API and catalog.
- Unresolved items came from the model declining all candidates, not from fabricated matches.
- **Output varies run to run** (2 vs 3 grounded). Repeatability needs measuring (plan §11).
- **Latency of about 17–19 s exceeds the provisional 15 s p95 target.**

**Not shown:** accuracy. Two runs on one photo aren't evidence of recognition or nutrient accuracy; that requires reference meals (POC-12/13).

## Smoke command

```powershell
uv run foodvision smoke-vision --image <owned photo> --confirm-one-request
```

- **Opt-in:** needs `ENABLE_LIVE_API_TESTS=true`.
- **Mode:** runs the configured pipeline. Grounded needs `DATABASE_URL`, and is capped at 2 model calls with no retries.
- **Output:** status, counts, which nutrients are known, reason categories, tokens, cost and latency. No food names or values.
