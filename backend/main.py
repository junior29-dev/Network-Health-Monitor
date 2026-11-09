"""
netmon backend
Probes targets (ICMP / TCP / DNS), keeps a rolling window in memory, persists
every sample to SQLite, detects status transitions, fires webhook alerts, and
streams snapshots over a WebSocket.

Run:  uvicorn main:app --reload --port 8000
"""
import asyncio
import json
import os
import platform
import re
import socket
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from statistics import mean
from typing import Optional

import psutil
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import alerts
from hosts import parse_bulk
from store import Store

BASE = Path(__file__).parent
TARGETS_FILE = BASE / "targets.json"
DB_PATH = os.getenv("DB_PATH", str(BASE / "netmon.db"))
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "7"))
ALERT_COOLDOWN_S = int(os.getenv("ALERT_COOLDOWN_S", "120"))

INTERVAL_S = 2.0
WINDOW = 90           # samples kept in memory per target
MIN_SAMPLES = 5       # need this many before DEGRADED can trigger
PROBE_TIMEOUT_S = 1.5
IS_WIN = platform.system() == "Windows"
TIME_RE = re.compile(r"time[=<]\s*([\d.]+)\s*ms", re.IGNORECASE)

store = Store(DB_PATH)
TARGETS: list[dict] = json.loads(TARGETS_FILE.read_text()) if TARGETS_FILE.exists() else []
history = {t["name"]: deque(store.recent(t["name"], WINDOW), maxlen=WINDOW) for t in TARGETS}
last_status: dict[str, str] = {}
last_notify: dict[str, float] = {}
recent_events = deque(store.events(30), maxlen=30)   # newest first
clients: set[WebSocket] = set()
boot = time.time()


def save_targets():
    tmp = TARGETS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(TARGETS, indent=2))
    tmp.replace(TARGETS_FILE)


# ---------- probes: each returns latency in ms, or None on failure ----------
async def probe_icmp(host: str) -> Optional[float]:
    args = (["ping", "-n", "1", "-w", "1000", host] if IS_WIN
            else ["ping", "-c", "1", "-W", "1", host])
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(proc.communicate(), PROBE_TIMEOUT_S + 1)
        m = TIME_RE.search(out.decode(errors="ignore"))
        if m and proc.returncode == 0:
            return float(m.group(1))
    except Exception:
        pass
    return None


async def probe_tcp(host: str, port: int) -> Optional[float]:
    t0 = time.perf_counter()
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), PROBE_TIMEOUT_S)
        dt = (time.perf_counter() - t0) * 1000
        writer.close()
        await writer.wait_closed()
        return dt
    except Exception:
        return None


async def probe_dns(host: str) -> Optional[float]:
    t0 = time.perf_counter()
    try:
        await asyncio.wait_for(
            asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM),
            PROBE_TIMEOUT_S)
        return (time.perf_counter() - t0) * 1000
    except Exception:
        return None


async def probe(t: dict) -> Optional[float]:
    if t["kind"] == "icmp":
        return await probe_icmp(t["host"])
    if t["kind"] == "tcp":
        return await probe_tcp(t["host"], t["port"])
    return await probe_dns(t["host"])


# ---------- stats ----------
def summarize(t: dict) -> dict:
    samples = list(history[t["name"]])
    ok = [s for s in samples if s is not None]
    loss = 100.0 * (len(samples) - len(ok)) / len(samples) if samples else 0.0
    avg = mean(ok) if ok else None
    jitter = mean(abs(a - b) for a, b in zip(ok, ok[1:])) if len(ok) > 1 else 0.0
    last3 = samples[-3:]
    if len(last3) == 3 and all(s is None for s in last3):
        status = "DOWN"
    elif len(samples) >= MIN_SAMPLES and (loss > 5 or (avg is not None and avg > 150)):
        status = "DEGRADED"
    else:
        status = "NOMINAL"
    return {
        "name": t["name"], "host": t["host"], "kind": t["kind"], "port": t.get("port"),
        "status": status, "last": samples[-1] if samples else None,
        "avg": avg, "min": min(ok) if ok else None, "max": max(ok) if ok else None,
        "jitter": jitter, "loss": loss, "samples": samples,
    }


# ---------- local interface throughput ----------
_prev = {"t": time.time(), "io": psutil.net_io_counters()}

def throughput() -> dict:
    now, io = time.time(), psutil.net_io_counters()
    dt = max(now - _prev["t"], 1e-6)
    rx = (io.bytes_recv - _prev["io"].bytes_recv) / dt
    tx = (io.bytes_sent - _prev["io"].bytes_sent) / dt
    _prev.update(t=now, io=io)
    return {"rx_bps": rx * 8, "tx_bps": tx * 8,
            "errin": io.errin, "errout": io.errout, "dropin": io.dropin, "dropout": io.dropout}


