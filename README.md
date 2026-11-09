<<<<<<< HEAD
# netmon

Network health monitor. Python (FastAPI + asyncio) probes hosts and stores
history in SQLite; a React + TypeScript (Vite) dashboard shows live telemetry.

```
backend/
  main.py           probe engine, REST API, WebSocket stream
  hosts.py          host line parser (the syntax in section 3)
  store.py          SQLite: samples (history) and events (status changes)
  alerts.py         webhook alerts (Discord / Slack)
  import_hosts.py   bulk import CLI
  targets.json      the monitored host list
  hosts.example.txt example import file
frontend/           Vite + React + TS dashboard
```

---

## 1. Quick start (Windows / PowerShell)

Terminal 1, backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Terminal 2, frontend:

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

If PowerShell blocks the venv activation script, run this once:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

---

## 2. How probing works

| Kind | Triggered by | What it measures |
|------|--------------|------------------|
| ICMP | host with **no port** | Round-trip time of one `ping` per cycle |
| TCP  | host **with a port** | Time to complete a TCP handshake to that port |
| DNS  | `dns://name` | Time for the system resolver to resolve the name |

Every 2 seconds each target is probed once. A timeout counts as a lost packet.

Status rules:

- **DOWN**: the last 3 probes all failed
- **DEGRADED**: over 5% loss or over 150 ms average (needs at least 5 samples)
- **NOMINAL**: everything else

Which kind should I use?

- Use **no port (ICMP)** for routers, servers and anything that answers ping.
- Use **a port (TCP)** when ping is blocked, which is common on cloud VMs and
  many Windows machines (Windows Firewall drops ICMP by default). TCP also
  proves the actual service is up, not just the machine. Examples: 443 for
  HTTPS, 22 for SSH, 3389 for RDP, 5432 for Postgres, 445 for SMB.
- Use **dns://** to watch your resolver's speed.

---

## 3. Adding hosts

There are three ways. All of them use the same syntax.

### 3a. Syntax

One entry per line. Spaces and commas also work as separators, so you can paste
`1.1.1.1, 8.8.8.8:53 github.com:443` on one line.

| You write | Result |
|-----------|--------|
| `1.1.1.1` | ICMP ping to 1.1.1.1 |
| `router.lan` | ICMP ping to a hostname |
| `github.com:443` | TCP connect to port 443 |
| `192.168.1.20:445` | TCP connect to port 445 |
| `tcp://10.0.0.5:22` | TCP, explicit scheme |
| `icmp://10.0.0.1` | ICMP, explicit scheme |
| `dns://example.com` | DNS resolve timing |
| `nas=192.168.1.20:445` | Custom display name `nas`, then TCP 445 |
| `gateway=192.168.1.1` | Custom name, ICMP |
| `2001:4860:4860::8888` | Bare IPv6, ICMP |
| `[2606:4700:4700::1111]:443` | IPv6 with port, TCP (brackets required) |
| `# anything` | Comment, ignored. Trailing ` # note` also works |

Rules:

- No port gives ICMP. A port gives TCP. `dns://` never takes a port.
- `tcp://` requires a port. `icmp://` and `dns://` reject one.
- Ports must be 1-65535. Names may use letters, digits, `. _ - :`
- Duplicates (same kind, host and port) are skipped, not added twice.
- If a name is taken, a suffix is added: `nas`, `nas-2`, ...
- Default name is the host (ICMP), `host:port` (TCP), or `dns:host` (DNS).

### 3b. From the dashboard

Click **[+] add / import hosts**, paste one host or a whole list, press
**[ commit ]**. **[ load file ]** reads a .txt, .csv or .json file into the box
first so you can review it. You get a report of what was added, skipped, or
rejected (with the reason). New hosts start probing on the next cycle.

Remove a host with the **[x]** button on its row. That also deletes its history.

### 3c. From a file with the CLI

Make a file (see `backend/hosts.example.txt`):

```text
# core
gateway=192.168.1.1
1.1.1.1
# services
nas=192.168.1.20:445
ssh-box=tcp://10.0.0.5:22
github.com:443
dns://example.com
```

Then, with the backend running:

```powershell
cd backend
python import_hosts.py hosts.txt --dry-run    # preview only, changes nothing
python import_hosts.py hosts.txt              # import into the running backend
python import_hosts.py hosts.txt --offline    # edit targets.json (backend stopped; restart after)
python import_hosts.py hosts.txt --api http://192.168.1.50:8000   # remote backend
```

