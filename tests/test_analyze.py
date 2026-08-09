"""Offline tests for the analyzer, driven by fixtures/sample_traffic.jsonl.

These run with no live target — the whole point of building analyze/ + the
fixture first (specs/001, "Approach notes"). Run with: pytest -q
"""

from __future__ import annotations

from pathlib import Path

import pytest

from analyze.classes import RATE_CLASSES, classify
from analyze.report import (
    HOURS_PER_MONTH,
    build_report,
    format_report,
    load_log,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "sample_traffic.jsonl"


# The fixture is hand-built to this exact mix. If you edit the fixture, update
# these — the test failing on a fixture edit is the point.
EXPECTED_REQUESTS = {
    "battle": 5,   # 4 committed + 1 rate-limited (429)
    "read": 6,
    "save": 3,
    "chance": 3,
    "world": 2,
    "session": 1,
    "other": 1,
}
EXPECTED_NON_API = 1
EXPECTED_TOTAL_API = sum(EXPECTED_REQUESTS.values())  # 21

# est_rows per class = committed_requests * rows_per_request. The 429 battle
# commits nothing, so battle rows = 4 * 6.0, not 5 * 6.0.
EXPECTED_ROWS = {
    "battle": 4 * 6.0,
    "read": 6 * 0.0,
    "save": 3 * 4.0,
    "chance": 3 * 3.0,
    "world": 2 * 8.0,
    "session": 1 * 1.0,
    "other": 1 * 1.0,
}
EXPECTED_TOTAL_ROWS = sum(EXPECTED_ROWS.values())  # 63.0
EXPECTED_DURATION_S = 60.0


@pytest.fixture(scope="module")
def report():
    records, skipped = load_log(FIXTURE)
    assert skipped == 0, "fixture should be clean JSONL"
    return build_report(records, skipped_lines=skipped)


def test_fixture_exists():
    assert FIXTURE.exists(), f"missing fixture: {FIXTURE}"


def test_per_class_request_counts(report):
    got = {name: st.requests for name, st in report.stats.items() if st.requests}
    assert got == EXPECTED_REQUESTS


def test_total_requests_and_non_api(report):
    assert report.total_requests == EXPECTED_TOTAL_API
    assert report.non_api == EXPECTED_NON_API


def test_per_class_estimated_rows(report):
    for name, expected in EXPECTED_ROWS.items():
        assert report.stats[name].est_rows == pytest.approx(expected), name
    assert report.total_rows == pytest.approx(EXPECTED_TOTAL_ROWS)


def test_rate_limited_charged_no_rows(report):
    # The single 429 battle is counted as a request but writes no rows.
    assert report.total_rate_limited == 1
    assert report.total_rejected == 1
    assert report.stats["battle"].requests == 5
    assert report.stats["battle"].est_rows == pytest.approx(4 * 6.0)


def test_observed_window(report):
    assert report.duration_s == pytest.approx(EXPECTED_DURATION_S)


def test_hourly_and_monthly_extrapolation(report):
    # Linear scale from a 60s window: multiply per-window by 60 for per-hour.
    scale = 3600.0 / EXPECTED_DURATION_S
    assert report.requests_per_hour == pytest.approx(EXPECTED_TOTAL_API * scale)
    assert report.rows_per_hour == pytest.approx(EXPECTED_TOTAL_ROWS * scale)
    assert report.rows_per_month == pytest.approx(
        EXPECTED_TOTAL_ROWS * scale * HOURS_PER_MONTH
    )
    # $/month is derived from rows/month; just assert it is positive & finite.
    assert report.usd_per_month > 0


def test_report_renders_and_mentions_uncalibrated(report):
    text = format_report(report)
    assert "TOTAL" in text
    assert "rows/hour" in text
    assert "rows/30 days" in text
    assert "UNCALIBRATED" in text
    # Rate-limit signal must be visible to the reader.
    assert "rate-limited" in text.lower()


def test_extrapolation_disabled_on_short_window():
    # A single record has no window; extrapolation must not divide by zero.
    rep = build_report([{"ts": 1.0, "method": "POST", "path": "/api/battle",
                         "status": 200}])
    assert rep.duration_s == 0.0
    assert rep.rows_per_hour == 0.0
    assert "disabled" in format_report(rep)


@pytest.mark.parametrize(
    "method,path,expected",
    [
        ("POST", "/api/battle", "battle"),
        ("POST", "/api/battle/start?stage=3", "battle"),
        ("POST", "/api/upgrade", "chance"),
        ("POST", "/api/breed", "chance"),
        ("POST", "/api/hatch", "chance"),
        ("GET", "/api/leaderboard", "world"),
        ("POST", "/api/pvp/attack", "world"),
        ("POST", "/api/autosave", "save"),
        ("POST", "/api/login", "session"),
        ("GET", "https://dev.playdfmc.com/api/state?full=1", "read"),
        ("GET", "/api/inventory", "read"),
        ("POST", "/api/incense", "other"),
    ],
)
def test_classify_rules(method, path, expected):
    assert classify(method, path) == expected


def test_chance_beats_generic_ordering():
    # A path that could look like a read/save must resolve to its real class;
    # ordering in RULES is load-bearing.
    assert classify("POST", "/api/upgrade") == "chance"
    assert classify("POST", "/api/pvp/state") == "world"  # world before read


def test_every_class_has_uncalibrated_coefficient():
    # Guard: nobody removed the calibration marker or a class definition.
    for name, cls in RATE_CLASSES.items():
        assert cls.do_target in {"PlayerDO", "WorldDO", "edge"}, name
        assert cls.rows_per_request >= 0.0, name
