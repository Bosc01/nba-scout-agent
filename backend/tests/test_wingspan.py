"""Test 6: _parse_wingspan_from_text across all four accepted formats,
rejecting non-wingspan measurements and implausible values."""

import pytest

from tools.bbref import _parse_wingspan_from_text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # Format 1: feet'inches" wingspan
        ("He measured a 6'11\" wingspan at the combine", "6-11"),
        ("wingspan measured 7′0.5″ wingspan", "7-0.5"),
        # Format 2: X feet Y inches wingspan
        ("a wingspan of 7 feet 3 inches", "7-3"),
        # Format 3: total inches wingspan
        ("an 87 inches wingspan", "7-3"),
        ("an 87.5-inch wingspan", "7-3.5"),
        # Format 4: decimal feet after the word wingspan
        ("his wingspan is 7.25 feet", "7-3"),
    ],
)
def test_accepted_formats(text, expected):
    assert _parse_wingspan_from_text(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "recorded a 6'11 vertical at the combine",  # not a wingspan
        "posted a 38 inch vertical leap",
        "a 15'2\" wingspan",  # feet out of range
        "a 150 inches wingspan",  # total inches out of range
        "a 4'2\" wingspan",  # too short to be real
        "no measurements were taken",
    ],
)
def test_rejected_inputs(text):
    assert _parse_wingspan_from_text(text) is None
