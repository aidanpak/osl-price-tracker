#!/usr/bin/env python3
"""Check StubHub prices for Outside Lands Saturday (Aug 8, 2026) via Browserbase.

StubHub bot-blocks plain HTTP (403), so we load the page in a real fingerprinted
browser via Browserbase and read the server-rendered ticket-class cards.

Usage (direct mode, local):
    BROWSERBASE_API_KEY=... BROWSERBASE_PROJECT_ID=... python3 check_price.py
    Requires: pip install playwright (client lib only; the browser runs remotely,
    no `playwright install` needed).

Usage (relay mode, for environments that cannot reach api.browserbase.com,
e.g. the Claude cloud sandbox whose egress proxy blocks it):
    RELAY_URL=https://osl-price-tracker.vercel.app/api/price \
    BROWSERBASE_API_KEY=... BROWSERBASE_PROJECT_ID=... python3 check_price.py
    No third-party packages needed; the Vercel function does the scrape.

Appends one row to history.jsonl and prints a JSON verdict to stdout.
Exit 0 on success (verdict carries the alert flag), exit 2 on scrape failure.
"""
import datetime
import json
import os
import re
import sys
import urllib.request

EVENT_URL = (
    "https://www.stubhub.com/outside-lands-music-festival-san-francisco-tickets-8-8-2026/"
    "event/159253857/?quantity=1"
)
HERE = os.path.dirname(os.path.abspath(__file__))
HISTORY = os.path.join(HERE, "history.jsonl")

# Ticket-class card headings as they appear in page text, mapped to short keys.
CLASS_NAMES = {
    "General Admission": "GA",
    "VIP": "VIP",
    "GA+": "GA+",
    "Golden Gate Pass": "Golden Gate",
}


def get_page_text():
    api_key = os.environ["BROWSERBASE_API_KEY"]
    project_id = os.environ["BROWSERBASE_PROJECT_ID"]
    req = urllib.request.Request(
        "https://api.browserbase.com/v1/sessions",
        data=json.dumps({"projectId": project_id}).encode(),
        headers={"X-BB-API-Key": api_key, "Content-Type": "application/json"},
    )
    sess = json.loads(urllib.request.urlopen(req).read())

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(sess["connectUrl"])
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(EVENT_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(12000)
        text = page.evaluate("document.body.innerText")
        browser.close()
    return text


def parse_prices(text):
    """Cards render as: <class name> / <perks> / [scarcity] / $1,234 / incl. fees.

    We take the first $ amount within 8 lines of a class heading, and require
    'incl. fees' within 2 lines after it so a stray heading elsewhere in the
    page can't match.
    """
    lines = [l.strip() for l in text.splitlines()]
    prices = {}
    for i, line in enumerate(lines):
        key = CLASS_NAMES.get(line)
        if not key or key in prices:
            continue
        for j in range(i + 1, min(i + 9, len(lines))):
            m = re.fullmatch(r"\$([\d,]+)(?:\.\d{2})?", lines[j])
            if m and any("incl. fees" in lines[k] for k in range(j + 1, min(j + 3, len(lines)))):
                prices[key] = int(m.group(1).replace(",", ""))
                break
    return prices


def get_prices_via_relay():
    req = urllib.request.Request(
        os.environ["RELAY_URL"],
        headers={
            "x-bb-key": os.environ["BROWSERBASE_API_KEY"],
            "x-bb-project": os.environ["BROWSERBASE_PROJECT_ID"],
        },
    )
    data = json.loads(urllib.request.urlopen(req, timeout=90).read())
    if not data.get("ok"):
        raise RuntimeError("relay error: " + json.dumps(data)[:500])
    return data["prices"]


def main():
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    text = None
    try:
        if os.environ.get("RELAY_URL"):
            prices = get_prices_via_relay()
        else:
            text = get_page_text()
            prices = parse_prices(text)
    except Exception as e:
        print(json.dumps({"ok": False, "ts": now, "error": f"{type(e).__name__}: {e}"}))
        sys.exit(2)

    if "GA" not in prices:
        if text is not None:
            with open(os.path.join(HERE, "last_page_text.txt"), "w") as f:
                f.write(text)
        print(json.dumps({
            "ok": False, "ts": now,
            "error": "GA price not found on page; page layout may have changed, "
                     "or listings sold out",
            "partial_prices": prices,
        }))
        sys.exit(2)

    history = []
    if os.path.exists(HISTORY):
        with open(HISTORY) as f:
            history = [json.loads(l) for l in f if l.strip()]

    ga = prices["GA"]
    prev = history[-1]["prices"].get("GA") if history else None
    past_lows = [h["prices"]["GA"] for h in history if h["prices"].get("GA")]
    alltime_low = min(past_lows) if past_lows else None

    with open(HISTORY, "a") as f:
        f.write(json.dumps({"ts": now, "prices": prices}) + "\n")

    alerts = []
    if alltime_low is not None and ga < alltime_low:
        alerts.append(f"NEW LOW: GA ${ga} (previous low ${alltime_low})")
    if prev is not None and prev > ga and (prev - ga) / prev >= 0.05:
        alerts.append(f"BIG DROP: GA fell {(prev - ga) / prev:.0%} since last check (${prev} -> ${ga})")

    print(json.dumps({
        "ok": True,
        "ts": now,
        "prices": prices,
        "ga": ga,
        "prev_ga": prev,
        "alltime_low_ga": alltime_low if alltime_low is not None else ga,
        "n_checks": len(history) + 1,
        "alert": bool(alerts),
        "alerts": alerts,
        "event_url": EVENT_URL,
    }, indent=2))


if __name__ == "__main__":
    main()
