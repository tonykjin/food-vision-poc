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
- **Not live-verified:** `OPENAI_API_KEY` is **missing** from `.env.agent.local` (`doctor`, 2026-10-07). Real response shape, served model ID, usage fields, latency and quotas are unverified until the opt-in smoke runs: set `VISION_PROVIDER=openai` and `PIPELINE_MODE=recognition_only` or `direct`, then `foodvision smoke-vision --image <photo> --confirm-one-request`.

## DeepSeek: not built (recorded, not substituted)

The official vision guide (2026-10-07) documents image input for `deepseek-flash` through the OpenAI-compatible Chat Completions endpoint (base64 data URLs; JPEG/PNG/GIF/WebP). That page **does not document JSON-schema structured output**, and there is **no DeepSeek account or key**. So no adapter exists, and `VISION_PROVIDER=deepseek` is rejected rather than silently mapped to another model. To proceed: get a key, then verify structured-output support with images in the official API reference before building.
