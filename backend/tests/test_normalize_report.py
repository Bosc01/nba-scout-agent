"""Test 7: _normalize_report with empty input, with percentages already in
0-1 form, and with pts/fga/fta present to check the TS% derivation."""

from agents.scout import ScoutAgent


def _agent() -> ScoutAgent:
    return ScoutAgent()


def test_empty_raw_report_produces_null_defaults():
    report = _agent()._normalize_report({}, "Test Player", set())
    assert report["player_name"] == "Test Player"
    assert report["confidence"] == 0.0
    assert report["stats"]["pts"] is None
    assert report["advanced"]["ts_pct"] is None
    assert report["strengths"] == []
    assert report["sources"] == []
    assert report["season"] is None


def test_percentages_in_decimal_form_pass_through_unchanged():
    raw = {"stats": {"fg_pct": 0.468, "three_pct": 0.372, "ft_pct": 0.84}}
    report = _agent()._normalize_report(raw, "Test Player", set())
    assert report["stats"]["fg_pct"] == 0.468
    assert report["stats"]["three_pct"] == 0.372
    assert report["stats"]["ft_pct"] == 0.84


def test_ts_pct_derived_from_attempts():
    # TS% = PTS / (2 * (FGA + 0.44 * FTA)) = 13.1 / (2 * 11.732) = 0.558
    raw = {"stats": {"pts": 13.1, "fga": 10.5, "fta": 2.8}}
    report = _agent()._normalize_report(raw, "Test Player", set())
    assert report["advanced"]["ts_pct"] == 0.558


def test_search_extracted_ts_pct_wins_over_derivation():
    raw = {
        "stats": {"pts": 13.1, "fga": 10.5, "fta": 2.8},
        "advanced": {"ts_pct": 0.584},
    }
    report = _agent()._normalize_report(raw, "Test Player", set())
    assert report["advanced"]["ts_pct"] == 0.584


def test_ts_pct_not_derived_without_attempts():
    raw = {"stats": {"pts": 13.1}}
    report = _agent()._normalize_report(raw, "Test Player", set())
    assert report["advanced"]["ts_pct"] is None


def test_sources_filtered_by_hostname():
    raw = {"sources": ["https://evil.com/?ref=espn.com", "https://www.espn.com/nba/x"]}
    report = _agent()._normalize_report(raw, "Test Player", {"https://duckduckgo.com/y"})
    assert report["sources"] == ["https://www.espn.com/nba/x"]
