"""SQLite persistence: probe samples (history) and status-change events."""
import sqlite3
import threading
import time


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS samples(
                    ts REAL NOT NULL, target TEXT NOT NULL, ms REAL);
                CREATE INDEX IF NOT EXISTS ix_samples ON samples(target, ts);
                CREATE TABLE IF NOT EXISTS events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL, target TEXT NOT NULL,
                    old TEXT, new TEXT NOT NULL, detail TEXT);
            """)

    def add_samples(self, rows):
        if not rows:
            return
        with self.lock:
            self.db.executemany("INSERT INTO samples VALUES (?,?,?)", rows)
            self.db.commit()

    def recent(self, target: str, n: int):
        with self.lock:
            rows = self.db.execute(
                "SELECT ms FROM samples WHERE target=? ORDER BY ts DESC LIMIT ?",
                (target, n)).fetchall()
        return [r[0] for r in reversed(rows)]

    def history(self, target: str, minutes: int, bucket_s: int):
        since = time.time() - minutes * 60
        with self.lock:
            rows = self.db.execute(
                "SELECT CAST(ts/? AS INTEGER)*? AS b, AVG(ms), MAX(ms), COUNT(*), "
                "SUM(ms IS NULL) FROM samples WHERE target=? AND ts>? "
                "GROUP BY b ORDER BY b", (bucket_s, bucket_s, target, since)).fetchall()
        return [{"t": b, "avg": a, "max": m, "n": n, "lost": l or 0} for b, a, m, n, l in rows]

    def add_event(self, ev: dict):
        with self.lock:
            self.db.execute(
                "INSERT INTO events(ts,target,old,new,detail) VALUES (?,?,?,?,?)",
                (ev["ts"], ev["target"], ev["old"], ev["new"], ev["detail"]))
            self.db.commit()

    def events(self, limit: int = 50):
        with self.lock:
            rows = self.db.execute(
                "SELECT ts,target,old,new,detail FROM events ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(zip(("ts", "target", "old", "new", "detail"), r)) for r in rows]

    def delete_target(self, target: str):
        with self.lock:
            self.db.execute("DELETE FROM samples WHERE target=?", (target,))
            self.db.commit()

    def prune(self, days: int):
        with self.lock:
            cut = time.time() - days * 86400
            self.db.execute("DELETE FROM samples WHERE ts<?", (cut,))
            self.db.execute("DELETE FROM events WHERE ts<?", (cut,))
            self.db.commit()
