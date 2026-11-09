import { useRef, useState } from "react";
import { API } from "./api";
import type { ImportResult } from "./types";

const PLACEHOLDER = `# one per line, or space / comma separated
1.1.1.1                 # no port  -> ICMP ping
github.com:443          # port     -> TCP connect
nas=192.168.1.20:445    # custom name
dns://example.com       # DNS resolve time`;

export default function HostPanel() {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [res, setRes] = useState<ImportResult | null>(null);
  const [err, setErr] = useState("");
  const file = useRef<HTMLInputElement>(null);

  async function submit() {
    setErr(""); setRes(null);
    try {
      const r = await fetch(`${API}/api/targets/import`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      const j: ImportResult = await r.json();
      setRes(j);
      if (j.errors.length === 0) setText("");
    } catch {
      setErr("backend unreachable on " + API);
    }
  }

  return (
    <section className="panel">
      <button className="btn" onClick={() => setOpen(!open)} aria-expanded={open}>
        {open ? "[-]" : "[+]"} add / import hosts
      </button>
      {open && (
        <div className="hostbox">
          <textarea
            value={text} onChange={(e) => setText(e.target.value)}
            placeholder={PLACEHOLDER} rows={6} spellCheck={false}
            aria-label="hosts to monitor"
          />
          <div className="row">
            <button className="btn go" onClick={submit} disabled={!text.trim()}>[ commit ]</button>
            <button className="btn" onClick={() => file.current?.click()}>[ load file ]</button>
            <input
              ref={file} type="file" accept=".txt,.csv,.json" hidden
              onChange={async (e) => {
                const f = e.target.files?.[0];
                if (f) setText(await f.text());
                e.target.value = "";
              }}
            />
            <span className="dim">no port = ICMP, port = TCP, dns:// = resolver timing</span>
          </div>
          {err && <p className="bad">&gt; {err}</p>}
          {res && (
            <pre className="result">
              {res.added.map((t) => `+ ${t.name}  ${t.kind}\n`).join("")}
              {res.skipped.map((s) => `= ${s}  already monitored\n`).join("")}
              {res.errors.map((e) => `! ${e.line}  ${e.error}\n`).join("")}
              {`added ${res.added.length}  skipped ${res.skipped.length}  errors ${res.errors.length}`}
            </pre>
          )}
        </div>
      )}
    </section>
  );
}
