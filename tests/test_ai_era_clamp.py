"""Pre-AI git history must not pollute the AI activity surface.

The default collection window is "all", so git scans years of pre-AI commits;
those days are unioned into the durable activity ledger. They should stay in the
timeline (tagged preAi, shown separately) but never inflate the AI streak,
active-days, or date range. This guards that clamp (representation only — no
score reads the activity surface).
"""

from nextmillionai.build_profile import _is_active_day, _longest_streak, tag_ai_era


def _days():
    # Two pre-AI git-only days in 2013, then a 3-day AI run in 2026.
    return [
        {"date": "2013-11-08", "sessions": 0, "commits": 5, "tools": ["git"]},
        {"date": "2013-11-09", "sessions": 0, "commits": 2, "tools": ["git"]},
        {"date": "2026-06-10", "sessions": 2, "commits": 1, "tools": ["claude_code"]},
        {"date": "2026-06-11", "sessions": 1, "commits": 0, "tools": ["claude_code"]},
        {"date": "2026-06-12", "sessions": 1, "commits": 0, "tools": ["claude_code"]},
    ]


def test_pre_ai_days_are_tagged_and_excluded():
    days = _days()
    ai_era = tag_ai_era(days, "2026-06-10")
    # pre-AI days are tagged but still present in the full list
    assert days[0]["preAi"] is True and days[1]["preAi"] is True
    assert days[2]["preAi"] is False
    # the returned AI-era subset drops them
    assert [d["date"] for d in ai_era] == ["2026-06-10", "2026-06-11", "2026-06-12"]


def test_streak_and_active_days_use_ai_era_only():
    days = _days()
    ai_era = tag_ai_era(days, "2026-06-10")
    # streak over AI era is 3 consecutive days, NOT the 2013 git run
    assert _longest_streak(ai_era) == 3
    assert _longest_streak(days) == 3  # full list would also see the 3-run, but...
    # active-day count excludes pre-AI git days
    assert len([d for d in ai_era if _is_active_day(d)]) == 3
    assert len([d for d in days if _is_active_day(d)]) == 5  # the bug: 2 extra


def test_date_range_excludes_pre_ai():
    days = _days()
    ai_era = tag_ai_era(days, "2026-06-10")
    dates = [d["date"] for d in ai_era if d.get("date")]
    assert f"{dates[0]} to {dates[-1]}" == "2026-06-10 to 2026-06-12"  # not 2013→2026


def test_no_sessions_leaves_days_untagged():
    days = _days()
    ai_era = tag_ai_era(days, None)  # no AI session date
    assert ai_era == days  # nothing dropped
    assert all("preAi" not in d for d in days)
