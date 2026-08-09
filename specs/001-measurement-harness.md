# Spec 001 — Cost measurement harness

## Goal
Measure the request and estimated-row cost of one account under maximal
legitimate play, so the breaker ceiling can be set from data instead of the
stale cost tables.

## Deliverables
1. `capture/login.py` — opens a browser, lets the user log into the dev
   environment by hand, saves `storage_state.json`.
2. `observe/run.py` — loads `storage_state.json`, opens the game, enables
   autoplay (and incense if available), intercepts every network request, and
   appends one JSONL line per `/api/*` call:
   `{ts, method, path, status, req_bytes, resp_bytes}`. Runs for a configurable
   duration.
3. `analyze/report.py` — reads a JSONL log, classifies each request by rate
   class (rules in `analyze/classes.py`), and prints a table: per class —
   request count, estimated rows, % of total; plus hourly and 30-day
   extrapolation for one account.
4. `fixtures/sample_traffic.jsonl` — a small hand-written sample so
   `analyze/report.py` is testable with no live target.
5. `tests/test_analyze.py` — runs the analyzer against the fixture and asserts
   the tally.

## Approach notes
- Rate-class rules and per-class row-cost coefficients start as best-guess
  constants in one file (`analyze/classes.py`), each marked `# UNCALIBRATED`.
  Calibration against the owner's usage-ledger export is a later spec.
- `observe/run.py` must NOT fabricate traffic — it observes what the real
  client does. Maximal play = autoplay + incense, not synthetic request spam.
- Build and test `analyze/` + `fixtures/` FIRST, offline. `capture/` and
  `observe/` are validated once dev creds exist.

## Acceptance (Gherkin)

    Scenario: analyzer tallies a known log
      Given fixtures/sample_traffic.jsonl with a known mix of requests
      When analyze/report.py runs against it
      Then it prints per-class request counts matching the fixture
      And it reports an hourly and 30-day per-account extrapolation

    Scenario: observer captures live traffic (requires dev session)
      Given a valid storage_state.json for the dev environment
      When observe/run.py runs for 2 minutes with autoplay on
      Then it produces a JSONL log with one line per /api/* request
      And analyze/report.py produces a report from that log

## Out of scope (later specs)
- Calibration against the usage ledger
- Account-creation-rate probe
- PvP / WorldDO load
- Anomaly false-positive review
