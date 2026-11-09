export type Status = "NOMINAL" | "DEGRADED" | "DOWN";

export interface Target {
  name: string; host: string; kind: "icmp" | "tcp" | "dns"; port: number | null;
  status: Status;
  last: number | null; avg: number | null; min: number | null; max: number | null;
  jitter: number; loss: number;
  samples: (number | null)[];
}

export interface NetEvent {
  ts: number; target: string; old: string; new: string; detail: string;
}

export interface Snapshot {
  ts: number; uptime: number; host: string; interval: number;
  net: { rx_bps: number; tx_bps: number; errin: number; errout: number; dropin: number; dropout: number };
  targets: Target[];
  events: NetEvent[];
}

export interface Bucket { t: number; avg: number | null; max: number | null; n: number; lost: number }

export interface ImportResult {
  added: { name: string; host: string; kind: string; port?: number }[];
  skipped: string[];
  errors: { line: string; error: string }[];
}
