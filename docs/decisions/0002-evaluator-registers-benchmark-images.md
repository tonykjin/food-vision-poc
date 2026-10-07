# 0002 — Evaluator registers benchmark images; manifests are group files outside Git

**Status:** Proposed
**Date:** 2026-10-07
**Deciders:** PENDING (Tony Jin to accept with the POC-12 PR)

## Context

POC-12 (#12) loads reviewed reference groups into the `benchmark` schema. Two facts about the POC-06 schema got in the way:
- `benchmark.samples.image_id` references `telemetry.images`.
- `fv_evaluator` could only read `telemetry`, so the evaluator couldn't register benchmark photos.

Plan §5 requires separate inference and evaluator credentials, with no access to hidden labels for inference.

The plan's example command uses `benchmarks/pilot-v1.jsonl` inside the repository. Real manifests contain hidden labels and participants' photo references, which plan §5 and CLAUDE.md keep out of Git.

## Decision

- Migration `0003` grants `fv_evaluator` **INSERT on `telemetry.images` only**. Image rows hold an object key, hashes, consent and retention, none of which are labels. Inference access is unchanged, and `fv_inference` still has nothing on schema `benchmark`. The loader checks both before writing.
- Migration `0003` also adds `benchmark.samples.expected_outcome` (`estimate` or `abstain`) for difficult inputs where abstaining is correct.
- Real manifests are **one JSON file per group** (JSONL also accepted) in a private directory outside Git (`BENCHMARK_DATA_DIR`). The repository holds only the format, the tools and synthetic examples. `validate-manifest` refuses real data in a tracked part of the repository.
- Sample IDs include the reference version, so a new load never overwrites an earlier, possibly locked, version.

## Consequences

- An evaluator login can add image rows. It still can't change or delete existing ones; deletion stays with the owner or migration role.
- Evaluations name their references by `reference_version` (`<name>@<manifest hash>`) instead of a file path in Git.
- The `benchmarks/pilot-v1.jsonl` path in plan §14 becomes a private path. The commands are otherwise as planned.
