# OSL Price Tracker

Tracks StubHub prices for Outside Lands Saturday (Aug 8, 2026), mainly the General Admission pass, so Aidan can buy near the bottom. This repo is public and contains no secrets: credentials live only in the cloud routine's configuration.

Event: https://www.stubhub.com/outside-lands-music-festival-san-francisco-tickets-8-8-2026/event/159253857/?quantity=1

## How it works

- `check_price.py` opens the event page in a real browser via Browserbase (StubHub 403s plain HTTP and Exa livecrawl), parses the ticket-class cards (GA, VIP, GA+, Golden Gate Pass), and appends one row to `history.jsonl`. Prices are per single ticket, fees included.
- A scheduled Claude Code cloud routine runs every 3 hours: it clones this repo read-only over HTTPS (the sandbox's egress proxy blocks SSH and git pushes are not possible without a token), restores `history.jsonl` from a Gmail draft titled "OSL price history log" that serves as the persistent state store, runs the script, writes the updated history back to that draft, and notifies via Gmail draft (plus a Google Calendar event 15 minutes out on real alerts, so a phone notification fires).
- The `history.jsonl` in this repo is only the day-one seed. The live history lives in the Gmail state draft.

## Alert rules

- New all-time low for GA, or
- GA dropped 5% or more since the previous check.
- Daily 6am PT summary draft regardless, plus a failure draft if anything breaks.

## Running locally

```
pip install playwright   # client only, browser runs at Browserbase
set -a; source ~/.claude/browserbase.env; set +a
python3 check_price.py
```

## Knobs

- Cadence: edit the routine at https://claude.ai/code/routines
- Alert thresholds: the alert math is in `check_price.py` (verdict section); the cloud agent picks up script changes on its next clone.
- After Aug 8, 2026 the routine drafts a final "delete me" email and stops doing work.
