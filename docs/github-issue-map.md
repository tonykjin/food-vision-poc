# GitHub Issue Map

POC IDs from `docs/project-plan.md` §12 Step 5, mapped to the **actual** GitHub issues in `tonykjin/food-vision-poc`. Created 2026-10-02 (Prompt 09).

The numbers happen to match (POC-xx = #xx) because the repo had no earlier issues. Still look numbers up here; don't infer them.

| POC | Issue | Title | Labels | Milestone | Status | Playbook |
|---|---|---|---|---|---|---|
| POC-01 | [#1](https://github.com/tonykjin/food-vision-poc/issues/1) | Access and provider capability checks | vendor, shared, blocked, partial | Access and foundations | Partial; blocked on fatsecret written rights/add-on; live smoke tests pending | 07–08 (done), 19 |
| POC-02 | [#2](https://github.com/tonykjin/food-vision-poc/issues/2) | Repo scaffolding and CI | infra | Access and foundations | **Ready (first implementation task)** | 10 |
| POC-03 | [#3](https://github.com/tonykjin/food-vision-poc/issues/3) | Common contracts and nutrition arithmetic | shared | Access and foundations | After #2 | 11 |
| POC-04 | [#4](https://github.com/tonykjin/food-vision-poc/issues/4) | Shared image preparation | shared | Access and foundations | After #3 | 12 |
| POC-05 | [#5](https://github.com/tonykjin/food-vision-poc/issues/5) | Measurement Kit v1 | shared, evaluation | Access and foundations | After #3 | 13 |
| POC-06 | [#6](https://github.com/tonykjin/food-vision-poc/issues/6) | PostgreSQL migrations and private image storage | data, infra | Access and foundations | After #3 | 14 |
| POC-07 | [#7](https://github.com/tonykjin/food-vision-poc/issues/7) | USDA catalog import and retrieval | data, app-b | Two functional apps | After #6 | 15 |
| POC-08 | [#8](https://github.com/tonykjin/food-vision-poc/issues/8) | fatsecret adapter and App A | app-a, vendor, blocked | Two functional apps | Code/mock after #4, #5; live blocked on #1 | 16, 19 |
| POC-09 | [#9](https://github.com/tonykjin/food-vision-poc/issues/9) | First model adapter and App B recognition | app-b | Two functional apps | After #3–#5; live in Prompt 19 | 17, 19 |
| POC-10 | [#10](https://github.com/tonykjin/food-vision-poc/issues/10) | B matching tools and grounded calculation | app-b, data | Two functional apps | After #7, #9 | 18 |
| POC-11 | [#11](https://github.com/tonykjin/food-vision-poc/issues/11) | Shared result UI and confidence reasons | shared | Two functional apps | After #8, #10 | 20 |
| POC-12 | [#12](https://github.com/tonykjin/food-vision-poc/issues/12) | Reference manifest and 30-meal development set | evaluation, data, blocked | Evaluation and iteration | Tooling after #6; blocked on real meals (0 so far) | 21 |
| POC-13 | [#13](https://github.com/tonykjin/food-vision-poc/issues/13) | Benchmark runner and comparison report | evaluation | Evaluation and iteration | Runner after #5; real runs after #8, #10, #12 | 22–23 |
| POC-14 | [#14](https://github.com/tonykjin/food-vision-poc/issues/14) | Direct-model mode and additional adapters | app-b, evaluation | Evaluation and iteration | After #9, #13 | 24 |
| POC-15 | [#15](https://github.com/tonykjin/food-vision-poc/issues/15) | Calibration and locked evaluation | evaluation, blocked | Locked test and pilot release | Blocked on sufficient reference data | 25 |
| POC-16 | [#16](https://github.com/tonykjin/food-vision-poc/issues/16) | Hosted pilot and cofounder readout | infra | Locked test and pilot release | After #11, #13; hosting pending | 27–30 |

All issues are assigned to `tonykjin`, the only collaborator. No issue is closed.

**Labels** (created 2026-10-02): `app-a`, `app-b`, `shared`, `evaluation`, `data`, `infra`, `vendor` (plan §12 Step 5), plus `blocked` and `partial` for status.
**Milestones:** the four plan §15 phases.
