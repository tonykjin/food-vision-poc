"""Benchmark report with storage rights applied (POC-13).

Status counts, latency and cost are payload-free metadata and always reportable. Accuracy,
repeatability, item and agreement metrics are *derived metrics*: for a source whose rights are
pending (fatsecret), they are computed and shown transiently but never written to disk; the
saved report says so explicitly instead of showing an empty or zero section.
"""

from collections.abc import Sequence
from dataclasses import asdict

from foodvision.benchmark.metrics import (
    ITEM_MAPPING,
    METRICS_VERSION,
    USEFUL_DEFINITION,
    Attempt,
    Reference,
    agreement,
    config_metrics,
    paired_useful_difference,
)
from foodvision.measurement.storage_policy import DataClass, DataSource, Purpose, StoragePolicy

CONFIG_SOURCES = {
    "A_native": DataSource.FATSECRET,
    "B_grounded": DataSource.VISION_MODEL,
    "B_direct": DataSource.VISION_MODEL,
    "A_mock": DataSource.MOCK,
    "B_mock": DataSource.MOCK,
}
DERIVED_SECTIONS = (
    "useful",
    "scorable_error",
    "partial",
    "abstention",
    "items",
    "repeatability",
    "by_category",
)
UNAVAILABLE = (
    "UNAVAILABLE in saved reports: fatsecret storage rights are pending, so derived metrics "
    "are transient only (shown in the terminal during the run, never written)"
)


def source_of(config: str) -> DataSource:
    return CONFIG_SOURCES[config]


def build_report(
    attempts: Sequence[Attempt],
    refs: dict[str, Reference],
    configs: Sequence[str],
    policy: StoragePolicy,
    purpose: Purpose,
    meta: dict,
    not_run: int = 0,
) -> dict:
    def derived_ok(config: str) -> bool:
        return policy.allows(source_of(config), DataClass.DERIVED_METRIC, purpose)

    report: dict = {
        "metrics_version": METRICS_VERSION,
        "useful_definition": USEFUL_DEFINITION,
        "item_mapping": ITEM_MAPPING,
        "purpose": purpose.value,
        "policy_version": policy.version,
        "complete_batch": not_run == 0,
        "not_run": not_run,
        "notes": [
            "Useful-result pass rate: denominator is EVERY attempt on a group with a scorable "
            "(grade A/B, complete) reference; failures, abstentions and partial results count "
            "as non-passes.",
            "Scorable-output error is a separate statistic over complete results only.",
            "Intervals: 95% bootstrap resampling whole groups (all photos and repeats).",
            "Agreement between configurations is not accuracy.",
        ],
        **meta,
        "configs": {},
    }
    if not_run:
        report["notes"].insert(0, f"INCOMPLETE BATCH: {not_run} planned run(s) were not run.")

    by_config = {c: [a for a in attempts if a.config == c] for c in configs}
    for config in configs:
        section = asdict(config_metrics(config, by_config[config], refs))
        if not derived_ok(config):
            for key in DERIVED_SECTIONS:
                section[key] = UNAVAILABLE
        report["configs"][config] = section

    if len(configs) == 2:
        a, b = configs
        if derived_ok(a) and derived_ok(b):
            report["comparison"] = {
                "agreement": agreement(by_config[a], by_config[b]),
                f"useful_pass_rate_difference_{a}_minus_{b}": paired_useful_difference(
                    by_config[a], by_config[b], refs
                ),
            }
        else:
            report["comparison"] = UNAVAILABLE
    return report


def _fmt(value) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    if isinstance(value, tuple | list) and len(value) == 2:
        return f"[{_fmt(value[0])}, {_fmt(value[1])}]"
    return str(value)


def to_markdown(report: dict) -> str:
    lines = [
        f"# Benchmark report ({report.get('batch_id', 'batch')})",
        "",
        f"- Metrics {report['metrics_version']}; useful-result definition "
        f"{report['useful_definition']}",
        f"- Purpose: {report['purpose']}; storage policy {report['policy_version']}",
        f"- Split {report.get('split')}; repeats {report.get('repeats')}; reference "
        f"{report.get('reference_version')}",
        f"- Complete batch: {report['complete_batch']} (not run: {report['not_run']})",
        "",
        *[f"> {n}" for n in report["notes"]],
    ]
    for config, section in report["configs"].items():
        lines += ["", f"## {config}", ""]
        for key, value in section.items():
            if key == "config":
                continue
            if isinstance(value, dict):
                lines.append(f"**{key}**")
                for k, v in value.items():
                    if isinstance(v, dict):
                        detail = ", ".join(f"{kk} {_fmt(vv)}" for kk, vv in v.items())
                        lines.append(f"- {k}: {detail}")
                    else:
                        lines.append(f"- {k}: {_fmt(v)}")
            else:
                lines.append(f"**{key}**: {_fmt(value)}")
    if "comparison" in report:
        lines += ["", "## Comparison", ""]
        comparison = report["comparison"]
        if isinstance(comparison, str):
            lines.append(comparison)
        else:
            for key, value in comparison.items():
                detail = ", ".join(f"{k} {_fmt(v)}" for k, v in value.items())
                lines.append(f"- {key}: {detail}")
    return "\n".join(lines) + "\n"
