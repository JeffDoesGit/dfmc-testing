"""Classify a captured /api/* JSONL log and report per-account cost.

Usage:
    python -m analyze.report <log.jsonl>
    python analyze/report.py fixtures/sample_traffic.jsonl

Input is one JSON object per line, as written by ``observe/run.py``:
    {"ts": <epoch seconds>, "method": "POST", "path": "/api/battle",
     "status": 200, "req_bytes": 123, "resp_bytes": 456}

Output is a per-class table (requests, estimated DO rows, share of each) plus an
hourly and 30-day extrapolation for a single account. Row counts lean on the
UNCALIBRATED coefficients in ``analyze/classes.py`` — the numbers are only as
good as those guesses, which is the whole reason this measurement exists.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from analyze.classes import (
    RATE_CLASSES,
    USD_PER_MILLION_ROWS,
    classify,
)

HOURS_PER_MONTH = 24 * 30  # 30-day month, matches CLAUDE.md's "30-day" ask.


@dataclass
class ClassStat:
    """Running tally for one rate class.

    ``requests`` counts every request seen for the class; ``est_rows`` only
    accrues for requests that plausibly reached a Durable Object (see
    ``_committed`` — a 429/4xx/5xx is rejected at the edge and writes nothing).
    ``rejected`` and ``rate_limited`` record what stopped, which is the
    "what stopped it" signal the rules of engagement ask every probe to log.
    """

    name: str
    requests: int = 0
    est_rows: float = 0.0
    rejected: int = 0
    rate_limited: int = 0
    req_bytes: int = 0
    resp_bytes: int = 0


@dataclass
class Report:
    """Everything ``format_report`` needs to render."""

    stats: dict[str, ClassStat]
    total_requests: int
    total_rows: float
    duration_s: float
    skipped_lines: int = 0
    non_api: int = 0
    total_rejected: int = 0
    total_rate_limited: int = 0
    paths_by_class: dict[str, set[str]] = field(default_factory=dict)

    # --- extrapolation (per single account) ---------------------------------
    @property
    def requests_per_hour(self) -> float:
        return _per_hour(self.total_requests, self.duration_s)

    @property
    def rows_per_hour(self) -> float:
        return _per_hour(self.total_rows, self.duration_s)

    @property
    def rows_per_month(self) -> float:
        return self.rows_per_hour * HOURS_PER_MONTH

    @property
    def usd_per_month(self) -> float:
        return self.rows_per_month / 1_000_000 * USD_PER_MILLION_ROWS


def _per_hour(count: float, duration_s: float) -> float:
    """Scale a count observed over ``duration_s`` to a per-hour rate.

    A zero/negative window (single sample, or unusable timestamps) can't be
    extrapolated, so return 0.0 rather than dividing by zero — the report notes
    the window separately.
    """
    if duration_s <= 0:
        return 0.0
    return count / duration_s * 3600.0


def load_log(path: str | Path) -> tuple[list[dict], int]:
    """Load a JSONL log. Returns (records, skipped_line_count).

    Blank lines and lines that don't parse as a JSON object are skipped and
    counted rather than fatal — a partially-written live capture should still
    analyze.
    """
    records: list[dict] = []
    skipped = 0
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if isinstance(obj, dict):
            records.append(obj)
        else:
            skipped += 1
    return records, skipped


def _committed(status: object) -> bool:
    """True if a request with this status plausibly committed DO rows.

    Anything the edge rejects (429 rate-limit, other 4xx) or that errors before
    committing (5xx) is assumed to write nothing. A missing/garbage status is
    treated as committed so we don't silently drop cost from a sloppy log.
    """
    if not isinstance(status, (int, float)):
        return True
    return int(status) < 400


def _duration_seconds(records: list[dict]) -> float:
    ts = [r["ts"] for r in records if isinstance(r.get("ts"), (int, float))]
    if len(ts) < 2:
        return 0.0
    return float(max(ts) - min(ts))


def build_report(records: list[dict], skipped_lines: int = 0) -> Report:
    """Classify records and tally per class.

    Only ``/api/*`` requests are counted toward cost; anything else is tallied
    separately as ``non_api`` so the report can show it was seen and ignored.
    """
    stats = {name: ClassStat(name=name) for name in RATE_CLASSES}
    paths_by_class: dict[str, set[str]] = {name: set() for name in RATE_CLASSES}
    non_api = 0

    for r in records:
        path = str(r.get("path", ""))
        if "/api/" not in path:
            non_api += 1
            continue
        method = str(r.get("method", ""))
        status = r.get("status")
        cls_name = classify(method, path)
        cls = RATE_CLASSES[cls_name]
        st = stats[cls_name]
        st.requests += 1
        if _committed(status):
            st.est_rows += cls.rows_per_request
        else:
            st.rejected += 1
            if isinstance(status, (int, float)) and int(status) == 429:
                st.rate_limited += 1
        st.req_bytes += int(r.get("req_bytes", 0) or 0)
        st.resp_bytes += int(r.get("resp_bytes", 0) or 0)
        paths_by_class[cls_name].add(_norm_path(path))

    total_requests = sum(s.requests for s in stats.values())
    total_rows = sum(s.est_rows for s in stats.values())
    return Report(
        stats=stats,
        total_requests=total_requests,
        total_rows=total_rows,
        duration_s=_duration_seconds(records),
        skipped_lines=skipped_lines,
        non_api=non_api,
        total_rejected=sum(s.rejected for s in stats.values()),
        total_rate_limited=sum(s.rate_limited for s in stats.values()),
        paths_by_class=paths_by_class,
    )


def _norm_path(path: str) -> str:
    """Strip host and query so distinct example paths read cleanly."""
    p = path
    if "://" in p:
        p = p.split("://", 1)[1]
        p = "/" + p.split("/", 1)[1] if "/" in p else p
    return p.split("?", 1)[0]


def _pct(part: float, whole: float) -> float:
    return (part / whole * 100.0) if whole else 0.0


def format_report(report: Report) -> str:
    """Render a Report as a plain-text table + extrapolation block."""
    lines: list[str] = []
    lines.append("DFMC cost measurement — one account, observed window")
    lines.append("=" * 68)

    if report.duration_s > 0:
        lines.append(
            f"Observed window: {report.duration_s:,.1f}s "
            f"({report.duration_s / 60:.1f} min), "
            f"{report.total_requests:,} /api requests"
        )
    else:
        lines.append(
            f"Observed window: unknown (need >=2 timestamps); "
            f"{report.total_requests:,} /api requests — extrapolation disabled"
        )
    lines.append("")

    header = f"{'class':<9} {'reqs':>6} {'req%':>6} {'est_rows':>9} {'rows%':>6}  target"
    lines.append(header)
    lines.append("-" * len(header))

    # Sort by estimated rows desc — the cost story, biggest first.
    ordered = sorted(
        report.stats.values(), key=lambda s: s.est_rows, reverse=True
    )
    for s in ordered:
        cls = RATE_CLASSES[s.name]
        cap = f"{cls.cap_per_min}/min" if cls.cap_per_min else "unfenced"
        lines.append(
            f"{s.name:<9} {s.requests:>6} "
            f"{_pct(s.requests, report.total_requests):>5.1f}% "
            f"{s.est_rows:>9,.0f} "
            f"{_pct(s.est_rows, report.total_rows):>5.1f}% "
            f" {cls.do_target} ({cap})"
        )
    lines.append("-" * len(header))
    lines.append(
        f"{'TOTAL':<9} {report.total_requests:>6} {'100.0%':>6} "
        f"{report.total_rows:>9,.0f} {'100.0%':>6}"
    )
    lines.append("")

    # Extrapolation.
    lines.append("Per-account extrapolation (linear, from observed window):")
    if report.duration_s > 0:
        lines.append(f"  requests/hour : {report.requests_per_hour:>12,.0f}")
        lines.append(f"  rows/hour     : {report.rows_per_hour:>12,.0f}")
        lines.append(f"  rows/30 days  : {report.rows_per_month:>12,.0f}")
        lines.append(
            f"  $/30 days     : {report.usd_per_month:>12,.2f}  "
            f"(@ ${USD_PER_MILLION_ROWS:.2f}/M rows, UNCALIBRATED)"
        )
        lines.append("")
        lines.append(
            "  Anchor: owner's pre-cap/pre-PvP figure was ~336 rows/player-hour"
        )
    else:
        lines.append("  (disabled: window too short to extrapolate)")
    lines.append("")

    # Footnotes.
    note = []
    if report.total_rate_limited:
        note.append(
            f"{report.total_rate_limited} rate-limited (429), 0 rows charged"
        )
    other_rejected = report.total_rejected - report.total_rate_limited
    if other_rejected:
        note.append(f"{other_rejected} other rejected (4xx/5xx), 0 rows charged")
    if report.non_api:
        note.append(f"{report.non_api} non-/api requests ignored")
    if report.skipped_lines:
        note.append(f"{report.skipped_lines} unparseable lines skipped")
    if note:
        lines.append("Notes: " + "; ".join(note) + ".")
    lines.append(
        "Row costs are UNCALIBRATED estimates (analyze/classes.py); "
        "calibration is a later spec."
    )
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        prog = "analyze.report"
        print(f"usage: python -m {prog} <log.jsonl>", file=sys.stderr)
        return 2
    path = argv[0]
    if not Path(path).exists():
        print(f"error: no such log: {path}", file=sys.stderr)
        return 1
    records, skipped = load_log(path)
    report = build_report(records, skipped_lines=skipped)
    print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
