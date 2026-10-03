# App B: Claude vision recognition (POC-09)

Pipeline `B_recognition_only`: image → shared baseline prep (512 px) → one Claude vision call → validated food hypotheses → shared result contract. **Matching to USDA and nutrient calculation are not in this step (POC-10, #10).** Every item is unresolved, nutrients stay unknown, and the result is labeled partial.

Docs checked 2026-10-02:
- [Vision](https://platform.claude.com/docs/en/build-with-claude/vision)
- [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- [Models overview and pricing](https://platform.claude.com/docs/en/about-claude/models/overview)

## Request

| Setting | Value | Configure with |
|---|---|---|
| SDK | official `anthropic` Python SDK 1.11.0, SDK retries off (the Measurement Kit counts attempts) | `uv.lock` |
| Model | `claude-opus-5-5` (default; configurable) | `VISION_MODEL` |
| Thinking | adaptive (always on for this model); no thinking budget, no sampling parameters | n/a |
| Effort | `medium` (set explicitly) | `VISION_EFFORT` |
| `max_tokens` | 16000 | `VISION_MAX_TOKENS` |
| Output | `output_config.format` JSON schema (`recognition/hypotheses.py`) | n/a |
| Prompt | `prompts/recognize-food-v1.md`, SHA-256 over LF-normalized text | `PROMPT_VERSION` in code |
| Refusal fallback | server-side `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`) | `VISION_REFUSAL_FALLBACK` |
| Image | base64 JPEG, placed before the text | n/a |

**Refusal fallback and benchmarks:** with fallback on, a refused request can be answered by a different model. That answer is recorded (`model_provenance.model_served`, `fallback_served`) and flagged in the result warnings. For frozen benchmark runs, consider `VISION_REFUSAL_FALLBACK=false` so every answer comes from the configured model.

## Hypotheses

Each food the model reports includes:
- name and a search description
- preparation, from a fixed list, or `unknown`
- visible brand, only when readable
- **low/base/high grams**, labeled as an assumption range rather than a confidence interval
- the portion cues used
- up to 3 alternatives
- a short visible-evidence phrase and uncertainty reasons
- whether it's a composite dish

**No confidence percentage is requested or accepted**, and no reasoning is requested. Text inside the image is treated as data, not instructions.

**Server-side validation:** structured output only guarantees the JSON shape, so these are checked on our side:
- grams > 0, at most 3000, and low ≤ base ≤ high
- known preparation values only
- no extra fields
- at most 8 items and 3 alternatives
- no items when the model says the image shows no food

## Failures (typed, never fabricated)

| Condition | Result |
|---|---|
| `stop_reason: refusal` | `refused` (billed tokens still costed) |
| `stop_reason: max_tokens` (truncated) | `invalid_schema` |
| Non-JSON output, or JSON that fails validation | `invalid_schema` |
| Timeout, connection error | retried once |
| 429 | retried once, honoring `retry-after` |
| 5xx / 529 | retried once |
| 401/403 | `authentication`, not retried |
| `billing_error` | `quota`, not retried |
| Other 4xx (bad request, unknown model) | `provider_error`, not retried |
| No food recognized | result `abstained` |
| Missing `ANTHROPIC_API_KEY` | HTTP 503 `authentication` |

Unsupported images are rejected earlier, by the shared image prep.

**Recorded per scan:**
- `model_provenance`: provider, requested and served model, fallback flag, prompt version and hash, SDK version, effort, stop reason, request ID
- the Measurement Kit attempt: tokens, and cost from the price table above (version `claude-models-overview-2026-10-02`)

## Verification status

| Behavior | Status |
|---|---|
| Request shape, error mapping, stop reasons, validation, budgets, cost provenance | **Adapter-verified** with a fake SDK client and real SDK exception classes |
| App B starts live with only the Anthropic key, no fatsecret credentials, no App A code | **Verified** locally 2026-10-03 (`/health` only) |
| Live call: key, model, image input, structured output, fallback beta together | **Live-verified once** (2026-10-03 UTC, 1 call): `end_turn`, served by `claude-opus-5-5`, no fallback, 5 items passed validation, 12.9 s, 1,871/1,038 tokens, ≈ $0.028 |
| Recognition quality (correct identity, preparation, grams) | **Not measured.** It needs reference meals (POC-12/13); one smoke call isn't evidence of accuracy |
| Refusal, fallback and truncation on the real API | **Live-unverified** (not triggered) |

## Live smoke test (opt-in, authorized as needed)

```powershell
uv run foodvision smoke-vision --image <path to an owned food photo> --confirm-one-request
```

- **Opt-in:** needs `ENABLE_LIVE_API_TESTS=true` in `.env.agent.local` or the shell.
- **Budget:** exactly one model request, no retries.
- **Output:** a payload-free summary only (status, model, counts, tokens, cost, latency). No food names or portion values are printed, and nothing is stored.
