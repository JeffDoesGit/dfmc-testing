# dfmc-testing

Black-box measurement + abuse-testing harness for DFMC / Herumon Tower
(playdfmc.com). No game code lives here — this drives the game's **dev**
environment over a real browser and measures cost and abuse surface. See
`CLAUDE.md` for scope and rules of engagement, and `specs/` for task specs.

## Spec 001 — cost measurement harness

Answers: *what does one account cost, per hour, under maximal legitimate play?*
Cost is dominated (~82%) by Durable Object rows written.

### Layout
- `analyze/classes.py` — rate-class rules + per-class row-cost coefficients
  (all `# UNCALIBRATED` best guesses; calibration is a later spec).
- `analyze/report.py` — reads a JSONL traffic log, classifies each request,
  prints a per-class table + hourly / 30-day per-account extrapolation.
- `fixtures/sample_traffic.jsonl` — hand-built sample so the analyzer is
  testable with no live target.
- `tests/test_analyze.py` — asserts the analyzer's tally against the fixture.
- `capture/login.py` — interactive login; saves `storage_state.json`.
- `observe/run.py` — replays the session, enables the client's autoplay/incense,
  logs one JSONL line per `/api/*` request.

### Run the offline analyzer (no dev creds needed)

    pip install -r requirements.txt
    python -m pytest -q
    python -m analyze.report fixtures/sample_traffic.jsonl

### Capture live traffic (needs a dev session)

    cp .env.example .env            # edit DFMC_BASE_URL to the dev env
    playwright install chromium
    python -m capture.login         # log in by hand; saves storage_state.json
    python -m observe.run --duration 120
    python -m analyze.report observe/logs/traffic-*.jsonl

`storage_state.json`, `.env`, and `observe/logs/` are gitignored — never commit
sessions, tokens, or captured account traffic. Dev environment only.
