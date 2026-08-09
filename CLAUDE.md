# dfmc-testing — CLAUDE.md

## What this is
Black-box measurement and abuse-testing harness for DFMC / Herumon Tower
(playdfmc.com). This repo contains **no game code**. It drives the game's DEV
environment over HTTP / a real browser and measures cost and abuse surface, to
help the game's solo developer harden the backend before it scales. This is
authorized defensive security work, coordinated with the owner.

## Prime objective
The game runs on Cloudflare Workers + Durable Objects, which have **no hard
spend cap** — cost is unbounded by design and must be made to fail closed.
`DO rows written` is ~82% of the bill. The first question this repo answers:

> What does one account cost, per hour, under maximal legitimate play at the
> current rate caps?

Everything else (account-creation rate, PvP / WorldDO load, anomaly
false-positive rate) builds on that number.

## Target architecture (what we measure against)
- Edge Worker validates session + rate limits BEFORE any Durable Object wakes.
- Two DO classes: **PlayerDO** (one per player) and **WorldDO** (a single
  shared object — leaderboards, PvP, admin; ~1000 req/s ceiling, unfenced).
- ~14 client routes under `/api/*`. Each has a rate class. Cost is dominated by
  rows written per request.
- Current caps (build 0.44): battle limit **4/min** (was 1/min); separate
  allowance classes for saves, reads, and chance-rolls (upgrade/breed/hatch).
- Owner's own prior measurement: ~$0.44/player/month, ~336 rows/player-hour —
  but that predates the cap increases and PvP, so re-measuring is the point.

## Rules of engagement
- Test against the **DEV environment only**. Never run load or abuse patterns
  against production or against another player's account.
- Measurement first (observe real client traffic). Abuse probes second, and
  only against our own test accounts on dev.
- Every probe logs what it did, what it cost, and what stopped it.

## Stack
- Python 3.11+, Playwright (browser capture + request interception),
  httpx (direct API probes), pytest.
- Session auth via Playwright `storage_state`: log in once interactively,
  replay headless. Never hardcode credentials.

## Structure
- `capture/` — interactive login; saves `storage_state.json` (gitignored)
- `observe/` — launch logged-in session, run autoplay, log every `/api/*`
  request to JSONL
- `analyze/` — classify requests by rate class, tally requests + estimated
  rows per class, extrapolate hourly / monthly
- `probes/` — targeted abuse tests (account-creation rate, oversized bodies,
  unfenced WorldDO paths) — later phases
- `fixtures/` — recorded sample traffic for offline testing
- `specs/` — task specs, one per file

## Conventions
- Never commit `storage_state.json`, tokens, or any real credentials. Put the
  dev base URL in a gitignored `.env`.
- Each probe is standalone and re-runnable. Log to JSONL; analyze separately.
- State lives on disk, not in a session.
