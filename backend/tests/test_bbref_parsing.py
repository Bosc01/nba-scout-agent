"""Tests 1-4: table extraction against real saved HTML, the renamed-table
parse-failure signal, the _to_int regression, and the ESPN table parser."""

from bs4 import BeautifulSoup

from tools.bbref import _extract_stats_from_table, _parse_espn_stats_tables, _to_int


def test_extract_stats_from_real_cbb_fixture(load_fixture):
    soup = BeautifulSoup(load_fixture("sr_cbb_jordan_pope.html"), "html.parser")
    stats, team, season = _extract_stats_from_table(soup, ["players_per_game"])
    assert stats is not None
    assert stats["pts"] == 13.1
    assert stats["reb"] == 2.1
    assert stats["ast"] == 1.9
    assert stats["fg_pct"] == 0.399
    assert stats["three_pct"] == 0.372
    assert stats["ft_pct"] == 0.840
    assert stats["fga"] == 10.5
    assert stats["fta"] == 2.8
    assert stats["games"] == 36
    assert stats["minutes"] == 29.1
    assert team == "Texas"
    assert season == "2025-26"


def test_extract_stats_from_comment_wrapped_table(load_fixture):
    soup = BeautifulSoup(load_fixture("sr_cbb_comment_wrapped.html"), "html.parser")
    stats, team, season = _extract_stats_from_table(soup, ["players_per_game"])
    assert stats is not None
    assert stats["pts"] == 13.1
    assert stats["games"] == 36
    assert season == "2025-26"


def test_renamed_table_is_a_distinguishable_parse_failure(load_fixture):
    """A renamed table id must NOT come back as all-None stats that read like
    'this player has no data'. It must be a parse failure the caller can
    surface as status=parse_failed."""
    soup = BeautifulSoup(load_fixture("sr_cbb_renamed_table.html"), "html.parser")
    stats, team, season = _extract_stats_from_table(soup, ["players_per_game"])
    assert stats is None
    assert team is None
    assert season is None


def test_to_int_regression():
    """_to_int's body was stranded as dead code after an unconditional return
    in another function, so games was silently null everywhere."""
    assert _to_int("82") == 82
    assert _to_int("82.0") == 82
    assert _to_int(None) is None
    assert _to_int("") is None
    assert _to_int("abc") is None


def test_espn_table_parser_alignment_and_pct_conversion(load_fixture):
    soup = BeautifulSoup(load_fixture("espn_stats_table.html"), "html.parser")
    stats = _parse_espn_stats_tables(soup)
    # The 2025-26 row is preferred; the mixed th+td header must be indexed as
    # one sequence so every value lands in the right column.
    assert stats["games"] == 36
    assert stats["minutes"] == 29.1
    assert stats["pts"] == 13.1
    assert stats["reb"] == 2.1
    assert stats["ast"] == 1.9
    # 46.8 → 0.468 conversion
    assert stats["fg_pct"] == 0.468
    assert stats["three_pct"] == 0.372
    assert stats["ft_pct"] == 0.84
