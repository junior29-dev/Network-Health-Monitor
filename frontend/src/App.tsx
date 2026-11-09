import { useEffect, useState } from "react";
import { useTelemetry } from "./useTelemetry";
import { API } from "./api";
import HostPanel from "./HostPanel";
import HistoryChart from "./HistoryChart";
import EventLog from "./EventLog";
import type { Status, Target } from "./types";

const fmtMs = (v: number | null) => (v === null ? "  --" : v.toFixed(1));
const fmtBps = (b: number) =>
  b > 1e6 ? `${(b / 1e6).toFixed(2)} Mb/s` : `${(b / 1e3).toFixed(1)} Kb/s`;
const fmtUp = (s: number) => {
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = Math.floor(s % 60);
  return [h, m, x].map((n) => String(n).padStart(2, "0")).join(":");
};

// latency -> heat bucket for the trace strip
function heat(v: number | null): string {
  if (v === null) return "h-lost";
  if (v < 30) return "h-1";
  if (v < 80) return "h-2";
  if (v < 150) return "h-3";
  return "h-4";
}

function TraceStrip({ samples, slots = 90 }: { samples: (number | null)[]; slots?: number }) {
  const pad = Array(Math.max(0, slots - samples.length)).fill(undefined);
  return (
    <div className="trace" aria-hidden>
      {pad.map((_, i) => <span key={`p${i}`} className="cell h-empty" />)}
      {samples.map((s, i) => (
        <span key={i} className={`cell ${heat(s)}`} title={s === null ? "timeout" : `${s.toFixed(1)} ms`} />
      ))}
    </div>
  );
}

function Spark({ samples }: { samples: (number | null)[] }) {
  const ok = samples.filter((s): s is number => s !== null);
  if (ok.length < 2) return <svg className="spark" viewBox="0 0 100 24" />;
  const max = Math.max(...ok, 1);
  const pts = samples.map((s, i) => {
    const x = (i / Math.max(samples.length - 1, 1)) * 100;
    const y = s === null ? 24 : 22 - (s / max) * 20;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg className="spark" viewBox="0 0 100 24" preserveAspectRatio="none">
      <polyline points={pts} fill="none" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

const TAG: Record<Status, string> = { NOMINAL: "[ OK ]", DEGRADED: "[WARN]", DOWN: "[DOWN]" };

function Row({ t }: { t: Target }) {
  const [open, setOpen] = useState(false);
  const uri = `${t.kind}://${t.host}${t.port ? ":" + t.port : ""}`;

  async function remove() {
    if (!confirm(`stop monitoring ${t.name} and delete its history?`)) return;
    await fetch(`${API}/api/targets?name=${encodeURIComponent(t.name)}`, { method: "DELETE" });
  }

  return (
    <section className={`node s-${t.status.toLowerCase()}`}>
      <header>
        <span className="tag">{TAG[t.status]}</span>
        <button className="name link" onClick={() => setOpen(!open)} aria-expanded={open} title="toggle history">
          {t.name}
        </button>
        <span className="dim">{uri}</span>
        <span className="lat">{fmtMs(t.last)}<i>ms</i></span>
        <button className="btn sm x" onClick={remove} aria-label={`remove ${t.name}`}>[x]</button>
      </header>
      <TraceStrip samples={t.samples} />
      <footer>
        <span>avg <b>{fmtMs(t.avg)}</b></span>
        <span>min <b>{fmtMs(t.min)}</b></span>
        <span>max <b>{fmtMs(t.max)}</b></span>
        <span>jitter <b>{t.jitter.toFixed(1)}</b></span>
        <span>loss <b className={t.loss > 5 ? "bad" : ""}>{t.loss.toFixed(1)}%</b></span>
        <Spark samples={t.samples} />
      </footer>
      {open && <HistoryChart name={t.name} />}
    </section>
  );
}

export default function App() {
  const { snap, link } = useTelemetry();
  const [webhook, setWebhook] = useState<boolean | null>(null);
  useEffect(() => {
    fetch(`${API}/api/config`).then((r) => r.json()).then((c) => setWebhook(c.webhook)).catch(() => {});
  }, [link]);
  const down = snap?.targets.filter((t) => t.status === "DOWN").length ?? 0;
  const warn = snap?.targets.filter((t) => t.status === "DEGRADED").length ?? 0;
  const verdict = !snap ? "WAITING" : down ? "LINK IMPAIRED" : warn ? "DEGRADED" : "ALL SYSTEMS NOMINAL";

  return (
    <main>
      <div className="scan" aria-hidden />
      <pre className="banner">{`  _   _  _____ _____ __  __  ___  _   _
 | \\ | || ____|_   _|  \\/  |/ _ \\| \\ | |
 |  \\| ||  _|   | | | |\\/| | | | |  \\| |
 | |\\  || |___  | | | |  | | |_| | |\\  |
 |_| \\_||_____| |_| |_|  |_|\\___/|_| \\_|`}</pre>

      <div className="bar">
        <span>host <b>{snap?.host ?? "?"}</b></span>
        <span>stream <b className={`lk-${link.toLowerCase()}`}>{link}</b></span>
        <span>uptime <b>{snap ? fmtUp(snap.uptime) : "--:--:--"}</b></span>
        <span>rx <b>{snap ? fmtBps(snap.net.rx_bps) : "--"}</b></span>
        <span>tx <b>{snap ? fmtBps(snap.net.tx_bps) : "--"}</b></span>
        <span>alerts <b className={webhook ? "lk-online" : "dim"}>{webhook === null ? "--" : webhook ? "WEBHOOK ARMED" : "OFF"}</b></span>
        <span>nic err <b>{snap ? snap.net.errin + snap.net.errout : "--"}</b></span>
        <span>drops <b>{snap ? snap.net.dropin + snap.net.dropout : "--"}</b></span>
      </div>

      <div className={`verdict ${down ? "v-down" : warn ? "v-warn" : "v-ok"}`}>
        &gt; status: {verdict}
        <span className="cursor" />
      </div>

      <HostPanel />

      {snap?.targets.map((t) => <Row key={t.name} t={t} />)}
      {!snap && <p className="dim">&gt; awaiting handshake on ws://localhost:8000/ws ...</p>}

      {snap && <EventLog events={snap.events} />}

      <p className="legend dim">
        trace: <span className="cell h-1" /> &lt;30ms <span className="cell h-2" /> &lt;80
        <span className="cell h-3" /> &lt;150 <span className="cell h-4" /> 150+
        <span className="cell h-lost" /> timeout
      </p>
    </main>
  );
}
