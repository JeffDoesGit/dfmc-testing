"""Observe live client traffic and log every /api/* request to JSONL.

Loads the session captured by ``capture/login.py``, opens the game headless,
tries to switch on the client's own autoplay (and incense, if present), and
records one JSONL line per ``/api/*`` request the *real client* makes:

    {"ts", "method", "path", "status", "req_bytes", "resp_bytes"}

It does NOT fabricate traffic (specs/001, "Approach notes"): maximal play means
autoplay + incense, driven by the game itself, not synthetic request spam. The
output feeds ``analyze/report.py`` unchanged.

    python -m observe.run --duration 120
    python observe/run.py --duration 120 --out observe/logs/run1.jsonl

Requires: playwright + browsers, and a valid ``storage_state.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

# Allow ``python observe/run.py`` as well as ``-m observe.run``.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import harness_env  # noqa: E402

# Best-effort ways to find and toggle the client's autoplay / incense controls.
# These are heuristics — the game UI is the source of truth. Override with
# --autoplay-selector / --incense-selector when the real controls are known.
DEFAULT_AUTOPLAY_HINTS = ["Autoplay", "Auto Play", "Auto-play", "Auto", "AFK"]
DEFAULT_INCENSE_HINTS = ["Incense", "Use Incense", "Burn Incense"]


def _default_out_path() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return harness_env.REPO_ROOT / "observe" / "logs" / f"traffic-{stamp}.jsonl"


def _response_bytes(response) -> int:
    """Best-effort response size: content-length header, else body length."""
    cl = response.headers.get("content-length")
    if cl and cl.isdigit():
        return int(cl)
    try:
        return len(response.body())
    except Exception:
        return 0


def _request_bytes(request) -> int:
    """Best-effort request size: post-body length, else content-length header."""
    try:
        data = request.post_data
        if data:
            return len(data.encode("utf-8", errors="ignore"))
    except Exception:
        pass
    cl = request.headers.get("content-length")
    if cl and cl.isdigit():
        return int(cl)
    return 0


def _try_toggle(page, hints: list[str], selector: str | None, label: str) -> bool:
    """Best-effort: click a control identified by an explicit selector or by
    visible-text hints. Never raises; returns whether something was clicked."""
    candidates: list = []
    if selector:
        candidates.append(page.locator(selector))
    for hint in hints:
        # get_by_role button, then any element containing the text.
        candidates.append(page.get_by_role("button", name=hint, exact=False))
        candidates.append(page.get_by_text(hint, exact=False))
    for loc in candidates:
        try:
            if loc.count() > 0 and loc.first.is_visible():
                loc.first.click(timeout=1500)
                print(f"[observe] enabled {label} via {loc}")
                return True
        except Exception:
            continue
    print(f"[observe] {label} control not found (continuing without it)")
    return False


def run(
    duration_s: int,
    out_path: Path,
    headless: bool,
    autoplay_selector: str | None,
    incense_selector: str | None,
) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "playwright not installed. Run:\n"
            "  pip install -r requirements.txt\n"
            "  playwright install chromium",
            file=sys.stderr,
        )
        return 1

    url = harness_env.base_url()
    harness_env.assert_not_production(url)
    state_path = harness_env.storage_state_path()
    if not state_path.exists():
        print(
            f"no session at {state_path}. Run capture/login.py first.",
            file=sys.stderr,
        )
        return 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0

    with sync_playwright() as p, open(out_path, "w", encoding="utf-8") as fh:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(storage_state=str(state_path))
        page = context.new_page()

        def on_response(response) -> None:
            nonlocal count
            request = response.request
            path = urlparse(request.url).path
            if "/api/" not in path:
                return
            record = {
                "ts": round(time.time(), 3),
                "method": request.method,
                "path": path,
                "status": response.status,
                "req_bytes": _request_bytes(request),
                "resp_bytes": _response_bytes(response),
            }
            fh.write(json.dumps(record) + "\n")
            fh.flush()
            count += 1

        context.on("response", on_response)

        print(f"[observe] loading {url}")
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)  # let the game boot its own initial calls

        _try_toggle(page, DEFAULT_AUTOPLAY_HINTS, autoplay_selector, "autoplay")
        _try_toggle(page, DEFAULT_INCENSE_HINTS, incense_selector, "incense")

        print(f"[observe] observing for {duration_s}s -> {out_path}")
        deadline = time.time() + duration_s
        while time.time() < deadline:
            page.wait_for_timeout(1000)

        browser.close()

    print(f"[observe] wrote {count} /api requests to {out_path}")
    print(f"[observe] analyze with:  python -m analyze.report {out_path}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--duration", type=int, default=120,
        help="seconds to observe (default 120)",
    )
    ap.add_argument(
        "--out", type=Path, default=None,
        help="output JSONL path (default observe/logs/traffic-<ts>.jsonl)",
    )
    ap.add_argument(
        "--headed", action="store_true",
        help="run with a visible browser (default headless)",
    )
    ap.add_argument("--autoplay-selector", default=None,
                    help="explicit CSS/Playwright selector for the autoplay control")
    ap.add_argument("--incense-selector", default=None,
                    help="explicit CSS/Playwright selector for the incense control")
    args = ap.parse_args(argv)

    out_path = args.out or _default_out_path()
    return run(
        duration_s=args.duration,
        out_path=out_path,
        headless=not args.headed,
        autoplay_selector=args.autoplay_selector,
        incense_selector=args.incense_selector,
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
