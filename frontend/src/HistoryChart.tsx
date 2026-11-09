import { useEffect, useState } from "react";
import { API } from "./api";
import type { Bucket } from "./types";

const RANGES: [string, number][] = [["15m", 15], ["1h", 60], ["6h", 360], ["24h", 1440]];
const W = 600, H = 120;

export default function HistoryChart({ name }: { name: string }) {
  const [range, setRange] = useState(60);
  const [data, setData] = useState<Bucket[]>([]);

  useEffect(() => {
    let dead = false;
    const load = async () => {
      try {
        const r = await fetch(`${API}/api/history?name=${encodeURIComponent(name)}&minutes=${range}`);
        const j = await r.json();
        if (!dead) setData(j.buckets);
      } catch { /* backend offline; keep last data */ }
    };
    load();
    const id = setInterval(load, 10000);
    return () => { dead = true; clearInterval(id); };
  }, [name, range]);

  const now = Date.now() / 1000;
  const x0 = now - range * 60;
  const X = (t: number) => ((t - x0) / (range * 60)) * W;
  const vals = data.map((d) => d.avg).filter((v): v is number => v !== null);
  const ymax = Math.max(10, ...vals) * 1.15;
  const Y = (v: number) => H - 6 - (v / ymax) * (H - 14);
  const pts = data.filter((d) => d.avg !== null).map((d) => `${X(d.t).toFixed(1)},${Y(d.avg!).toFixed(1)}`).join(" ");

  return (
    <div className="hist">
      <div className="row">
        {RANGES.map(([label, m]) => (
          <button key={m} className={`btn sm ${m === range ? "on" : ""}`} onClick={() => setRange(m)}>{label}</button>
        ))}
        <span className="dim">avg latency, scale 0-{ymax.toFixed(0)}ms, red = packet loss in bucket</span>
      </div>
      {data.length === 0 ? (
        <p className="dim">&gt; no samples in this window yet</p>
      ) : (
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={`latency history for ${name}`}>
          <line x1="0" x2={W} y1={H - 6} y2={H - 6} className="axis" />
          {data.map((d) => d.lost > 0 && (
            <rect key={d.t} x={X(d.t) - 1.5} width={3} y={H - 6 - (d.lost / d.n) * (H - 14)}
                  height={(d.lost / d.n) * (H - 14)} className="lossbar" />
          ))}
          <polyline points={pts} fill="none" vectorEffect="non-scaling-stroke" className="hline" />
        </svg>
      )}
    </div>
  );
}
