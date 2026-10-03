# Project Settings (nonsecret)

Nonsecret project facts and decisions. **Never put API keys, tokens, passwords, or connection strings with credentials here.** Secrets go in ignored local runtime files such as `.env.provider.local` and `.env.agent.local`, or in deployment secrets.

`PENDING` means the value is unknown or unconfirmed. A pending value blocks only the tasks that depend on it.

**Last updated:** 2026-10-02

## Repository

| Setting | Value | Status / source |
|---|---|---|
| GitHub owner | `tonykjin` (personal account) | Observed via `gh repo view`. **PENDING:** confirm this is the intended long-term owner rather than an organization. |
| Repository | `food-vision-poc` | Confirmed (renamed from `fatsecret-PoC` on 2026-10-02) |
| URL | https://github.com/tonykjin/food-vision-poc | Verified |
| Visibility | Private | Verified |
| Default branch | `main` | Verified |
| Local path | `C:\Users\tonyj\OneDrive\Desktop\food-vision-poc` | Verified |
| Branch protection / required review | PENDING | Plan Step 3; depends on the GitHub plan |
| Secret scanning | PENDING | Plan Step 3 |

## People and roles (plan §12 Step 1)

| Role | Owner | Status |
|---|---|---|
| Product thresholds | Tony Jin (`tonykjin`) | User decision 2026-10-02 |
| Technical implementation | Tony Jin (`tonykjin`) | User decision 2026-10-02 |
| Reference-data review | Tony Jin (`tonykjin`) | User decision 2026-10-02. Plan §11 asks for two reviewers on difficult identities and recipes. With one person, record those cases as single-reviewed. |
| Vendor / access / spend | Tony Jin (`tonykjin`) | User decision 2026-10-02 |
| PR reviewers | Tony Jin (`tonykjin`) | Sole reviewer, so review is self-review |
| Cofounders to invite | PENDING | Don't invite guessed users |

## Scope and runtime

| Setting | Value | Status |
|---|---|---|
| Pilot region | `US` | User decision 2026-10-02. Fits fatsecret Basic/Premier Free (US data only). |
| Language | `en` | Plan baseline; follows from the US region and not separately confirmed |
| Initial runtime vision provider | Anthropic (Claude API) | User created a Console API key 2026-10-02 |
| Runtime vision model ID | PENDING | Must be confirmed with a real capability smoke test |
| Comparison providers (later) | OpenAI, then DeepSeek | Plan baseline; added only after the core comparison works (POC-14) |
| Pipeline mode default | `grounded` | Plan baseline |
| Baseline image size | 512 px longest side | Plan baseline (§8 A2) |
| Max scan seconds | 45 | Plan baseline; adjustable after measurement |
| Max model calls per scan | 2 | Plan baseline |
| Max external attempts per scan | 8 | Plan baseline |
| Image retention | 30 days (proposed) | Plan baseline; consent may change it |
| Persist provider outputs | `false` | Default until fatsecret rights are confirmed in writing |
| Provider output policy version | `pending` | |

## Budgets

| Setting | Value | Status |
|---|---|---|
| Runtime smoke-test cap (Prompt 19) | No dollar cap | User decision 2026-10-02. Paid runs still need the explicit `ENABLE_LIVE_API_TESTS=true` opt-in. Real spend is limited only by the Console credit balance. |
| Development batch cap (Prompt 23) | No dollar cap | User decision 2026-10-02. Estimate and report cost before each batch. |
| Per-scan cost cap | No dollar cap | User decision 2026-10-02. Per-scan call limits still apply: `MAX_MODEL_CALLS_PER_SCAN=2`, `MAX_EXTERNAL_ATTEMPTS_PER_SCAN=8`, `MAX_SCAN_SECONDS=45`. |
| Spending alerts configured | PENDING | Plan Step 1 |
| How Claude Code dev usage vs runtime API is billed | Claude Code: user's Max plan. App B runtime: pay-as-you-go Console API credits, default workspace. | User-reported 2026-10-02. Keep `ANTHROPIC_API_KEY` out of shell and user env vars, or Claude Code bills to the API key. |

| Live smoke checks | **Authorized as needed** (user, 2026-10-02) | Opt-in via `ENABLE_LIVE_API_TESTS=true` in the app's local env file. Every run still needs `--confirm-one-request` and is capped at 1 token + 1 provider request, no retries, payload-free output. CI pins it to `false`. |

## Providers and accounts

Details are in `docs/provider-readiness.md` (Prompt 07, docs accessed 2026-10-02). The vendor question draft is in `docs/vendor-questions-fatsecret.md` (not sent).

- **Repo location: stays under OneDrive (user accepted the risk 2026-10-02).** Ignored local secret files, such as `.env.agent.local`, sync to OneDrive's cloud and linked devices. If OneDrive is ever compromised or shared, rotate the keys.

| Provider | Access status | Notes |
|---|---|---|
| fatsecret image add-on | Credentials present (2026-10-02); add-on, scope and IP registration unconfirmed | Blocks live App A only. Storage/derived-metric rights unconfirmed. |
| USDA FoodData Central API key | Present (boolean check 2026-10-02); no live call yet | Downloaded datasets don't need a key |
| Runtime vision model account | Key present in `.env.agent.local` (boolean check 2026-10-02); no live call yet | Separate from the Claude Code login (Max plan). Default workspace by user choice. |
| Supabase | Not needed yet | Only for the shared hosted pilot |

## Infrastructure and deployment

| Setting | Value | Status |
|---|---|---|
| Local database | PostgreSQL in Docker Compose | Plan baseline |
| Local image storage | Private local directory, outside Git | Plan baseline |
| Hosted database/storage | Supabase (proposed) | PENDING confirmation at hosted-pilot stage |
| Deployment destination | PENDING | Chosen after the local apps work |
| Hosting region | PENDING | Verify provider outbound/IP requirements first |
| Owned test image path (Prompt 19) | PENDING | Private path outside Git |

## Development tools

Full audit in `docs/setup-readiness.md` (Prompt 02).

| Tool | Status |
|---|---|
| Git | Installed (version recorded in Prompt 02) |
| GitHub CLI | 2.102.0, authenticated as `tonykjin` |
| Git identity | Configured (user.name `Tony Jin`) |
| Python | 3.12.10 (default); 3.11.1 also present; pin it in Prompt 10 |
| uv | 0.12.22 |
| Docker | Desktop 4.93.0 (per-user, WSL 2 backend), CLI 29.8.1; engine verified (server 29.8.1, Compose v5.5.1) |
| WSL | 3.0.1, default version 2 |
| Claude Code | 2.1.288 |
| Docker licensing tier | Agreement accepted by you 2026-10-02. Tier not recorded: PENDING confirmation (free under 250 employees and US$10M revenue) |
