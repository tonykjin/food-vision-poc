# Verification Matrix

Maps each issue's acceptance criteria to how it's verified. **T** = automated test (CI, no paid secrets). **L** = opt-in live check (`ENABLE_LIVE_API_TESTS=true`, Prompt 19 or later). **H** = human check, recorded in the issue. The full criteria live in each GitHub issue (see `docs/github-issue-map.md`).

A criterion passes only on observed evidence. A stub, mock or empty file is not evidence.

| Issue | Criterion | Check |
|---|---|---|
| #1 POC-01 | Readiness docs, vendor questions | H: done 2026-10-02 |
| | Credential presence | H: boolean check done 2026-10-02 |
| | fatsecret written answers recorded | H: vendor reply with source/date/scope |
| | Policy version set or persistence stays off | H + T (config default test) |
| | fatsecret image smoke test | L: status, latency, shape; no payload persisted |
| | Anthropic vision + structured output smoke test | L |
| #2 POC-02 | Frozen install | T: CI `uv sync --frozen` |
| | Independent launch, own secrets only | T: import/config isolation test + H: launch each app |
| | MOCK labeling | T: mock result carries MOCK label + H: UI check |
| | Doctor is boolean-only | T: output never contains a test secret value |
| | Local Postgres | H: `docker compose ... up -d postgres` |
| | CI Ruff + pytest without secrets | T: PR workflow run |
| | Launch docs | H: README review |
| #3 POC-03 | Schema rejects bad enums, negatives, non-finite | T: contract tests |
| | Per-100 g / per-serving scaling | T: hand-computed cases |
| | kJ basis, no ml→g without density | T |
| | Null preserved; partial totals | T |
| | Display-only rounding | T |
| | Off-list IDs rejected | T |
| #4 POC-04 | Reject bad content before billed call | T |
| | Location metadata stripped | T: EXIF-GPS fixture |
| | Identical A/B bytes | T: hash equality |
| | Serialized body size | T: base64 + JSON overhead case |
| | Preprocessing version recorded | T |
| #5 POC-05 | Monotonic durations, UTC timestamps | T: fake clocks |
| | All attempts, retries, failures emitted | T |
| | Overlapping spans not double-summed | T |
| | Policy filter on every export; pending-rights mode | T: each export path |
| | Payload-free events | T |
| | `client_total_ms` unavailable | T |
| #6 POC-06 | Clean upgrade/downgrade | T: CI disposable Postgres |
| | Inference role denied on reference tables | T: permission test |
| | NULL nutrients | T |
| | Images outside DB/Git; retention | T + H |
| #7 POC-07 | Reproducible versioned import | T: small CC0 subset |
| | Cooked/dry, raw/cooked filters | T: fixture queries |
| | No evaluator schema access | T |
| | `api_key` not logged | T: log capture |
| | Known queries → expected FDC IDs | T |
| #8 POC-08 | Synthetic-fixture adapter tests | T |
| | App A runs without model key or App B | T + H |
| | No restricted persistence/logging/export | T: policy tests |
| | Attribution displayed | H: UI check |
| | Opt-in smoke command exists | T: skipped without opt-in |
| | Real image → result | L (blocked on #1) |
| #9 POC-09 | Refusal, truncation, invalid output typed | T: synthetic responses |
| | No CoT request, no self-confidence % | T + H: prompt review |
| | App B runs without fatsecret keys | T + H |
| | Model/prompt/metadata recorded | T |
| | Real hypotheses | L |
| #10 POC-10 | Off-list IDs rejected | T |
| | Wrong preparation can't win | T |
| | Unresolved → partial, not zero | T |
| | Budgets/deadline enforced | T: fake clock and counters |
| | Ranges labeled as assumptions | T + H |
| #11 POC-11 | Same fields/states in both apps | T + H: UI checklist |
| | No percentage from self-confidence or agreement | H + T |
| | Null shown as unknown | T + H |
| | Partial labeled | T + H |
| | Timing labels correct | H |
| #12 POC-12 | Split-leakage rejection | T |
| | Labels inaccessible to inference | T |
| | Real meal count explicit | H |
| | 30 reviewed dev meals | H: review log (blocked on real meals) |
| | Single-reviewer cases flagged | H |
| #13 POC-13 | Synthetic predictions → exact metrics | T |
| | Failures in denominators | T |
| | Agreement separate from accuracy | T |
| | A metrics unavailable while rights pending | T: policy test |
| | Group-level aggregation | T |
| #14 POC-14 | Distinct configs, no mixing | T |
| | Capability verified per provider | H: docs + L probe |
| | CI without paid secrets | T: workflow audit |
| #15 POC-15 | No test labels in calibration | T + H: leakage audit |
| | Insufficient buckets labeled | T |
| | Calibration version recorded | T |
| | Reproducible held-out report | H: rerun from frozen commit |
| #16 POC-16 | Authenticated URLs, own secrets | H + L: deployment smoke |
| | No secrets/payloads in logs | H: log inspection |
| | Rollback recorded | H |
| | Evidence-based readout | H: cofounder review |
