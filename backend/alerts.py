"""Webhook alerts. Works with Discord and Slack incoming webhooks (no extra deps).

Set before starting the backend (PowerShell):
    $env:ALERT_WEBHOOK_URL = "https://discord.com/api/webhooks/..."
"""
import json
import os
import urllib.request


def url() -> str:
    return os.getenv("ALERT_WEBHOOK_URL", "").strip()


def configured() -> bool:
    return bool(url())


def send(msg: str) -> bool:
    if not configured():
        return False
    body = json.dumps({"content": msg, "text": msg}).encode()
    req = urllib.request.Request(
        url(), data=body,
        headers={"Content-Type": "application/json", "User-Agent": "netmon/0.2"})
    try:
        urllib.request.urlopen(req, timeout=5).close()
        return True
    except Exception as e:
        print(f"[alerts] webhook failed: {e}")
        return False
