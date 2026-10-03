# Food Vision POC

The plan is the source of truth for scope, architecture and evaluation: @docs/project-plan.md (read the relevant section before changing architecture or evaluation).
Execution order: `docs/claude-code-prompt-playbook.md`. Live handoff: `docs/execution-status.md`. Nonsecret settings: `docs/project-settings.md`. Decisions: `docs/decisions/`.

## Working rules

- Routine work inside the active prompt or issue is authorized. Finish its checks without repeatedly asking to continue. Ask only when a required input is missing or an external action isn't already authorized (accounts, spend, publishing, pushes, merges).
- One GitHub issue per branch. State scope before editing. Don't widen scope. Record any stack or scope change as an ADR.
- Read `docs/execution-status.md` and `git status` at the start of a session, and reconcile them. Update the status file when a step finishes.
- Don't push to `main` or merge PRs without the team's review workflow.
- Windows host. The shell is PowerShell 5.1 (Git Bash is also available). Use uv for Python (`uv run ...`); never use a bare system `python` for project code.

## Architecture invariants

- Build two independently runnable apps: **A** (fatsecret provider pipeline) and **B** (vision model plus USDA-grounded matching). Neither imports the other's pipeline. They share contracts, nutrition arithmetic, telemetry and evaluation (the Measurement Kit).
- Stack: Python, FastAPI, Streamlit, Pydantic, PostgreSQL, Alembic, uv. The commands in plan §6 are entry points to implement, not ones that already work.
- USDA is a nutrition data source, not an image-recognition provider.
- Check official provider docs before choosing endpoints or model parameters. Keep model IDs configurable. Record prompt, code, data and config versions.

## Nutrition and data correctness

- Never invent food IDs, nutrient values, benchmark results or confidence.
- Unknown nutrients stay `null`, never 0. Label partial results as partial.
- Nutrient arithmetic is deterministic, with explicit units and serving bases.
- Confidence is heuristic until it's calibrated on separate reference data. Model self-confidence and A/B agreement are not measured accuracy.

## Data policy and secrets

- Don't persist fatsecret output or derived metrics unless `PERSIST_PROVIDER_OUTPUTS` and the configured rights allow it. Apply each source's storage policy to writes, logs, fixtures and exports.
- The inference services must never access hidden benchmark labels. The evaluator database or credentials are separate.
- Never expose API keys or privileged database or storage credentials to UI users.
- Real secrets live only in ignored files (`.env.provider.local`, `.env.agent.local`, `secrets/`) or deployment secrets. **Never read, print or echo secret values**, even to troubleshoot. Credential checks report presence as a boolean only. See `docs/credential-handling.md`.
- `.env.example` holds names with empty values only.

## Measurement

- Log every retry and failure. Don't hide unsuccessful benchmark attempts.
- Use monotonic clocks for durations and UTC for event timestamps.
- Normal CI makes no live paid API calls. Live smoke tests need an explicit opt-in (`ENABLE_LIVE_API_TESTS=true`) and an approved budget.

## Completion evidence

- Add meaningful tests for units, contracts, adapters and metrics.
- Run `uv run ruff check .` and `uv run pytest` before proposing completion (once they exist after Prompt 10).
- Review the diff. Report which checks ran with their real results, plus any provider behavior you didn't verify.
- Never call a stub or mock a working live integration. Never claim success that wasn't observed.
