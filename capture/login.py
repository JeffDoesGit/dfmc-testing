"""Interactive login — capture a reusable dev-environment session.

Opens a real (headed) browser at the dev base URL, then waits for YOU to log in
by hand. Credentials are never touched by this script or stored anywhere except
Playwright's ``storage_state.json`` (cookies + localStorage), which is
gitignored. When you press Enter, the session is saved for headless replay by
``observe/run.py``.

    python -m capture.login              # run from the repo root
    python capture/login.py

Requires: playwright + browsers (``pip install -r requirements.txt`` then
``playwright install chromium``).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow ``python capture/login.py`` (not just ``-m capture.login``) by putting
# the repo root on sys.path so ``harness_env`` imports cleanly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import harness_env  # noqa: E402


def main() -> int:
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
    out_path = harness_env.storage_state_path()

    print(f"Opening {url}")
    print("Log in by hand in the browser window, reach the game, then come back")
    print("here and press Enter to save the session.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")

        try:
            input("\nPress Enter once you are logged in and in the game... ")
        except (EOFError, KeyboardInterrupt):
            print("\nAborted — nothing saved.", file=sys.stderr)
            browser.close()
            return 1

        context.storage_state(path=str(out_path))
        browser.close()

    print(f"Saved session to {out_path}")
    print("This file is gitignored. Do not commit it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
