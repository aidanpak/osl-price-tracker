# OSL Price Tracker

Tracks StubHub prices for Outside Lands Saturday (Aug 8, 2026), mainly the General Admission pass, so Aidan can buy near the bottom.

Event: https://www.stubhub.com/outside-lands-music-festival-san-francisco-tickets-8-8-2026/event/159253857/?quantity=1

## How it works

- `check_price.py` opens the event page in a real browser via Browserbase (StubHub 403s plain HTTP and Exa livecrawl), parses the ticket-class cards (GA, VIP, GA+, Golden Gate Pass), and appends one row to `history.jsonl`. Prices are per single ticket, fees included.
- A scheduled Claude Code cloud routine runs it every 3 hours, commits the new data point to this repo, and notifies via Gmail draft (+ a Google Calendar event 15 minutes out on real alerts, so a phone notification fires).

## Alert rules (implemented in `check_price.py` verdict + routine prompt)

- New all-time low for GA, or
- GA dropped 5% or more since the previous check.
- Daily 6am PT summary draft regardless, plus a failure draft if the scrape breaks.

## Running locally

```
pip install playwright   # client only, browser runs at Browserbase
set -a; source ~/.claude/browserbase.env; set +a
python3 check_price.py
```

## Knobs

- Cadence and alert thresholds: edit the routine at https://claude.ai/code/routines (cadence) or the alert math in `check_price.py` (thresholds).
- The routine prompt carries the Browserbase credentials because cloud sandboxes cannot read local env files.
- After Aug 8, 2026 the routine drafts a final "delete me" email and stops doing work.
