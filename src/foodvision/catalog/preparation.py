"""Preparation state parsed from FDC food descriptions (whole-word matches only).

FDC encodes state in the name, e.g. "Rice, white, long-grain, regular, raw, enriched" (dry
rice is "raw"/"uncooked"/"dry") vs "..., cooked". Whole words matter: "precooked or instant,
dry" is a dry product, so "precooked" is not "cooked".
"""

import re
from enum import StrEnum


class PreparationState(StrEnum):
    UNCOOKED = "uncooked"  # raw, dry, uncooked, unprepared
    COOKED = "cooked"
    NOT_STATED = "not_stated"
    AMBIGUOUS = "ambiguous"  # both kinds of words present


UNCOOKED_WORDS = frozenset({"raw", "uncooked", "dry", "unprepared"})
COOKED_WORDS = frozenset(
    {
        "cooked",
        "prepared",
        "boiled",
        "roasted",
        "braised",
        "broiled",
        "fried",
        "baked",
        "grilled",
        "steamed",
        "stewed",
        "simmered",
        "microwaved",
        "sauteed",
        "poached",
        "toasted",
        "scrambled",
        "rotisserie",
        "pan-fried",
        "deep-fried",
    }
)
_WORD = re.compile(r"[a-z]+(?:-[a-z]+)*")


def words(description: str) -> set[str]:
    return set(_WORD.findall(description.lower()))


def preparation_state(description: str) -> PreparationState:
    found = words(description)
    uncooked, cooked = bool(found & UNCOOKED_WORDS), bool(found & COOKED_WORDS)
    if uncooked and cooked:
        return PreparationState.AMBIGUOUS
    if cooked:
        return PreparationState.COOKED
    if uncooked:
        return PreparationState.UNCOOKED
    return PreparationState.NOT_STATED


def preparation_text(description: str) -> str | None:
    """The comma-separated description parts that state the preparation, if any."""
    parts = [p.strip() for p in description.split(",")]
    hits = [p for p in parts if words(p) & (UNCOOKED_WORDS | COOKED_WORDS)]
    return ", ".join(hits) or None
