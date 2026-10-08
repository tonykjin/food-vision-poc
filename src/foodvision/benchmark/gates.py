"""Go / no-go / inconclusive evidence for the plan §15 decision gates (POC-15).

Each automated gate turns a group-level 95% interval into a verdict against its threshold:
GO when the whole interval meets it, NO-GO when the whole interval misses it, otherwise
INCONCLUSIVE ("collect more data" is a valid outcome). The thresholds are the plan's proposed
business gates, not yet approved, so every verdict is PROVISIONAL. Gates needing human
judgment (cost materiality, false-high-confidence review) are reported, never auto-passed.
"""

from collections.abc import Sequence

from foodvision.benchmark.metrics import (
    ABSTAIN_EQUIVALENT_ERRORS,
    Attempt,
    Reference,
    group_bootstrap,
    is_useful,
    paired_useful_difference,
    percentile,
)

GATES_VERSION = "gates-v1 (PROVISIONAL: plan §15 proposed thresholds, not yet approved)"
TYPED_WITHIN_DEADLINE_MIN = 0.95
P95_LIMIT_MS = 15_000.0
MAX_USEFUL_SHORTFALL = 0.05  # B no more than 5 percentage points below A
GO, NO_GO, INCONCLUSIVE, HUMAN = "GO", "NO-GO", "INCONCLUSIVE", "NEEDS HUMAN DECISION"


def _verdict_at_least(ci, threshold) -> str:
    if ci is None:
        return INCONCLUSIVE
    low, high = ci
    return GO if low >= threshold else NO_GO if high < threshold else INCONCLUSIVE


def _verdict_at_most(ci, threshold) -> str:
    if ci is None:
        return INCONCLUSIVE
    low, high = ci
    return GO if high <= threshold else NO_GO if low > threshold else INCONCLUSIVE


def typed_within_deadline(attempt: Attempt, deadline_ms: float) -> bool:
    ok = attempt.status in ("complete", "partial", "abstained") or (
        attempt.status == "failed" and attempt.error_code in ABSTAIN_EQUIVALENT_ERRORS
    )
    return ok and attempt.server_total_ms <= deadline_ms


def evaluate_gates(
    attempts_by_config: dict[str, Sequence[Attempt]],
    refs: dict[str, Reference],
    deadline_ms: float,
    complete_batch: bool,
    provider_config: str | None,
    agent_config: str | None,
) -> dict:
    gates: dict[str, dict] = {}
    for config, attempts in attempts_by_config.items():
        rate = (
            sum(typed_within_deadline(a, deadline_ms) for a in attempts) / len(attempts)
            if attempts
            else None
        )
        ci = group_bootstrap(
            attempts,
            lambda s: sum(typed_within_deadline(a, deadline_ms) for a in s) / len(s) if s else None,
        )
        gates[f"typed_result_within_deadline[{config}]"] = {
            "threshold": f">= {TYPED_WITHIN_DEADLINE_MIN:.0%} of attempts",
            "value": rate,
            "ci95": ci,
            "verdict": _verdict_at_least(ci, TYPED_WITHIN_DEADLINE_MIN),
        }
        times = [a.server_total_ms for a in attempts]
        p95_ci = group_bootstrap(
            attempts, lambda s: percentile([a.server_total_ms for a in s], 0.95)
        )
        gates[f"p95_server_time[{config}]"] = {
            "threshold": f"<= {P95_LIMIT_MS / 1000:.0f} s",
            "value": percentile(times, 0.95),
            "ci95": p95_ci,
            "verdict": _verdict_at_most(p95_ci, P95_LIMIT_MS),
        }
        groups = {a.group_id for a in attempts if refs[a.group_id].scorable}
        gates[f"scorable_groups[{config}]"] = {"value": len(groups), "verdict": "INFO"}
    gates["no_hidden_exclusions"] = {
        "threshold": "complete batch, nothing silently dropped",
        "value": complete_batch,
        "verdict": GO if complete_batch else NO_GO,
    }
    if provider_config and agent_config:
        diff = paired_useful_difference(
            attempts_by_config[agent_config], attempts_by_config[provider_config], refs
        )
        gates["useful_rate_B_minus_A"] = {
            "threshold": f"B no more than {MAX_USEFUL_SHORTFALL:.0%} points below A",
            "value": diff["difference"],
            "ci95": diff["ci95"],
            "paired_groups": diff["paired_groups"],
            "verdict": _verdict_at_least(diff["ci95"], -MAX_USEFUL_SHORTFALL),
        }
    useful_cost = {}
    for config, attempts in attempts_by_config.items():
        useful = sum(is_useful(a, refs[a.group_id]) for a in attempts if refs[a.group_id].scorable)
        unknown = any(a.estimated_cost_usd is None for a in attempts)
        known = sum(a.known_cost_usd for a in attempts)
        useful_cost[config] = None if unknown or not useful else known / useful
    gates["cost_materiality"] = {
        "threshold": "lower cost or better performance material enough to justify owning B",
        "value": useful_cost,
        "verdict": HUMAN,
    }
    gates["false_high_confidence_review"] = {
        "threshold": "false-high-confidence cases reviewed",
        "verdict": HUMAN,
    }
    automated = [g["verdict"] for g in gates.values() if g["verdict"] in (GO, NO_GO, INCONCLUSIVE)]
    overall = NO_GO if NO_GO in automated else INCONCLUSIVE if INCONCLUSIVE in automated else GO
    return {"gates_version": GATES_VERSION, "overall": f"{overall} (provisional)", "gates": gates}