# ---------- status transitions -> events -> alerts ----------
async def check_transition(s: dict):
    name, new = s["name"], s["status"]
    old = last_status.get(name)
    last_status[name] = new
    if old == new or (old is None and new == "NOMINAL"):
        return
    avg = "--" if s["avg"] is None else f"{s['avg']:.1f}ms"
    ev = {"ts": time.time(), "target": name, "old": old or "UNKNOWN", "new": new,
          "detail": f"loss {s['loss']:.0f}% avg {avg}"}
    await asyncio.to_thread(store.add_event, ev)
    recent_events.appendleft(ev)
    uri = f"{s['kind']}://{s['host']}" + (f":{s['port']}" if s.get("port") else "")
    msg = f"[netmon] {name} ({uri}) {ev['old']} -> {new} | {ev['detail']}"
    print(msg)
    recovery = new == "NOMINAL"
    if recovery or time.time() - last_notify.get(name, 0) >= ALERT_COOLDOWN_S:
        if not recovery:
            last_notify[name] = time.time()
        await asyncio.to_thread(alerts.send, msg)


# ---------- main loop ----------
async def monitor_loop():
    cycles = 0
    while True:
        started = time.perf_counter()
        targets = list(TARGETS)
        results = await asyncio.gather(*(probe(t) for t in targets))
        now, rows = time.time(), []
        for t, r in zip(targets, results):
            h = history.get(t["name"])
            if h is None:          # removed mid-probe
                continue
            h.append(r)
            rows.append((now, t["name"], r))
        await asyncio.to_thread(store.add_samples, rows)

        summaries = [summarize(t) for t in targets if t["name"] in history]
        for s in summaries:
            await check_transition(s)

        snap = json.dumps({
            "ts": now, "uptime": now - boot, "host": socket.gethostname(),
            "interval": INTERVAL_S, "net": throughput(),
            "targets": summaries, "events": list(recent_events)[:14],
        })
        for ws in list(clients):
            try:
                await ws.send_text(snap)
            except Exception:
                clients.discard(ws)

        cycles += 1
        if cycles % 1800 == 0:     # roughly hourly
            await asyncio.to_thread(store.prune, RETENTION_DAYS)
        await asyncio.sleep(max(0.0, INTERVAL_S - (time.perf_counter() - started)))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(store.prune, RETENTION_DAYS)
    task = asyncio.create_task(monitor_loop())
    yield
    task.cancel()


app = FastAPI(title="netmon", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------- REST ----------
class ImportBody(BaseModel):
    text: str


@app.get("/api/config")
def get_config():
    return {"webhook": alerts.configured(), "retention_days": RETENTION_DAYS,
            "interval": INTERVAL_S, "cooldown_s": ALERT_COOLDOWN_S}


@app.get("/api/targets")
def get_targets():
    return [summarize(t) for t in TARGETS]


@app.post("/api/targets/import")
def import_targets(body: ImportBody):
    """One host or many. See hosts.py for the accepted syntax."""
    new, skipped, errors = parse_bulk(body.text, TARGETS)
    for t in new:
        TARGETS.append(t)
        history[t["name"]] = deque(store.recent(t["name"], WINDOW), maxlen=WINDOW)
    if new:
        save_targets()
    return {"added": new, "skipped": skipped, "errors": errors}


@app.delete("/api/targets")
def delete_target(name: str):
    for i, t in enumerate(TARGETS):
        if t["name"] == name:
            TARGETS.pop(i)
            history.pop(name, None)
            last_status.pop(name, None)
            save_targets()
            store.delete_target(name)
            return {"removed": name}
    raise HTTPException(404, f"no target named '{name}'")


@app.get("/api/history")
def get_history(name: str, minutes: int = 60):
    minutes = max(1, min(minutes, RETENTION_DAYS * 1440))
    bucket = max(int(minutes * 60 / 120), 2)
    return {"name": name, "minutes": minutes, "bucket_s": bucket,
            "buckets": store.history(name, minutes, bucket)}


@app.get("/api/events")
def get_events(limit: int = 50):
    return store.events(max(1, min(limit, 500)))


@app.post("/api/alerts/test")
def alerts_test():
    return {"configured": alerts.configured(),
            "sent": alerts.send("[netmon] test alert: webhook is wired up")}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    try:
        while True:
            await ws.receive_text()   # keepalive; we only push
    except WebSocketDisconnect:
        clients.discard(ws)
