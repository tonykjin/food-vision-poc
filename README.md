# Food Vision POC

Proof of concept that answers one question: for food-photo nutrition logging, should we build on an integrated provider or on our own recognition-plus-grounding pipeline?

Two independently runnable apps share one contract and one Measurement Kit, so their results can be compared fairly:

- **App A (provider):** fatsecret's image-recognition add-on returns foods, portions, and nutrition. USDA lookup is an optional mode.
- **App B (agent):** a vision model proposes food hypotheses, bounded matching grounds them in USDA FoodData Central, and our code calculates nutrition.
- **Measurement Kit (shared):** timing, cost, reliability, accuracy against held-out references, and confidence calibration.

Stack: Python, FastAPI, Streamlit, Pydantic, PostgreSQL (Docker Compose locally), Alembic, uv.

## Status

**Scaffold only (POC-02, #2).**
- Both apps launch and serve health and analyze endpoints. Real analysis isn't implemented yet: live mode returns HTTP 501 `not_implemented`.
- `MOCK_MODE=true` returns a **synthetic MOCK result** with all nutrients unknown (null). MOCK is not a provider integration and not a nutrition estimate.
- Progress: [`docs/execution-status.md`](docs/execution-status.md) and [`docs/github-issue-map.md`](docs/github-issue-map.md).

## Run locally (Windows PowerShell)

Prerequisites: uv and Docker Desktop (see `docs/setup-readiness.md`). Run everything from the repo root.

```powershell
uv sync --frozen
uv run foodvision doctor --app provider   # prints set/missing only, never values
uv run foodvision doctor --app agent
docker compose -f infra/compose.yml up -d postgres   # optional now; used from POC-06
```

Each app reads only its own ignored env file: App A reads `.env.provider.local` and App B reads `.env.agent.local`. Shell variables override file values.

**App A (provider)**, in two terminals:

```powershell
$env:MOCK_MODE = "true"; uv run uvicorn foodvision.api.provider_app:app --host 127.0.0.1 --port 8001
uv run streamlit run apps/provider_ui.py --server.port 8501
```

**App B (agent)**, in two terminals:

```powershell
$env:MOCK_MODE = "true"; uv run uvicorn foodvision.api.agent_app:app --host 127.0.0.1 --port 8002
uv run streamlit run apps/agent_ui.py --server.port 8502
```

Without `MOCK_MODE=true`, `/v1/analyze` returns 501 until POC-08 (A) or POC-09/POC-10 (B) land. API docs: http://127.0.0.1:8001/docs and http://127.0.0.1:8002/docs.

Local Postgres listens on `127.0.0.1:5432` (user/db `foodvision`). The default password is a local-only dev value in `infra/compose.yml`. Put your `DATABASE_URL` in the app's local env file, not in Git.

### Database (POC-06)

Three schemas with enforced access:

| Schema | Holds | `fv_inference` | `fv_evaluator` |
|---|---|---|---|
| `food_catalog` | Nutrition records | read | read |
| `telemetry` | Image metadata, runs, events, policy-filtered results | write | read |
| `benchmark` | Samples, hidden reference labels, metrics | **no access** | read/write |

Migrate with the owner role, set only in your shell:

```powershell
$env:MIGRATION_DATABASE_URL = "postgresql+psycopg://foodvision:<compose password>@127.0.0.1:5432/foodvision"
uv run alembic upgrade head
```

Create login users per environment. Never use the owner URL in an app. In `psql`, `\password` prompts so the secret stays out of shell history:

```sql
CREATE ROLE app_a_inference LOGIN IN ROLE fv_inference;  \password app_a_inference
CREATE ROLE evaluator_1     LOGIN IN ROLE fv_evaluator;  \password evaluator_1
```

- Put the inference URL in the app's `DATABASE_URL`.
- Put the evaluator URL only in the evaluator's environment.
- `foodvision doctor` flags `EVALUATOR_DATABASE_URL` or `MIGRATION_DATABASE_URL` if they appear in an app's env file.

Images are stored as files, one per image ID, outside Git: either outside the repo or under the ignored `data/`. Postgres keeps only the key, hashes, consent basis and retention deadline. Deletion removes the file and keeps a tombstone row.

Database tests create and drop a throwaway database. They need an admin URL to a local or disposable server, and they skip without one:

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://foodvision:<compose password>@127.0.0.1:5432/foodvision"
uv run pytest tests/db
```

### App A live mode (POC-08)

With `FATSECRET_CLIENT_ID`/`SECRET` in `.env.provider.local` and no `MOCK_MODE`, App A calls fatsecret image recognition (no LLM fallback). It's adapter-tested with fake HTTP only. Real behavior is **unverified** until the opt-in smoke test (`foodvision smoke-fatsecret`) runs. See [`docs/app-a-fatsecret.md`](docs/app-a-fatsecret.md).

### App B live mode (POC-09/10)

With `ANTHROPIC_API_KEY` and `DATABASE_URL` (an `fv_inference` login) in `.env.agent.local`, App B runs `B_grounded`: Claude recognition, USDA retrieval, selection of a retrieved ID or `no_match`, and nutrients calculated in code. `PIPELINE_MODE=recognition_only` returns hypotheses without nutrients. See [`docs/app-b-grounded.md`](docs/app-b-grounded.md) and [`docs/app-b-vision.md`](docs/app-b-vision.md).

### USDA catalog (POC-07)

See [`docs/catalog.md`](docs/catalog.md) for the documented FDC subset, the import commands (`foodvision import-usda`, `import-usda-api`, `catalog-report`), retrieval rules and known gaps.

### Benchmark reference data (POC-12)

Real reference meals live in a private folder outside Git. See [`benchmarks/protocol.md`](benchmarks/protocol.md) for weighing, photographing and review, [`benchmarks/collection-form.md`](benchmarks/collection-form.md) for the kitchen form, and [`benchmarks/dataset-card.md`](benchmarks/dataset-card.md). Commands: `foodvision validate-manifest`, `assign-splits`, `load-manifest` (evaluator login only). `benchmarks/examples/` holds synthetic groups that are never counted.

### Human UI checks (each app)

1. Open http://localhost:8501 (A) or http://localhost:8502 (B). The title names the right app, and a red **MOCK MODE** banner appears.
2. Upload a JPG/PNG/WebP you own and press **Analyze**. You should see:
   - "MOCK result (synthetic)" and the **Partial** banner
   - Status `partial`
   - The MOCK warnings
   - "Totals unavailable", and every item nutrient showing **unknown** (never 0)
   - "Confidence: not assessed" and "Reference unavailable"
   - An item named "MOCK item (synthetic, not a recognized food)"
   - "Click-to-render (client_total_ms): unavailable"
   - No "User corrections" form (MOCK has nothing to correct)
3. Stop the API and reload the page. It should show "API not reachable".
4. Restart the API without `MOCK_MODE` and without credentials, then analyze. It should show the **Failed** banner with `authentication` and HTTP 503.
5. With a live result (App B with `DATABASE_URL`): confidence shows Low/Medium/High per identity, portion and nutrition match, labeled "heuristic, uncalibrated", with no percentage. Record a correction: it appears under "User corrections", and the automatic result above is unchanged.

The result screen and confidence rules are described in [`docs/result-ui.md`](docs/result-ui.md).

### Checks

```powershell
uv run ruff check .
uv run pytest
```

CI (`.github/workflows/ci.yml`) runs the frozen install, Ruff and pytest on every PR. It uses no provider secrets.

### Not implemented yet

| Command / entry point (plan §6, §14) | Arrives with |
|---|---|
| `apps/compare_ui.py` | POC-13 (#13) |
| `foodvision benchmark`, `foodvision report` | POC-13 (#13) |
| `foodvision calibrate` | POC-15 (#15) |
| `infra/Dockerfile` | POC-16 (#16) |

## Documents

- [`docs/project-plan.md`](docs/project-plan.md): scope, architecture, configuration contract, evaluation protocol
- [`docs/claude-code-prompt-playbook.md`](docs/claude-code-prompt-playbook.md): execution sequence
- [`docs/project-settings.md`](docs/project-settings.md): nonsecret settings and pending decisions
- [`docs/setup-readiness.md`](docs/setup-readiness.md): development tool audit
- [`docs/decisions/`](docs/decisions/): architecture decision records

## Configuration

Copy `.env.example` to an ignored local file and fill in values there. Never commit real keys. Plan §6 has the full configuration contract.
