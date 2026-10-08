# Hosted pilot deployment plan (POC-16, Prompt 27)

**Status (2026-10-08): packaging done and verified locally; destination PENDING.** Nothing has been provisioned. Built from the real code and `infra/compose.yml`, not a generic diagram.

**Deployment readiness is not a business result.** A working deployment says nothing about accuracy: 0 real reference meals exist, and the only evaluation run used synthetic references (`docs/dev-runs/2026-10-08-poc25-synthetic.md`). The go/no-go gates remain INCONCLUSIVE.

## Services (one image, four containers, two independent apps)

| Service | Command | Network | Published | Secrets it receives |
|---|---|---|---|---|
| `a-api` | `uvicorn foodvision.api.provider_app:app` :8001 | `app_a` | no | `.env.provider.local` only: fatsecret ID/secret, USDA key |
| `a-ui` | `streamlit run apps/provider_ui.py` :8501 | `app_a` | via auth proxy only | **none** (just `PROVIDER_API_URL`) |
| `b-api` | `uvicorn foodvision.api.agent_app:app` :8002 | `app_b`, `b_data` | no | `.env.agent.local` only: model key(s), USDA key; `DATABASE_URL` = an `fv_inference` login |
| `b-ui` | `streamlit run apps/agent_ui.py` :8502 | `app_b` | via auth proxy only | **none** (just `AGENT_API_URL`) |
| `postgres` | Postgres 17 | `b_data` (+ local dev) | local only | — |

- **Independence:** Compose profiles `app-a` and `app-b` start each app alone. App A runs without any model key or database, and App B without fatsecret.
- **Network isolation:** each UI reaches only its own API. App A's containers can't reach App B or the database, and only `b-api` reaches Postgres.
- **Verified locally in MOCK mode (2026-10-08):** all healthy; secret-like variable names per container as in the table; UI → own API 200; UI → other app's API and UIs/A → Postgres unreachable; 11 MB upload → `413 image_too_large`.
- **Image:** `infra/Dockerfile` (python:3.12-slim + uv 0.12.23, locked production dependencies, non-root uid 10001). `.dockerignore` keeps env files, `secrets/`, `data/`, `work/`, tests and docs out of every image (checked: no `.env*` in `/app`).

## Authentication boundary

- Only the two UIs face users, behind **one authenticated reverse proxy** (implemented in Prompt 28). Streamlit has no login of its own, and the APIs are never exposed.
- Pilot users: **PENDING** (`project-settings.md`: cofounders to invite). Access is allow-listed per person; no public signup.
- The UIs hold no secrets, so a UI user can never read a key. Provider calls happen only inside the API containers.

## Database roles

| Role | Used by | Can |
|---|---|---|
| owner / migration (`MIGRATION_DATABASE_URL`) | the one-off migration and catalog-import job only | everything; **never in an app's env** (`doctor` flags it) |
| `fv_inference` login | `b-api` | read `food_catalog`, write run telemetry; **nothing on `benchmark`** (checked at runtime) |
| `fv_evaluator` login | evaluator CLI only (not deployed) | read everything, write `benchmark`, register benchmark images |

## Private images and retention

- **Uploaded photos are not stored.** Both APIs prepare the image in memory and return a result. No object store is deployed, so there's nothing to retain or delete.
- If storage is added later, it follows `data/object_store.py`: a private directory, metadata only in Postgres, 30-day proposed retention, tombstoned deletion.
- fatsecret results stay transient (rights pending; `PERSIST_PROVIDER_OUTPUTS=false`). Telemetry is in-memory per process today (no durable sink yet).

## Runtime secrets

- Provided by the host's secret mechanism, or root-only env files on the host, mapped as in the table. Never in the image, compose file, Git or chat.
- `B_DATABASE_URL` is supplied by the host environment (the in-network host is `postgres`).
- Model keys: `ANTHROPIC_API_KEY` (default provider) and optionally `OPENAI_API_KEY`. The App B keys and the GitHub integration's credential stay separate.

## Provider outbound / IP requirements

