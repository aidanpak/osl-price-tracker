#!/usr/bin/env python3
"""Send the alert email via Gmail SMTP, from Aidan's own address to itself.

This is the channel that reliably reaches his phone: real inbox delivery, so the
Gmail app pushes. (Gmail-MCP drafts and short-lead calendar events are silent,
and GitHub issue notifications route to a different address.)
Requires GMAIL_APP_PASSWORD in env; the Action skips this step when the secret
is absent. TEST_ALERT=true forces a send regardless of price movement.
"""
import json
import os
import smtplib
import ssl
from email.message import EmailMessage

HERE = os.path.dirname(os.path.abspath(__file__))
ADDR = "aidanpak10@gmail.com"

v = json.load(open(os.path.join(HERE, "verdict.json")))
test = os.environ.get("TEST_ALERT", "").lower() == "true"
if not (v.get("ok") and (v.get("alert") or test)):
    raise SystemExit(0)

with open(os.path.join(HERE, "history.jsonl")) as f:
    tail = [json.loads(l) for l in f if l.strip()][-10:]

subject = "[OSL Tracker] " + (
    v["alerts"][0] if v.get("alerts") else f"TEST: GA ${v['ga']} (plumbing check)"
)
lines = [
    f"GA: ${v['ga']}  (prev ${v['prev_ga']}, all-time low ${v['alltime_low_ga']}, check #{v['n_checks']})",
    f"All tiers: {json.dumps(v['prices'])}",
    "",
    "Last 10 checks (UTC):",
    *[f"  {r['ts']}  GA ${r['prices'].get('GA', '?')}" for r in tail],
    "",
    f"Buy now: {v['event_url']}",
]
msg = EmailMessage()
msg["From"] = ADDR
msg["To"] = ADDR
msg["Subject"] = subject
msg.set_content("\n".join(lines))

with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
    s.login(ADDR, os.environ["GMAIL_APP_PASSWORD"])
    s.send_message(msg)
print("alert email sent:", subject)
