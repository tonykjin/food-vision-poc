# App A: fatsecret adapter (POC-08)

Pipeline `A_native`: image → shared baseline prep (512 px) → fatsecret image recognition v2 → shared result contract. **There is no LLM or model fallback in App A** (`max_model_calls` is fixed at 0).

Docs checked 2026-10-02:
- [Image recognition v2](https://platform.fatsecret.com/docs/v2/image.recognition)
- [OAuth 2.0](https://platform.fatsecret.com/docs/guides/authentication/oauth2)
- [Error codes](https://platform.fatsecret.com/docs/guides/error-codes)
- [Attribution](https://platform.fatsecret.com/attribution)

## Behavior

**Token**
- Client-credentials request, scope `image-recognition`, HTTP Basic auth.
- The token is kept in memory and reused until 5 minutes before `expires_in` (86400 s). On error code 13 (invalid token), it is refreshed once.
- Credentials are `SecretStr`, read from `.env.provider.local` only, and never logged.

**Request**
- JSON `{image_b64, include_food_data: true}`: no `eaten_foods` hints in the baseline, and no `region`/`language` (Premier-only; the US default applies).
- The full serialized body is size-checked before any send (`fatsecret_limits.py`).

**Normalization**
- **`eaten.total_nutritional_content` is the total for the detected portion and is used as-is.** It is never scaled again.
- Only when those totals are missing is the suggested per-serving record scaled, once: amount × suggested units / serving units.
- Numbers arrive as strings. Blank, non-numeric, negative or non-finite values become unknown, with a reason.
- An ml portion has no gram weight, so that item stays unresolved and is excluded from totals.
- Status is `complete` only when every item is resolved and every nutrient is known; otherwise `partial`.

**Errors (typed)**

| Condition | Result |
|---|---|
| No foods | `failed` / `empty_recognition` |
| 211 "No food item detected" (also returned for nutrition-label-only images) | `failed` / `empty_recognition` |
| 13, 14, 21 (token, scope, IP) and 401/403 | `authentication` |
| 11 (request limit) | `quota`, not retried |
| 12 (too many actions) | retried once |
| 20, 24, 5xx, transport errors, timeouts | retried once |
| Non-JSON response | `invalid_schema` |
| Missing credentials | HTTP 503 `authentication` |

**Telemetry:** every token and image attempt is recorded by the Measurement Kit. Provider message text is dropped and only numeric codes are kept. Cost is **unknown**, because fatsecret prices per market by quote.

**Rights (pending, see `provider-readiness.md`)**
- Results are returned to the caller for transient display only.
- Each result carries a "not stored" notice.
- The telemetry ScanRecord is payload-free (tested).
- `filter_result` keeps only `food_id`/`serving_id` plus metadata for any persist or export.
- Ordinary tests use **synthetic** protocol fixtures (`tests/fixtures/fatsecret/`). No live response is ever stored as a fixture.

**Attribution:** App A's UI shows the unmodified snippet `<a href="https://platform.fatsecret.com">Powered by fatsecret Platform API</a>` whenever `A_native` is active.

## Verification status

| Behavior | Status |
|---|---|
| Token request shape, reuse, refresh margin, code-13 refresh | **Adapter-verified** (fake HTTP) |
| Image request shape, size guard, no hints | **Adapter-verified** |
| Eaten totals vs per-serving (no double scaling), missing/invalid values, ml portions | **Adapter-verified** on synthetic fixtures |
| Error codes 11/12/13/14/20/21/22/211, HTTP 429/5xx, transport, timeout, non-JSON | **Adapter-verified** |
| Payload-free telemetry; policy filter; no provider text in errors | **Adapter-verified** |
| App A starts live with only fatsecret credentials, no model key, no B code | **Verified** locally 2026-10-02 (`/health` only, no request made) |
| Real token issuance for our client ID, from this machine's IP | **Live-verified 2026-10-07** (after `invalid_scope` on 2026-10-03/06, then image-request code 21 until the IP was registered) |
| `image-recognition` scope and add-on enabled on our account | **Live-verified 2026-10-07** (add-on enabled by you; scope granted) |
| Real response field presence and value types | **Live-verified on one image** (2026-10-07): 7 items, all with `food_id`, `serving_id`, gram portions and all four nutrients; normalized to a schema-valid `complete` result. Other images may differ. |
| Whether label-only images return 211 in practice | **Live-unverified** |
| Latency, quotas, real HTTP status for errors | **One sample:** image request 5.5 s, token 232 ms (2026-10-07). Code 21 arrived as HTTP 200 with an error body, as the adapter expects. Quotas unverified. |

## Live smoke test (opt-in, authorized as needed)

**Passed 2026-10-07 20:29 UTC** with a third-party stock image (smoke only, not owned): `complete`, 7/7 items resolved, totals complete, 1 token + 1 image request, 5.8 s total. Nothing stored; rights are still pending, so no fatsecret result or derived metric may be persisted.

Opt in once by adding `ENABLE_LIVE_API_TESTS=true` to `.env.provider.local`, or set it in the shell. The user authorized live checks "as needed" on 2026-10-02. `foodvision doctor --app provider` shows `live API tests enabled`.

```powershell
uv run foodvision smoke-fatsecret --image <path to an owned food photo> --confirm-one-request
```

- **Budget:** at most 1 token request + 1 image request, no retries. Any fatsecret charges for those requests depend on your plan.
- **Output:** a payload-free summary only: status, codes, counts, which fields were present, and timings. No food names or nutrient values.
- **Storage:** nothing is written.
- **Prerequisites:** your IP is registered with fatsecret and the image add-on is enabled (`provider-readiness.md`).
