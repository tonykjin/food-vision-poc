# Food Vision POC

Proof of concept that answers one question: for food-photo nutrition logging, should we build on an integrated provider or on our own recognition-plus-grounding pipeline?

Two independently runnable apps share one contract and one Measurement Kit, so their results can be compared fairly:

- **App A (provider):** fatsecret's image-recognition add-on returns foods, portions, and nutrition. USDA lookup is an optional mode.
- **App B (agent):** a vision model proposes food hypotheses, bounded matching grounds them in USDA FoodData Central, and our code calculates nutrition.
- **Measurement Kit (shared):** timing, cost, reliability, accuracy against held-out references, and confidence calibration.

Stack: Python, FastAPI, Streamlit, Pydantic, PostgreSQL (Docker Compose locally), Alembic, uv.

## Status

**Setup phase. There is no application code yet.** Development tools are installed and verified, including the Docker engine. Scaffolding starts at playbook Prompt 10. For live progress, see [`docs/execution-status.md`](docs/execution-status.md). Once GitHub Issues exist, they track engineering status.

## Documents

- [`docs/project-plan.md`](docs/project-plan.md): scope, architecture, configuration contract, evaluation protocol
- [`docs/claude-code-prompt-playbook.md`](docs/claude-code-prompt-playbook.md): execution sequence
- [`docs/project-settings.md`](docs/project-settings.md): nonsecret settings and pending decisions
- [`docs/setup-readiness.md`](docs/setup-readiness.md): development tool audit
- [`docs/decisions/`](docs/decisions/): architecture decision records

## Configuration

Copy `.env.example` to an ignored local file and fill in values there. Never commit real keys. Plan §6 has the full configuration contract.
