"""Test 5: table-driven identity matching. First-initial matching let
'Jalen Williams' pass for 'Jaylen Williams'."""

import pytest

from tools.bbref import _is_same_player, _url_matches_requested_player


@pytest.mark.parametrize(
    ("requested", "found", "expected"),
    [
        ("Jordan Pope", "Jordan Pope", True),
        ("jordan pope", "Jordan  Pope", True),
        ("Jalen Williams", "Jaylen Williams", False),
        ("Marcus Johnson", "Michael Johnson", False),
        ("Cam Boozer", "Cameron Boozer", True),  # nickname-style prefix
        ("Cooper Flagg", "Cooper Flagg", True),
        ("Cooper Flagg", "Cooper Flag", False),  # different last name
        ("Jordan Pope", "", False),
        ("", "Jordan Pope", False),
    ],
)
def test_is_same_player(requested, found, expected):
    assert _is_same_player(requested, found) is expected


@pytest.mark.parametrize(
    ("url", "requested", "expected"),
    [
        # Sports Reference CBB slug style
        ("https://www.sports-reference.com/cbb/players/jordan-pope-1.html", "Jordan Pope", True),
        ("https://www.sports-reference.com/cbb/players/jaylen-williams-1.html", "Jalen Williams", False),
        # Basketball Reference slug style: last[:5] + first[:2]
        ("https://www.basketball-reference.com/players/f/flaggco01.html", "Cooper Flagg", True),
        ("https://www.basketball-reference.com/players/p/popejo01.html", "Jordan Pope", True),
        ("https://www.basketball-reference.com/players/w/willija06.html", "Jalen Williams", True),
        # The old check passed when the last name appeared ANYWHERE in the URL.
        ("https://evil.com/search?q=pope", "Jordan Pope", False),
        ("https://www.sports-reference.com/cbb/players/other-guy-1.html?ref=jordan-pope", "Jordan Pope", False),
        ("https://www.sports-reference.com/cbb/players/", "Jordan Pope", False),
    ],
)
def test_url_matches_requested_player(url, requested, expected):
    assert _url_matches_requested_player(url, requested) is expected
