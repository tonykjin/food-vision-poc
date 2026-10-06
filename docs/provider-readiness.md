# Provider Readiness

Account, access and rights status for each external provider. **This file never contains secret values.** `PENDING` means unknown or unconfirmed. Nothing here is approved just because it's documented. A permission counts only once it's confirmed in writing for our account (see `docs/project-settings.md` and Prompt 08).

**Last updated:** 2026-10-02 (Prompt 07)
**Docs accessed:** 2026-10-02. All sources are official vendor pages, listed in [Sources](#sources). Vendor docs change; re-check them before integrating.

## Summary

| Field | fatsecret (App A) | USDA FoodData Central (A lookup mode, B) | First runtime model (App B) | Hosted storage (optional) |
|---|---|---|---|---|
| Owner | Tony Jin (`tonykjin`) | Tony Jin | Tony Jin | Tony Jin |
| Access status | Credentials present. **Live token request with scope `image-recognition` was rejected: HTTP 400 `invalid_scope`** (smoke run 2026-10-03 UTC, 1 token request, no image sent). **Unchanged on 2026-10-06 22:10 UTC** (Prompt 19: 1 token request, 291 ms, HTTP 400 `invalid_scope`, no image sent, no retry). Most likely the image add-on/scope isn't enabled for this key; the client credentials themselves were probably accepted (no `invalid_client`). IP registration is still unconfirmed. Image recognition is a paid add-on. | Key present (2026-10-02). The branded catalog import used it successfully (1 request, 2026-10-06). Downloaded datasets need no key. | Key present. **Live vision smoke call succeeded 2026-10-03 UTC**: `claude-opus-5-5`, image input, structured output and fallback beta accepted; 1 call, 12.9 s, ≈ $0.028. **Prompt 19 grounded smoke passed 2026-10-06** (2 calls, ≈ $0.060; see `app-b-grounded.md`). Billing is prepaid credits with auto-reload (user-reported). The default workspace is used; the user chose not to partition. Claude hasn't verified presence (its sandbox blocks the file) or any live call. | Not needed yet (hosted pilot only) |
| Allowed region | PENDING. Basic and Premier Free cover **US data only**. Premier covers 62+ countries. `region`/`language` params are Premier-only. | US data (FDC is a US dataset) | PENDING. Check the [supported regions](https://platform.claude.com/docs/en/api/supported-regions) list for the pilot location. | PENDING (chosen at the hosted-pilot stage) |
| Capability to verify | Image add-on enabled on our key; `image-recognition` OAuth scope granted; token request from our IP; one owned image returns `food_response` with `eaten` and `suggested_serving`; error 211 on a label-only image | Search and detail endpoints return FDC IDs, nutrient units and portions for pilot foods; key works within the rate limit | Chosen model accepts a base64 image and returns `output_config.format` JSON schema output; refusal and `max_tokens` paths behave as documented | Private bucket, RLS policies, separate inference and evaluator credentials |
| Credential variable names | `FATSECRET_CLIENT_ID`, `FATSECRET_CLIENT_SECRET` (in `.env.provider.local`) | `USDA_API_KEY` (in each app's own local file) | `ANTHROPIC_API_KEY` (in `.env.agent.local` only); `VISION_PROVIDER=anthropic`, `VISION_MODEL` (nonsecret) | PENDING (names chosen in Prompt 27) |
| Budget status | PENDING. Pricing is per market, by quote. Premier Free gets 50% off for startups and nonprofits. | Free; rate-limited | No dollar cap (user decision 2026-10-02). Spend is limited by the Console credit balance and the per-scan call limits. Paid calls still need the explicit opt-in (Prompt 19). | PENDING |
| Persistence rights | **Restricted.** Only `food_id` and `serving_id` are storable. Everything else must be removed within 24 hours (Terms §1.5). Derived metrics, exports and training use are PENDING written confirmation. `PERSIST_PROVIDER_OUTPUTS=false`. | Public domain / CC0. Cite FDC. | Inputs and outputs are ours to store under our own policy. Anthropic states it doesn't train on API-uploaded images (vision FAQ). | Our data; follow the image-retention policy |
| Next action | **User contacted fatsecret about a plan upgrade (2026-10-03).** Once the image add-on is enabled, re-run `foodvision smoke-fatsecret`. Still send the [vendor questions](vendor-questions-fatsecret.md) on storage rights. | Sign up for a key; pick a dataset release for POC-07 | Create a dedicated runtime workspace with a spend limit; choose a model (Prompt 19) | None until the hosted pilot |

## fatsecret

Facts from the docs (2026-10-02):

- **Endpoint:** `POST https://platform.fatsecret.com/rest/image-recognition/v2`. OAuth scope `image-recognition`.
- **Request:** `image_b64` is required and limited to **999,982 characters**. Accepted formats are jpg, png and webp up to 1.09 MB. Recommended size is 256×256 or 512×512. Optional: `include_food_data`, `eaten_foods`, and `region`/`language` (Premier-only; region defaults to `US`).
- **Response:** a `food_response[]` array with `food_id`, `food_entry_name`, `eaten` (portion and nutrients), `suggested_serving` (`serving_id`), and `food` when `include_food_data=true`.
- **Error 211:** images that show only a nutrition-facts panel are rejected by design.
- **OAuth 2.0:** `client_credentials` only, token from `https://oauth.fatsecret.com/connect/token` using HTTP Basic auth. `expires_in` is 86400 s, so reuse the token until it's close to expiry. **Tokens can only be requested from IP addresses you register when managing your keys** (CIDR ranges on Premier). Dev machines, CI and hosting all need their egress IPs registered.
- **Editions:** Basic is free and limited. Premier Free is for startups and nonprofits. Premier is the paid tier. Image recognition is an "Optional Add-On" priced by number of markets, not by call volume. **Attribution is required** on Basic and Premier Free and not on Premier.
- **Terms (https://platform.fatsecret.com/terms):**
  - §1.3: attribute fatsecret wherever its content is shown.
  - §1.5: "must immediately remove or replace any Content not explicitly identified as storable indefinitely within 24 hours after obtaining it."
  - §1.7(i): no copying, transferring or sublicensing without written consent.
  - No clause found on benchmarking, derived metrics or ML training.

**Conflict to resolve:** the editions page lists the image add-on as available across all tiers, but the image-recognition page flags it as an add-on alongside Premier-only parameters. Whether the add-on is available on Premier Free for US-only use is PENDING (vendor question 1).

**Impact on the plan:** §1.5 is stricter than the plan's "keep restricted results in memory" assumption. Even transient evaluation artifacts held longer than 24 hours, such as a benchmark batch rerun the next day or cached report inputs, may break the terms unless fatsecret confirms otherwise. Until then, App A results and metrics derived from them stay in memory for the length of a run only. Durable A metrics are reported as unavailable (plan §14).

## USDA FoodData Central

- **API:** `https://api.nal.usda.gov/fdc/v1/` with `/food/{fdcId}`, `/foods`, `/foods/list` and `/foods/search`. The key goes in the `api_key` query parameter. Our client must keep that query string out of logs and error messages.
- **Rate limit:** 1,000 requests per hour per IP by default (`DEMO_KEY` allows 30/hour and 50/day). Going over returns HTTP 429.
- **License:** public domain / CC0 1.0. Suggested citation: "U.S. Department of Agriculture, Agricultural Research Service. FoodData Central, 2019. fdc.nal.usda.gov."
- **Downloads (no key needed):** Foundation Foods (latest April 2026), SR Legacy (final release April 2018), FNDDS (October 2024, covering 2021–2023), Branded (April 2026; the CSV is 427 MB zipped and 2.9 GB unzipped). Available as CSV and JSON. **POC-07 can start from a download before any key exists.**
- Keys found exposed online are deactivated.

## First runtime model: Anthropic (plan §9 baseline)

- **Access:** a Claude Console account at https://platform.claude.com with an API key created in Settings → API keys. Requests use the `x-api-key` or `Authorization: Bearer` header plus `anthropic-version`.
- **Vision:** images go in `image` content blocks (base64, URL or Files API `file_id`) as JPEG, PNG, GIF or WebP. Limits are 10 MB per image (base64, direct API), 8000×8000 px, and a 32 MB request. Cost is about `ceil(w/28) × ceil(h/28)` visual tokens, so a 512×512 baseline image is 19 × 19 = 361 tokens. Images go before the text in a prompt.
- **Documented vision limits that matter to us:** counting is approximate, and images under 200 px or low-quality images may be misread. Plan for these in portion estimation.
- **Structured output:** `output_config.format` with `{"type":"json_schema", ...}`, which is GA and needs no beta header. Strict tool use is `strict: true`. The schema can't use `minimum`/`maximum`/`minLength`, so **our Pydantic validation must enforce non-negative grams and other ranges.**
  - A refusal comes back as `stop_reason: "refusal"` with HTTP 200 and may not match the schema.
  - `stop_reason: "max_tokens"` may produce truncated, non-matching output.
  - Both paths need typed failures (plan §7).
- **Models (2026-10-02):** `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-4-5-20251001` and `claude-fable-5-1` all support vision. Current model IDs are pinned snapshots. Haiku 4.5 retirement is "not sooner than October 15, 2026", so don't use it as a frozen benchmark baseline. **`VISION_MODEL` is PENDING** and chosen in Prompt 19 after a real smoke test. Pricing: check https://platform.claude.com/docs/en/about-claude/pricing on the day the budget is set. Don't reuse numbers from this file.
- **Spend control:** the usage tier sets a monthly spend limit (Console → Billing) plus RPM/TPM rate limits (Console → Limits). Workspaces separate spend by use case.

### Claude Code login vs runtime API billing

These are **separate** and are tracked separately (plan §16):

| | Claude Code (development tool) | App B runtime (vision calls) |
|---|---|---|
| What it is | The CLI you're using now | `foodvision` App B calling the Messages API |
| Login | `claude` / `/login`, through a claude.ai plan or a Console account | None: an API key in `.env.agent.local` |
| Billed to | Whatever you signed into Claude Code with | The Console organization/workspace that owns `ANTHROPIC_API_KEY` |
| Spend control | Your Claude plan or Claude Code's Console settings | A **dedicated runtime workspace** with its own spend limit |

**Watch out:** Claude Code itself uses an `ANTHROPIC_API_KEY` environment variable if one is set in the shell that launches `claude`. That would bill development usage to the runtime key. **Never set it as a Windows user or system environment variable or in your PowerShell profile.** Keep it only in `.env.agent.local`, which the app loads itself.

## Hosted storage (optional, Supabase)

Not needed until the hosted pilot (POC-16). Its docs were **not re-fetched today**; the plan's §5 citation (https://supabase.com/docs/guides/storage/security/access-control) stands until then. Requirements carried forward: a private bucket, explicit RLS, no service-role key in any browser or UI, and separate inference and evaluator credentials.

## Human setup steps (links)

Do these yourself in a browser. **Never paste a key, secret or token into this chat**, or into issues, commits or logs. Claude only ever checks whether a value is set.

1. **fatsecret**
   - Register or sign in at https://platform.fatsecret.com (sign-in is at https://fatsecret.com/login, which the guides link to).
   - Generate client credentials and register your IP address in the key-management page of your account. The guides don't publish a direct URL for it.
   - Ask about the image add-on, Premier Free eligibility and the rights questions at https://platform.fatsecret.com/contact, using [the draft](vendor-questions-fatsecret.md).
   - Compare editions at https://platform.fatsecret.com/api-editions.
2. **USDA:** sign up at https://fdc.nal.usda.gov/api-key-signup/. The key arrives by email from api.data.gov.
3. **Anthropic runtime:**
   - Use the Console at https://platform.claude.com.
   - Create a workspace such as `food-vision-runtime` at https://platform.claude.com/settings/workspaces.
   - Set a spend limit for that workspace. Check the org caps at https://platform.claude.com/settings/billing and https://platform.claude.com/settings/limits.
   - Create a key **in that workspace** at https://platform.claude.com/settings/keys.
4. **Write the ignored local files.** Run this from the project root in PowerShell. It creates files with variable names only:

   ```powershell
   cd "C:\Users\tonyj\OneDrive\Desktop\food-vision-poc"
   Set-Content -Path .env.provider.local -Encoding ascii -Value 'FATSECRET_CLIENT_ID=','FATSECRET_CLIENT_SECRET=','USDA_API_KEY='
   Set-Content -Path .env.agent.local -Encoding ascii -Value 'ANTHROPIC_API_KEY=','USDA_API_KEY='
   git check-ignore -v .env.provider.local .env.agent.local
   notepad .env.provider.local
   notepad .env.agent.local
   ```

   Use `-Encoding ascii`, not `utf8`. In Windows PowerShell 5.1, `utf8` writes a BOM that can corrupt the first variable name. In Notepad, type each value right after `=`, with no quotes or spaces.

   To check presence without showing any values (it prints `set` or `missing` only):

   ```powershell
   foreach ($f in '.env.provider.local','.env.agent.local') { "== $f"; Get-Content $f | ForEach-Object { $n,$v = $_ -split '=',2; if ($n) { "{0,-26} {1}" -f $n, $(if ($v) {'set'} else {'missing'}) } } }
   ```

   - Fill in the values in Notepad and save. The `git check-ignore` line must print a match for both files.
   - App A's file gets no model key and App B's file gets no fatsecret key (plan §5).
   - Neither file ever gets `EVALUATOR_DATABASE_URL`.
   - Claude's permission rules block it from reading or editing these files, so this step is yours.
5. **OneDrive:** this repo lives under `OneDrive\Desktop`, so the local secret files sync to Microsoft's cloud and linked devices. **The user accepted this risk on 2026-10-02.** Rotate the keys if the OneDrive account is ever compromised or shared.

## Permission decisions log

Record only **written** decisions, with source, date and scope. Having a paid account, a working key or a successful authentication is **not** a permission.

| Provider | Decision | Source / date | Scope | Effect |
|---|---|---|---|---|
| fatsecret | **None in writing.** Questions drafted, not sent. | n/a (checked 2026-10-02) | n/a | `PERSIST_PROVIDER_OUTPUTS=false`, `PROVIDER_OUTPUT_POLICY_VERSION=pending`. Only `food_id` and `serving_id` may be stored (official docs). All other content is removed within 24 h (Terms §1.5). No durable A metrics, exports or fixtures. |
| USDA FDC | Public domain / CC0 (published license, not a custom grant) | https://fdc.nal.usda.gov/api-guide/, 2026-10-02 | All FDC data | Store and export allowed; cite FDC |
| Anthropic | No custom agreement. Standard API terms apply. | User-created Console key, 2026-10-02 | App B runtime inputs and outputs | Our own retention policy applies. Not a judgment on any fatsecret data. |

## Credential presence (boolean only)

| Variable | File | Status | How checked |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | `.env.agent.local` only | **set** (re-check 2026-10-02, `scripts/check-env-presence.sh`); absent from `.env.provider.local` | Claude's sandbox blocks the file. The user runs the `!` check from `docs/credential-handling.md` and reports `set`/`missing`. |
| `USDA_API_KEY` | both local files | **set** (user-run boolean check 2026-10-02) | Same |
| `FATSECRET_CLIENT_ID`, `FATSECRET_CLIENT_SECRET` | `.env.provider.local` | **set** (user-run boolean check 2026-10-02). Presence only: the image add-on, IP registration and rights are still unconfirmed. | Same |
| `ANTHROPIC_API_KEY` in the shell or user environment | n/a | **not set** (2026-10-02) | The same `!` check prints `not set` or a warning |

"Set" means present, not valid. Validity is only shown by the opt-in live smoke test (Prompt 19).

## What can proceed, and what's blocked

| Work | Status | Blocked by |
|---|---|---|
| Prompt 09 backlog (labels, milestones, 16 issues) | **Can proceed** once the user pastes Prompt 09 (it authorizes the GitHub changes) | n/a |
| POC-02 scaffold and CI (Prompt 10) | Can proceed | n/a |
| POC-03 contracts and nutrition arithmetic; POC-05 Measurement Kit | Can proceed | n/a |
| POC-04 image preparation | Can proceed with self-owned test images | n/a |
| POC-06 migrations and local private storage | Can proceed (Docker engine verified) | n/a |
| POC-07 USDA import and retrieval | Can proceed from a **downloaded** dataset. API fallback needs `USDA_API_KEY`. | Key only for fallback |
| POC-08 fatsecret adapter | Code and unit tests against **synthetic, MOCK-labeled** fixtures can proceed. **Live use is blocked.** | fatsecret account, image add-on, IP registration, written rights answers |
| POC-09/10 App B recognition and matching | Implemented. **Live grounded smoke passed** (2026-10-03, and Prompt 19 on 2026-10-06). Accuracy is not measured. | The live App B UI needs a `DATABASE_URL` inference login in `.env.agent.local` (user) |
| POC-12 reference set (30 dev meals) | **Blocked on people and real meals** | Real weighed meals and photos with consent, image-storage path (owner: Tony Jin) |
| POC-13 benchmark runs | Runner can be built and tested on synthetic predictions. Real runs are blocked. | Both live apps, POC-12 references, development batch budget |
| Any durable App A metric or report | **Blocked** | Written fatsecret permission |
| POC-15 calibration / locked test; POC-16 hosted pilot | Blocked | Enough referenced data (100+ groups per split); hosting decision |

**Honest timeline:**
- Plan §15's "Access and foundations" gate isn't met. Provider capabilities are still unknown (owners are now assigned: Tony Jin for all roles).
- Both apps can reach working MOCK mode independently. But the gate "both independently analyze a real image" can't be passed until fatsecret access and the Anthropic smoke test are done.
- Comparison results can't exist until real reference meals do.
- The fatsecret reply time is outside our control. **App A may stay blocked after App B works.** That status has to be shown as blocked, not filled in with a simulation (plan §12 Step 5).

## Sources

All accessed 2026-10-02.

- fatsecret image recognition v2: https://platform.fatsecret.com/docs/v2/image.recognition
- fatsecret OAuth 2.0: https://platform.fatsecret.com/docs/guides/authentication/oauth2
- fatsecret editions: https://platform.fatsecret.com/api-editions
- fatsecret guides (registration, contact): https://platform.fatsecret.com/docs/guides
- fatsecret terms: https://platform.fatsecret.com/terms
- USDA FDC API guide: https://fdc.nal.usda.gov/api-guide/
- USDA FDC downloads: https://fdc.nal.usda.gov/download-datasets/
- USDA key signup: https://fdc.nal.usda.gov/api-key-signup/
- Claude vision: https://platform.claude.com/docs/en/build-with-claude/vision
- Claude structured outputs: https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- Claude models overview: https://platform.claude.com/docs/en/about-claude/models/overview
- Claude API overview (keys, limits, billing): https://platform.claude.com/docs/en/api/overview
