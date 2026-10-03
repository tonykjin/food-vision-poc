"""Invented food IDs are caught by selection validation, not by the JSON schema."""

import pytest

from foodvision.contracts.results import FoodSource, PortionMethod, ResultItem
from foodvision.matching.selection import (
    NO_MATCH,
    InvalidSelectionError,
    validate_grounded_items,
    validate_selection,
)

CANDIDATES = ["fdc:168878", "fdc:169704", "fdc:2512381"]


def test_selected_candidate_is_accepted():
    assert validate_selection("fdc:169704", CANDIDATES) == "fdc:169704"


def test_no_match_is_explicit_none():
    assert validate_selection(NO_MATCH, CANDIDATES) is None


@pytest.mark.parametrize("invented", ["fdc:999999", "FDC:169704", " fdc:169704", "169704", ""])
def test_ids_outside_candidates_rejected(invented):
    with pytest.raises(InvalidSelectionError):
        validate_selection(invented, CANDIDATES)


def test_any_id_rejected_when_no_candidates():
    with pytest.raises(InvalidSelectionError):
        validate_selection("fdc:168878", [])


def grounded(food_id):
    return ResultItem(
        name="rice",
        resolved=True,
        portion_g=100,
        portion_method=PortionMethod.IMAGE_ESTIMATED,
        food_source=FoodSource.USDA,
        food_id=food_id,
    )


def test_schema_alone_accepts_an_invented_id():
    # The contract can only check shape; membership needs the tool results.
    assert grounded("fdc:invented").food_id == "fdc:invented"


def test_grounded_items_must_cite_returned_ids():
    validate_grounded_items([grounded("fdc:168878")], CANDIDATES)
    with pytest.raises(InvalidSelectionError, match="not returned"):
        validate_grounded_items([grounded("fdc:invented")], CANDIDATES)
