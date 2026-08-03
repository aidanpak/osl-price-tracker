#!/usr/bin/env python3
"""Check StubHub prices for Outside Lands Saturday (Aug 8, 2026) via Browserbase.

StubHub bot-blocks plain HTTP (403), so we load the page in a real fingerprinted
browser via Browserbase and read the server-rendered ticket-class cards.
Scrapes the page twice in one session: quantity=1 and quantity=2, since the
cheapest listing differs by how many tickets a listing can sell.

Usage (direct mode, local):
    BROWSERBASE_API_KEY=... BROWSERBASE_PROJECT_ID=... python3 check_price.py
    Requires: pip install playwright (client lib only; the browser runs remotely,
    no `playwright install` needed).

Usage (relay mode, legacy, quantity=1 only, for environments that cannot reach
api.browserbase.com):
    RELAY_URL=https://osl-price-tracker.vercel.app/api/price \
    BROWSERBASE_API_KEY=... BROWSERBASE_PROJECT_ID=... python3 check_price.py

Appends one row to history.jsonl and prints a JSON verdict to stdout.
Exit 0 on success (verdict carries the alert flag), exit 2 on scrape failure.
"""
import datetime
import json
import os
import re
import sys
import urllib.request

EVENT_URL_BASE = (
    "https://www.stubhub.com/outside-lands-music-festival-san-francisco-tickets-8-8-2026/"
    "event/159253857/?quantity={q}"
)
EVENT_URL = EVENT_URL_BASE.format(q=1)
HERE = os.path.dirname(os.path.abspath(__file__))
HISTORY = os.path.join(HERE, "history.jsonl")

# With hourly checks, cheapest-listing churn makes 5%-per-check drops common
# noise; NEW LOW stays the buy signal and BIG DROP only flags real capitulation.
BIG_DROP = 0.08

# Ticket-class card headings as they appear in page text, mapped to short keys.
CLASS_NAMES = {
    "General Admission": "GA",
    "VIP": "VIP",
    "GA+": "GA+",
    "Golden Gate Pass": "Golden Gate",
}


def get_page_texts(quantities):
    api_key = os.environ["BROWSERBASE_API_KEY"]
    project_id = os.environ["BROWSERBASE_PROJECT_ID"]
    req = urllib.request.Request(
        "https://api.browserbase.com/v1/sessions",
        data=json.dumps({"projectId": project_id}).encode(),
        headers={"X-BB-API-Key": api_key, "Content-Type": "application/json"},
    )
    sess = json.loads(urllib.request.urlopen(req).read())

    from playwright.sync_api import sync_playwright

    texts = {}
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(sess["connectUrl"])
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        for q in quantities:
            page.goto(EVENT_URL_BASE.format(q=q), wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(12000)
            texts[q] = page.evaluate("document.body.innerText")
        browser.close()
    return texts


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


def emit(verdict):
    """Print the verdict and persist it to verdict.json for downstream consumers
    (the notification routine reads verdict.json from git, it cannot run the scrape)."""
    out = json.dumps(verdict, indent=2)
    with open(os.path.join(HERE, "verdict.json"), "w") as f:
        f.write(out + "\n")
    print(out)


def ga_alerts(label, ga, prev, low):
    alerts = []
    if ga is None:
        return alerts
    if low is not None and ga < low:
        alerts.append(f"NEW LOW ({label}): GA ${ga} (previous low ${low})")
    if prev is not None and prev > ga and (prev - ga) / prev >= BIG_DROP:
        alerts.append(
            f"BIG DROP ({label}): GA fell {(prev - ga) / prev:.0%} since last check (${prev} -> ${ga})"
        )
    return alerts


def main():
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    texts = None
    try:
        if os.environ.get("RELAY_URL"):
            prices, prices2 = get_prices_via_relay(), {}
        else:
            texts = get_page_texts([1, 2])
            prices = parse_prices(texts[1])
            prices2 = parse_prices(texts[2])
    except Exception as e:
        emit({"ok": False, "ts": now, "error": f"{type(e).__name__}: {e}"})
        sys.exit(2)

    if "GA" not in prices and "GA" not in prices2:
        if texts is not None:
            with open(os.path.join(HERE, "last_page_text.txt"), "w") as f:
                f.write((texts.get(1) or "") + "\n----- quantity=2 -----\n" + (texts.get(2) or ""))
        emit({
            "ok": False, "ts": now,
            "error": "GA price not found on either quantity page; page layout may "
                     "have changed, or listings sold out",
            "partial_prices": {"q1": prices, "q2": prices2},
        })
        sys.exit(2)

    history = []
    if os.path.exists(HISTORY):
        with open(HISTORY) as f:
            history = [json.loads(l) for l in f if l.strip()]

    def series(key):
        return [h[key]["GA"] for h in history if h.get(key, {}).get("GA")]

    ga, ga2 = prices.get("GA"), prices2.get("GA")
    prev = (series("prices") or [None])[-1]
    prev2 = (series("prices2") or [None])[-1]
    low = min(series("prices")) if series("prices") else None
    low2 = min(series("prices2")) if series("prices2") else None

    with open(HISTORY, "a") as f:
        f.write(json.dumps({"ts": now, "prices": prices, "prices2": prices2}) + "\n")

    alerts = ga_alerts("1 ticket", ga, prev, low) + ga_alerts("2 tickets", ga2, prev2, low2)

    emit({
        "ok": True,
        "ts": now,
        "prices": prices,
        "prices2": prices2,
        "ga": ga if ga is not None else ga2,
        "ga2": ga2,
        "prev_ga": prev,
        "prev_ga2": prev2,
        "alltime_low_ga": low if low is not None else ga,
        "alltime_low_ga2": low2 if low2 is not None else ga2,
        "n_checks": len(history) + 1,
        "alert": bool(alerts),
        "alerts": alerts,
        "event_url": EVENT_URL,
    })


if __name__ == "__main__":
    main()
