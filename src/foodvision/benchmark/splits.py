"""Deterministic, family-safe split assignment (plan §11).

- A whole family (all groups sharing `family_id`, or a lone group) always gets one split.
- Splits already assigned are never changed; a family that already has a split passes it on to
  its new groups.
- Unassigned families are ordered by a seeded hash, not by collection order, so nobody chooses
  which meals land in the held-out test set.
- Development is filled first, up to `development_target` groups (the first collection
  milestone). Later families are split between calibration and test by the same hash.
"""

import hashlib
from collections import defaultdict

from foodvision.benchmark.manifest import DEVELOPMENT_TARGET, Group, Split

DEFAULT_SEED = "pilot-v1"


def _unit_hash(seed: str, key: str) -> float:
    digest = hashlib.sha256(f"{seed}:{key}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def assign_splits(
    groups: list[Group], seed: str = DEFAULT_SEED, development_target: int = DEVELOPMENT_TARGET
) -> dict[str, Split]:
    """Return {group_id: split} for groups that need one. Assigned groups are left alone."""
    families: dict[str, list[Group]] = defaultdict(list)
    for g in groups:
        families[g.family_key].append(g)

    assigned: dict[str, Split] = {}
    dev_count = sum(1 for g in groups if g.split is Split.DEVELOPMENT)
    pending: list[tuple[float, str]] = []
    for key, members in families.items():
        existing = {g.split for g in members if g.split is not None}
        if len(existing) > 1:
            raise ValueError(f"family {key} already spans several splits; fix it by hand")
        if existing:
            (split,) = existing
            assigned.update({g.group_id: split for g in members if g.split is None})
            if split is Split.DEVELOPMENT:
                dev_count += sum(1 for g in members if g.split is None)
        else:
            pending.append((_unit_hash(seed, key), key))

    for _, key in sorted(pending):
        members = families[key]
        if dev_count < development_target:
            split = Split.DEVELOPMENT
            dev_count += len(members)
        else:
            split = Split.CALIBRATION if _unit_hash(seed + ":holdout", key) < 0.5 else Split.TEST
        assigned.update({g.group_id: split for g in members})
    return assigned
