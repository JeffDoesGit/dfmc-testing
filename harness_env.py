"""Tiny .env loader and shared config for the live-capture scripts.

Deliberately dependency-free (no python-dotenv): the harness must run with only
the stdlib for anything offline, and capture/observe already pull in Playwright.
Config precedence is: real environment variables first, then ``.env``, then the
documented defaults.

Secrets never live here. The dev base URL and the storage-state path come from a
gitignored ``.env`` (see ``.env.example``); credentials are entered by hand in
the browser during ``capture/login.py`` and persisted only to
``storage_state.json`` (also gitignored).
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

DEFAULTS = {
    "DFMC_BASE_URL": "https://dev.playdfmc.com",
    "DFMC_STORAGE_STATE": "storage_state.json",
}


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            values[key] = val
    return values


def get(key: str) -> str:
    """Resolve one config key: real env > .env file > DEFAULTS."""
    if key in os.environ and os.environ[key] != "":
        return os.environ[key]
    file_values = _parse_env_file(REPO_ROOT / ".env")
    if key in file_values:
        return file_values[key]
    if key in DEFAULTS:
        return DEFAULTS[key]
    raise KeyError(f"no config for {key} (set it in the environment or .env)")


def base_url() -> str:
    return get("DFMC_BASE_URL").rstrip("/")


def storage_state_path() -> Path:
    p = Path(get("DFMC_STORAGE_STATE"))
    return p if p.is_absolute() else REPO_ROOT / p


def assert_not_production(url: str) -> None:
    """Fail loud if the configured target looks like production.

    Cheap guardrail for the "DEV environment only" rule of engagement. It is a
    heuristic, not a guarantee — it only blocks the obvious foot-guns.
    """
    lowered = url.lower()
    looks_dev = any(m in lowered for m in ("dev", "staging", "localhost", "127.0.0.1"))
    if not looks_dev:
        raise SystemExit(
            f"refusing to run against {url!r}: it does not look like a dev/staging "
            "target. Set DFMC_BASE_URL to the dev environment (see CLAUDE.md, "
            "'Rules of engagement'). Override only if you are certain."
        )
