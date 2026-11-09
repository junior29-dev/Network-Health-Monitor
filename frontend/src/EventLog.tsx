import type { NetEvent } from "./types";

const hms = (ts: number) => new Date(ts * 1000).toLocaleTimeString("en-GB");

export default function EventLog({ events }: { events: NetEvent[] }) {
  return (
    <section className="panel">
      <h2>&gt; event log</h2>
      {events.length === 0 && <p className="dim">no status changes recorded</p>}
      <ul className="events">
        {events.map((e, i) => (
          <li key={`${e.ts}-${e.target}-${i}`} className={`ev-${e.new.toLowerCase()}`}>
            <span className="dim">{hms(e.ts)}</span>
            <span className="name">{e.target}</span>
            <span>{e.old} -&gt; <b>{e.new}</b></span>
            <span className="dim">{e.detail}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
