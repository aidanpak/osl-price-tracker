# OSL Price Tracker

Tracks StubHub prices for Outside Lands Saturday (Aug 8, 2026), mainly the General Admission pass, so Aidan can buy near the bottom. This repo is public and contains no secrets.

Event: https://www.stubhub.com/outside-lands-music-festival-san-francisco-tickets-8-8-2026/event/159253857/?quantity=1

## Architecture

Two halves, split by what each environment is allowed to do:

1. **Scraper: GitHub Action** (`.github/workflows/price-check.yml`), cron every 3 hours at :00 UTC. Runs `check_price.py`, which opens the event page in a real browser via Browserbase (StubHub 403s plain HTTP, headless local browsers, and crawler APIs), parses the ticket-class cards (GA, VIP, GA+, Golden Gate Pass), appends one row to `history.jsonl`, and writes `verdict.json` (current prices + alert decision). The Action commits both, so **git history is the price database**. Browserbase credentials live in the repo's Actions secrets.
2. **Notifier: Claude Code cloud routine**, cron every 3 hours at :20 UTC. The Claude cloud sandbox egress-allowlists only GitHub and package hosts (Browserbase, Vercel, and every other host are blocked, which is why the scrape cannot happen there). It clones this repo read-only, reads `verdict.json`, and on a fresh alert creates a Gmail draft with the details plus a Google Calendar event 15 minutes out so a phone notification fires. Daily summary draft at the 15:20 UTC run (8:20am PT). Prices are per single ticket, fees included.

`api/price.js` is a stateless Vercel relay from an earlier iteration (caller supplies Browserbase creds as headers). The pipeline no longer uses it; kept because it costs nothing and may be handy for ad-hoc checks.

## Alert rules (in `check_price.py`)

- New all-time low for GA, or
- GA dropped 5% or more since the previous check.

## Running locally

```
pip install playwright   # client only, browser runs at Browserbase
set -a; source ~/.claude/browserbase.env; set +a
python3 check_price.py
```

## Knobs

- Scrape cadence: the workflow cron. Notify cadence: the routine at https://claude.ai/code/routines (keep it ~20 min after the workflow).
- Alert thresholds: the alert math in `check_price.py`.
- After Aug 8, 2026: delete the routine, disable the workflow, archive the repo.
