import { useEffect, useRef, useState } from "react";
import type { Snapshot } from "./types";

import { WS_URL } from "./api";

export function useTelemetry() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [link, setLink] = useState<"CONNECTING" | "ONLINE" | "RETRY">("CONNECTING");
  const retry = useRef(0);

  useEffect(() => {
    let ws: WebSocket;
    let timer: number;
    let dead = false;

    const open = () => {
      ws = new WebSocket(WS_URL);
      ws.onopen = () => { retry.current = 0; setLink("ONLINE"); };
      ws.onmessage = (e) => setSnap(JSON.parse(e.data));
      ws.onclose = () => {
        if (dead) return;
        setLink("RETRY");
        timer = window.setTimeout(open, Math.min(1000 * 2 ** retry.current++, 8000));
      };
    };
    open();
    return () => { dead = true; clearTimeout(timer); ws?.close(); };
  }, []);

  return { snap, link };
}
