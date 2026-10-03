# 0001 — Adopt the project plan as the baseline

**Status:** Accepted
**Date:** 2026-10-02
**Deciders:** PENDING (recorded during Prompt 01)

## Context

`docs/project-plan.md` (prepared 2026-10-01) defines the scope and stack: two independently runnable apps (A: fatsecret provider; B: vision model + USDA grounding), a shared Measurement Kit, Python/Streamlit/FastAPI/Pydantic/PostgreSQL/Alembic/uv, and one private GitHub monorepo. `docs/claude-code-prompt-playbook.md` sequences its execution.

The GitHub repository already existed as an empty private repo named `fatsecret-PoC`. On 2026-10-02 it was renamed to `food-vision-poc`, and the two docs were pushed as the first commit. This happened before playbook Prompts 04 (local init) and 06 (publish).

## Decision

- Use the plan's technologies, scope, and POC-01–16 backlog unchanged as the baseline.
- Keep the existing private repo `tonykjin/food-vision-poc` as the project repository. Prompts 04 and 06 reconcile with it instead of initializing or creating a new one.

## Consequences

- Any later change of stack or scope needs a new ADR.
- The repo owner is the personal account `tonykjin`. Moving it to an organization later is possible (GitHub transfers keep redirects) but stays PENDING confirmation in `docs/project-settings.md`.
