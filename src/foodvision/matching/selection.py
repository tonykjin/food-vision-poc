"""Selection validation: a chosen food ID must be one the tools actually returned.

A JSON schema can only check that an ID is a string; membership in the retrieved
candidate set is checked here, server-side, against the real tool results (plan §9 B3).
"""

from collections.abc import Collection, Sequence

from foodvision.contracts.errors import ErrorCode
from foodvision.contracts.results import FoodSource, ResultItem

NO_MATCH = "no_match"
GROUNDED_SOURCES = (FoodSource.USDA, FoodSource.FATSECRET)


class InvalidSelectionError(ValueError):
    code = ErrorCode.INVALID_SELECTION


def validate_selection(selected: str, candidate_ids: Sequence[str]) -> str | None:
    """Return the selected ID, or None for an explicit no_match. Exact match only."""
    if selected == NO_MATCH:
        return None
    if selected not in candidate_ids:
        raise InvalidSelectionError(
            f"selected food ID {selected!r} is not among the "
            f"{len(candidate_ids)} retrieved candidates"
        )
    return selected


def validate_grounded_items(items: Sequence[ResultItem], returned_ids: Collection[str]) -> None:
    """Every database-grounded item must cite an ID that the tools returned in this scan."""
    for item in items:
        cited = item.food_id
        if item.food_source in GROUNDED_SOURCES and cited is not None and cited not in returned_ids:
            raise InvalidSelectionError(
                f"item {item.name!r} cites food ID {cited!r} not returned by tools"
            )
