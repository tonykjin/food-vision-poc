"""Manifest validation and collection progress (POC-12).

Errors block loading and evaluation. Warnings are listed as human work. Synthetic groups are
validated like real ones but never counted as collected samples.
"""

import hashlib
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from foodvision.benchmark.manifest import (
    DEVELOPMENT_TARGET,
    Category,
    ExpectedOutcome,
    Grade,
    Group,
    Measurement,
    SourceType,
    Split,
    reference_totals,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    progress: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _git_ignored(path: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "check-ignore", "-q", str(path)],
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def check_location(manifest: Path, groups: list[Group], report: Report) -> None:
    """Real reference labels must never sit in a tracked part of the repository."""
    if not any(not g.is_synthetic for g in groups):
        return
    resolved = manifest.resolve()
    if resolved.is_relative_to(REPO_ROOT) and not _git_ignored(resolved):
        report.errors.append(
            f"{manifest}: real reference data inside the repository and not git-ignored. "
            "Move it to the private benchmark directory outside Git."
        )


def _grade_errors(group: Group) -> list[str]:
    """A claimed grade must be supported by how the reference was measured and sourced."""
    parts = group.recipe.ingredients if group.recipe else group.components
    measurements = {c.measurement for c in parts}
    sources = {c.values.source for c in parts if c.values is not None}
    problems = []
    if group.quality_grade is not Grade.C and Measurement.ESTIMATED in measurements:
        problems.append("estimated grams allow grade C only")
    if group.quality_grade is Grade.A:
        if measurements - {Measurement.WEIGHED}:
            problems.append("grade A needs every component weighed")
        if sources & {SourceType.LABEL, SourceType.MENU}:
            problems.append("label/menu values are grade B, not A")
    return problems


def check_groups(groups: list[Group], data_dir: Path | None, report: Report) -> None:
    by_id = Counter(g.group_id for g in groups)
    for group_id, count in by_id.items():
        if count > 1:
            report.errors.append(f"group {group_id}: defined {count} times")

    family_splits: dict[str, set[Split]] = defaultdict(set)
    photo_owner: dict[str, str] = {}
    photo_ids: Counter[str] = Counter()
    for g in groups:
        where = f"group {g.group_id}"
        if g.split is not None:
            family_splits[g.family_key].add(g.split)
        for photo in g.photos:
            photo_ids[photo.photo_id] += 1
            other = photo_owner.setdefault(photo.sha256, g.group_id)
            if other != g.group_id:
                report.errors.append(
                    f"{where}: photo {photo.photo_id} is the same image as one in group {other} "
                    "(split leakage)"
                )
            elif photo_ids[photo.photo_id] == 1 and data_dir is not None:
                _check_photo_file(where, photo.file, photo.sha256, data_dir, report)
        if g.expected_outcome is ExpectedOutcome.ESTIMATE:
            for problem in _grade_errors(g):
                report.errors.append(f"{where}: grade {g.quality_grade}: {problem}")
            totals = reference_totals(g)
            for problem in totals.errors:
                report.errors.append(f"{where}: {problem}")
            if totals.missing_components:
                report.warnings.append(
                    f"{where}: no source values yet for {', '.join(totals.missing_components)}"
                )
            elif not totals.errors and totals.nutrients.missing():
                report.warnings.append(
                    f"{where}: reference unknown for {', '.join(totals.nutrients.missing())} "
                    "(not scorable for those nutrients)"
                )
        if g.split is None:
            report.warnings.append(f"{where}: split not assigned (run assign-splits)")
        if g.review.status == "draft":
            report.warnings.append(f"{where}: not reviewed yet")
        elif len(g.review.reviewers) == 1:
            report.warnings.append(f"{where}: single reviewer (no second review available)")
        if g.quality_grade is Grade.C:
            report.warnings.append(f"{where}: grade C, excluded from primary numeric accuracy")
    for photo_id, count in photo_ids.items():
        if count > 1:
            report.errors.append(f"photo id {photo_id}: used {count} times")
    for family, splits in family_splits.items():
        if len(splits) > 1:
            names = ", ".join(sorted(s.value for s in splits))
            report.errors.append(f"family {family}: groups in several splits ({names}): leakage")


def _check_photo_file(where: str, file: str, sha256: str, data_dir: Path, report: Report) -> None:
    root = data_dir.resolve()
    path = (root / file).resolve()
    if not path.is_relative_to(root):
        report.errors.append(f"{where}: photo path {file} escapes the data directory")
    elif not path.is_file():
        report.errors.append(f"{where}: photo file missing: {file}")
    elif hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
        report.errors.append(f"{where}: photo {file} does not match its sha256")


def is_collected(group: Group) -> bool:
    """A real, reviewed group with a grade A/B reference (or a reviewed abstain case)."""
    return (
        not group.is_synthetic
        and group.review.status == "reviewed"
        and (group.quality_grade in (Grade.A, Grade.B) or group.expected_outcome == "abstain")
    )


def progress(groups: list[Group], report: Report) -> None:
    real = [g for g in groups if not g.is_synthetic]
    synthetic = len(groups) - len(real)
    collected = [g for g in real if is_collected(g)]
    dev = [g for g in collected if g.split is Split.DEVELOPMENT]
    report.progress.append(
        f"Real groups: {len(real)} ({len(collected)} reviewed with grade A/B); "
        f"synthetic groups (never counted): {synthetic}"
    )
    report.progress.append(
        f"Development milestone: {len(dev)}/{DEVELOPMENT_TARGET} reviewed real groups"
    )
    for split in Split:
        counts = Counter(g.category for g in collected if g.split is split)
        detail = ", ".join(f"{c.value} {counts[c]}" for c in Category if counts[c])
        report.progress.append(f"  {split.value}: {sum(counts.values())} ({detail or 'none'})")
    single = sum(1 for g in collected if len(g.review.reviewers) == 1)
    if single:
        report.progress.append(f"Single-reviewer groups: {single} of {len(collected)}")
    if len(dev) < DEVELOPMENT_TARGET:
        report.progress.append(
            f"Human work: collect and review {DEVELOPMENT_TARGET - len(dev)} more real "
            "development groups (benchmarks/protocol.md). No accuracy study is ready until then."
        )


def manifest_sha256(groups: list[Group]) -> str:
    """Order-independent hash of the parsed manifest, for recording which version was used."""
    canonical = sorted(g.model_dump_json() for g in groups)
    return hashlib.sha256("\n".join(canonical).encode("utf-8")).hexdigest()