| Provider | Requirement |
|---|---|
| fatsecret | **The host's outbound IP must be registered** in fatsecret key management; otherwise image calls fail with code 21. The host needs a **static egress IP**. Plan: Premier Free / US data; image add-on enabled; 25k photo-request quota. |
| Anthropic / OpenAI | HTTPS outbound; no IP allow-list. |
| USDA FDC | HTTPS outbound, only for catalog imports (not per scan). |

## Health checks, migrations, limits

- **Health:** `GET /health` (APIs) and `/_stcore/health` (UIs) are wired as container health checks. `/health` reports `ready` and the actual `pipeline_id`. A UI starts only after its API is healthy.
- **Migrations:** a one-off job using the same image, `alembic upgrade head` with `MIGRATION_DATABASE_URL`. Then the catalog import (`foodvision import-usda …`) and creating the `fv_inference` login. **Back up the database before every migration.**
- **Limits:**
  - upload ≤ 10 MB (API `413`, Streamlit `--server.maxUploadSize 10`)
  - decoded-pixel limit and baseline 512 px preparation
  - per-scan deadline 45 s, ≤ 2 model calls, ≤ 8 external attempts
  - the reverse proxy should also cap the request body at about 11 MB

## Costs (measured per scan; hosting depends on the destination)

- **App B (Claude, `B_grounded`):** about $0.04-0.07 per scan measured (2026-10-07/08). OpenAI `B_direct`: about $0.10. Paid from prepaid Console credits / OpenAI credits; there's no dollar cap per scan (recorded decision), only call and attempt limits.
- **App A:** a flat fatsecret plan with a 25k photo-request quota; there's no per-request price on record.
- **Hosting:** one small VM (two Python apps + Postgres; about 2 vCPU / 4 GB is plenty for a few pilot users) plus a static IP. **Price not estimated until the destination is chosen.** Set provider spending alerts (`project-settings`: PENDING).

## Rollback

- Images are tagged with the git commit (`FOODVISION_TAG=<sha>`). Rollback = redeploy the previous tag (`docker compose … up -d`).
- Migrations so far are additive (`0001`-`0003`) and have tested `downgrade`. Restore the pre-migration backup if needed.
- Each app can be stopped or rolled back alone (separate profiles), so an App A problem never takes down App B.

## Deployment checklist

1. [ ] **Choose the destination** (see the questions below). Record it in `project-settings.md`.
2. [ ] Provision **one VM with a static egress IP** in the chosen region. Install Docker + Compose.
3. [ ] **Register the VM's egress IP with fatsecret.** Test with one `foodvision smoke-fatsecret` from the VM.
4. [ ] Put runtime secrets on the host (root-only), one file per app, plus `B_DATABASE_URL`.
5. [ ] Postgres: managed (Supabase, if chosen) or the compose `postgres` with a persistent volume and backups. Run migrations → catalog import → create the `fv_inference` login.
6. [ ] Prompt 28: add the authenticated reverse proxy (TLS, allow-listed users, body-size cap) in front of the two UIs.
7. [ ] `docker compose --profile app-a --profile app-b up -d` with `FOODVISION_TAG=<sha>`. Check health and run one live smoke per app from the VM.
8. [ ] Confirm no keys, private image URLs or provider payloads appear in logs. Record the URLs, region and rollback tag.
9. [ ] Spending alerts on Anthropic/OpenAI and the host.

## Required human / account actions

- **Destination account and region** (the only blocker for provisioning). Options:
  - **A: one VM running this Compose setup** (any provider with static IPs). Simplest and matches the plan ("an authenticated Docker Compose deployment on one host is sufficient").
  - **B: the same VM with Supabase for Postgres.** A managed database, but one more account; still needs the VM for the apps.
  - **C: a container PaaS.** Less ops, but a static egress IP for fatsecret is often a paid add-on; check before choosing.
- **Pilot users:** who gets access (emails), and how they sign in (decided in Prompt 28).
- **Spend:** a hosting budget and spending alerts.
- **fatsecret:** register the host IP; send the storage-rights questions before any durable App A results.
