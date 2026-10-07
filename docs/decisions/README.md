# Architecture Decision Records

Short records of decisions that change or clarify the baseline in `docs/project-plan.md`. Any change to technology or scope needs a record here explaining why.

Name files `NNNN-short-title.md`, numbered in sequence. Don't rewrite an accepted record. Supersede it with a new one and link both.

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-adopt-plan-baseline.md) | Adopt the project plan as the baseline | Accepted |
| [0002](0002-evaluator-registers-benchmark-images.md) | Evaluator registers benchmark images; manifests are group files outside Git | Proposed |

## Template

```markdown
# NNNN — Title

**Status:** Proposed | Accepted | Superseded by NNNN
**Date:** YYYY-MM-DD
**Deciders:** names or PENDING

## Context
What forces the decision; link the plan section or issue.

## Decision
What we will do.

## Consequences
What changes, what it costs, what becomes harder or easier.
```
