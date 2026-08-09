"""Rate-class rules and per-class row-cost coefficients.

Every row-cost coefficient in this file is a BEST GUESS and is marked
``# UNCALIBRATED``. They exist so ``analyze/report.py`` can produce a shaped
answer today; they are NOT authoritative. Calibrating them against the owner's
usage-ledger export is a later spec (see specs/001, "Approach notes").

The prime objective (CLAUDE.md) is: what does one account cost per hour under
maximal legitimate play? "Cost" is dominated (~82%) by Durable Object rows
written, so every rate class carries an estimated ``rows_per_request`` and the
DO it targets (PlayerDO vs the single shared WorldDO).

Classification is rule-based: an ordered list of (method, path-regex) -> class.
The first matching rule wins; anything unmatched falls through to ``OTHER``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RateClass:
    """One rate/allowance class.

    Attributes:
        name: stable identifier, used as the tally key and in reports.
        rows_per_request: estimated DO rows WRITTEN per request. # UNCALIBRATED
        cap_per_min: client/edge rate cap in requests per minute for this class,
            or ``None`` if the class is unfenced / the cap is unknown.
        do_target: which object absorbs the write — "PlayerDO", "WorldDO", or
            "edge" (validated/served at the edge, no DO wake).
        note: human context for whoever reads the report.
    """

    name: str
    rows_per_request: float
    cap_per_min: int | None
    do_target: str
    note: str


# --- Rate classes ------------------------------------------------------------
# rows_per_request values below are all UNCALIBRATED best guesses. Rationale is
# in each note; the owner's prior figure of ~336 rows/player-hour (pre-cap,
# pre-PvP) is the sanity anchor we are trying to re-measure past.

BATTLE = RateClass(
    name="battle",
    rows_per_request=6.0,  # UNCALIBRATED: battle result + stats + drops + xp
    cap_per_min=4,  # build 0.44 raised this from 1/min to 4/min
    do_target="PlayerDO",
    note="Combat resolution. Cap raised 1->4/min in 0.44; the dominant "
    "write path under autoplay.",
)

SAVE = RateClass(
    name="save",
    rows_per_request=4.0,  # UNCALIBRATED: full player-state snapshot write
    cap_per_min=None,
    do_target="PlayerDO",
    note="Explicit state persistence (autosave / manual save).",
)

CHANCE = RateClass(
    name="chance",
    rows_per_request=3.0,  # UNCALIBRATED: roll outcome + inventory mutation
    cap_per_min=None,
    do_target="PlayerDO",
    note="Chance-rolls: upgrade / breed / hatch. Own allowance class.",
)

READ = RateClass(
    name="read",
    rows_per_request=0.0,  # UNCALIBRATED: reads shouldn't write rows
    cap_per_min=None,
    do_target="PlayerDO",
    note="State/inventory reads. Cost is read units, not rows — 0 rows here "
    "by assumption; revisit if reads touch a last-seen row.",
)

WORLD = RateClass(
    name="world",
    rows_per_request=8.0,  # UNCALIBRATED: shared leaderboard/PvP write, contended
    cap_per_min=None,  # ~1000 req/s ceiling, unfenced per CLAUDE.md
    do_target="WorldDO",
    note="Single shared WorldDO: leaderboard / PvP / admin. Unfenced; the "
    "abuse-surface headline for a later spec.",
)

SESSION = RateClass(
    name="session",
    rows_per_request=1.0,  # UNCALIBRATED: session/login touch
    cap_per_min=None,
    do_target="edge",
    note="Auth / session bootstrap. Validated at the edge before any DO wakes.",
)

OTHER = RateClass(
    name="other",
    rows_per_request=1.0,  # UNCALIBRATED: unknown route, assume one write
    cap_per_min=None,
    do_target="PlayerDO",
    note="Unmatched /api/* route. Conservative 1-row guess; if this class is "
    "non-trivial in a real log, add a rule for it.",
)

RATE_CLASSES: dict[str, RateClass] = {
    c.name: c
    for c in (BATTLE, SAVE, CHANCE, READ, WORLD, SESSION, OTHER)
}


# --- Classification rules ----------------------------------------------------
# Ordered (method_regex, path_regex, class_name). First match wins. method_regex
# of None matches any method. Paths are matched with re.search (case-insensitive)
# so a leading host or trailing query string does not need stripping first.

_Rule = tuple[re.Pattern[str] | None, re.Pattern[str], str]


def _rule(method: str | None, path: str, cls: RateClass) -> _Rule:
    m = re.compile(method, re.IGNORECASE) if method else None
    return (m, re.compile(path, re.IGNORECASE), cls.name)


RULES: list[_Rule] = [
    # Chance-rolls before generic writes: these are their own allowance class.
    _rule(None, r"/api/(upgrade|breed|hatch|roll|gacha)\b", CHANCE),
    # Battles.
    _rule(None, r"/api/(battle|fight|combat)\b", BATTLE),
    # Shared WorldDO surfaces: PvP, leaderboards, admin.
    _rule(None, r"/api/(pvp|arena|leaderboard|ranking|world|admin)\b", WORLD),
    # Explicit saves / autosave.
    _rule(None, r"/api/(save|autosave|persist|sync)\b", SAVE),
    # Auth / session.
    _rule(None, r"/api/(login|logout|session|auth|token)\b", SESSION),
    # Reads: explicit GET-style state/inventory fetches. Keep last among the
    # specific rules so a write path never gets miscounted as a read.
    _rule(None, r"/api/(state|inventory|profile|read|get|list|status)\b", READ),
]


def classify(method: str, path: str) -> str:
    """Return the rate-class name for one request.

    Only ``/api/*`` paths are meaningful here; a non-/api path still resolves
    (to OTHER) rather than raising, so callers can pass anything.
    """
    for method_re, path_re, cls_name in RULES:
        if method_re is not None and not method_re.fullmatch(method.strip()):
            continue
        if path_re.search(path):
            return cls_name
    return OTHER.name


# Cost coefficient tying rows -> dollars, for the monthly extrapolation.
# Cloudflare Durable Objects bill per row written; the exact SKU price is what
# the owner pays, so this is UNCALIBRATED until cross-checked against the bill.
USD_PER_MILLION_ROWS = 1.0  # UNCALIBRATED
