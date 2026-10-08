# App B OpenAI adapter, and DeepSeek status (POC-14)

`providers/openai_vision.py` lets every App B pipeline (`B_grounded`, `B_direct`, recognition-only) run on OpenAI with **the same prompts, schemas, image bytes, item and text limits, deadline, budgets and server-side validation** as Claude. Only the model call changes. Select it with `VISION_PROVIDER=openai`; the key is `OPENAI_API_KEY` in `.env.agent.local`.

## Facts from the official docs (checked 2026-10-07, developers.openai.com)

| Topic | What the docs say | What the adapter does |
|---|---|---|
| Endpoint | Responses API | `client.responses.create`, SDK `openai` 3.26.0, SDK retries off |
| Image input | `input_image` with a base64 data URL; `detail` low/high/original/auto; JPEG/PNG/WebP | baseline JPEG, `detail: "original"` (no provider resizing) |
| Structured output | `text.format` = `json_schema`, `strict: true`. Strict mode: no `anyOf`; nullable via type arrays | the shared schema converted (`strict_schema`); our own validation still runs |
| Refusal / truncation | a `refusal` content item; `status: incomplete` with `max_output_tokens` | typed `refused` / `invalid_schema`, billed, not retried |
| Reasoning | `reasoning.effort` (Astra: low…max, default medium); output tokens include reasoning | `medium`, same as the Claude config |
| Model | `gpt-6-astra` flagship, recommended for new projects; **an alias, not a snapshot** | default, configurable with `VISION_MODEL` |
| Price | Astra $10 / $50 per M tokens (Sol $2 / $10, Luna $0.10 / $0.50) | price table `openai-pricing-2026-10-07`; dated snapshots priced as their base model |
| Fallback | none | `nofallback` in the configuration ID; a refusal is final |
| Errors | 429 can mean a rate limit or `insufficient_quota` | the rate limit is retried once; insufficient quota is a typed `quota` failure, never retried |

The configuration ID names the provider, model, effort, prompt hash and image detail (for example `B:openai:gpt-6-astra:effort-medium:recognize-food-v2@…:detail-original:nofallback`). In the benchmark, `--configs B_grounded,B_grounded@openai` compares providers on identical bytes, and each config is labeled separately (`@openai:gpt-6.1-sol` picks a model).

**Cost expectation:** Astra is 2.5× Opus 5.5 per token, so roughly $0.10-0.15 per recognition call before reasoning tokens. Check this before any batch.

## Verified vs not

- **Contract-tested** (fake SDK client, 18 tests): request shape, strict schema, provenance, cost, refusal, truncation, invalid JSON, field-level validation, every error mapping, registry selection, `B_direct` on OpenAI.
- **Live attempts (2026-10-08, opt-in smoke, 1 call each, no output, no cost):** the key is present and authenticates, but both calls returned HTTP 429 with **code `credit_balance_exhausted`, type `insufficient_quota`**: the OpenAI account has no credit. This exposed a classification bug: billing arrives in `type` with a new `code`, so it had been treated as a retryable rate limit. Now it's a non-retried `quota` failure, and rate-limit details record the code, type and retry-after (identifiers only).
- **Live-verified 2026-10-08 after you added credit** (opt-in smokes, stock smoke image, 1 call each):

  | Mode | Status | Items | Served model | stop | Time | Tokens in/out | Cost |
  |---|---|---|---|---|---|---|---|
  | recognition-only | partial (as designed: no nutrients) | 7 | `gpt-6-astra` | completed | 28.4 s | 1,156 / 1,366 | $0.080 |
  | `B_direct` | complete, 7/7 nutrients | 7 | `gpt-6-astra` | completed | 32.3 s | 1,326 / 1,725 | $0.0995 |

  The served model ID equals the alias (no snapshot suffix seen), so pricing matched. Strict-schema output passed our own validation both times.
  **Same photo, Claude (`claude-opus-5-5`, 2026-10-07):** `B_direct` 6 items, 14.5 s, $0.040. OpenAI took about 2× longer and cost 2.5× more per call here. One photo isn't a comparison of quality or accuracy.
- Earlier (2026-10-07): `OPENAI_API_KEY` was missing from `.env.agent.local`. Real response shape, served model ID, usage fields, latency and quotas are unverified until the opt-in smoke runs: set `VISION_PROVIDER=openai` and `PIPELINE_MODE=recognition_only` or `direct`, then `foodvision smoke-vision --image <photo> --confirm-one-request`.

## DeepSeek: not built (recorded, not substituted)

The official vision guide (2026-10-07) documents image input for `deepseek-flash` through the OpenAI-compatible Chat Completions endpoint (base64 data URLs; JPEG/PNG/GIF/WebP). That page **does not document JSON-schema structured output**, and there is **no DeepSeek account or key**. So no adapter exists, and `VISION_PROVIDER=deepseek` is rejected rather than silently mapped to another model. To proceed: get a key, then verify structured-output support with images in the official API reference before building.