The CLI exits non-zero if any line had an error, so it works in scripts.

### 3d. Editing targets.json directly

```json
[
  {"name": "gateway",   "host": "192.168.1.1", "kind": "icmp"},
  {"name": "web-https", "host": "github.com",  "kind": "tcp", "port": 443},
  {"name": "resolver",  "host": "example.com", "kind": "dns"}
]
```

Restart the backend after hand-editing. A JSON array like this can also be
pasted into the dashboard box or imported with the CLI.

---

## 4. History

Every probe is written to `backend/netmon.db` (SQLite). That gives you:

- The latency strip survives restarts (the last 90 samples reload on startup).
- Click a host name on the dashboard to open its history chart
  (15m / 1h / 6h / 24h). Red bars mark buckets that had packet loss.
- Data older than 7 days is pruned. Change it with the `RETENTION_DAYS`
  environment variable.

Query it yourself:

```powershell
sqlite3 backend\netmon.db "SELECT datetime(ts,'unixepoch'), target, ms FROM samples ORDER BY ts DESC LIMIT 10;"
```

---

## 5. Alerts

Status changes (NOMINAL, DEGRADED, DOWN) are always written to the event log
on the dashboard. To also get pushed notifications, set a webhook.

Discord: Server Settings, Integrations, Webhooks, New Webhook, Copy URL.
Slack: create an Incoming Webhook and copy the URL.

```powershell
$env:ALERT_WEBHOOK_URL = "https://discord.com/api/webhooks/XXXX/YYYY"
uvicorn main:app --port 8000
```

The dashboard top bar shows `alerts WEBHOOK ARMED` when it is set. Test it:

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/api/alerts/test
```

Behaviour:

- A message is sent on each status change: `[netmon] nas (tcp://192.168.1.20:445) NOMINAL -> DOWN | loss 100% avg --`
- Recovery messages (back to NOMINAL) are always sent.
- Problem messages for one host are rate-limited to once per 120 s to stop
  flapping from spamming you. Change with `ALERT_COOLDOWN_S`.

---

## 6. API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/config` | Webhook armed?, retention, interval |
| GET | `/api/targets` | Current stats for every host |
| POST | `/api/targets/import` | Body `{"text": "..."}` adds one or many hosts |
| DELETE | `/api/targets?name=NAME` | Remove a host and its history |
| GET | `/api/history?name=NAME&minutes=60` | Bucketed latency and loss history |
| GET | `/api/events?limit=50` | Status change log |
| POST | `/api/alerts/test` | Send a test webhook |
| WS | `/ws` | Live snapshot every 2 s |

Interactive docs: http://localhost:8000/docs

Add a host from PowerShell:

```powershell
$b = @{ text = "nas=192.168.1.20:445" } | ConvertTo-Json
Invoke-RestMethod -Method Post http://localhost:8000/api/targets/import -ContentType application/json -Body $b
```

---

## 7. Troubleshooting

| Symptom | Fix |
|---------|-----|
| Every ICMP host shows DOWN but the internet works | Ping is blocked by a firewall. Use the same host with a port, e.g. `host:443` |
| Dashboard says `stream RETRY` | Backend is not running on port 8000. Check terminal 1 |
| `bad port` / `tcp needs a port` | See the rules in section 3a |
| A host shows `invalid host` | Check for typos or stray characters. Hostnames allow letters, digits, `-` and `.` only |
| Added a host but it never appears | It was probably a duplicate. The import report lists skipped hosts |
| Frontend calls the wrong address | Edit `frontend/src/api.ts` |
| Alerts never arrive | Run the test call in section 5; confirm the env var was set in the same terminal that started uvicorn |

## 8. Ideas to extend

- Traceroute view with per-hop latency
- LAN sweep to discover devices on your subnet
- Email / Telegram alert channels in `alerts.py`
- Per-host thresholds in `targets.json`
- Docker Compose for one-command startup
=======
# Network-Health-Monitor
A real-time Network Health Monitoring application  Designed to monitor network connectivity, track host availability, measure response times, and provide insights into network performance through an interactive dashboard.
>>>>>>> 8018e70862c2b8a27789dc303f7b63a28d4ce0e5
