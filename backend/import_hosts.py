"""
Bulk-import hosts from a text / csv / json file.

    python import_hosts.py hosts.txt                # POST to the running backend
    python import_hosts.py hosts.txt --dry-run      # parse only, change nothing
    python import_hosts.py hosts.txt --offline      # edit targets.json directly (restart backend after)
    python import_hosts.py hosts.txt --api http://192.168.1.50:8000

File syntax is documented at the top of hosts.py and in the README.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from hosts import parse_bulk

TARGETS_FILE = Path(__file__).parent / "targets.json"


def report(new, skipped, errors):
    for t in new:
        port = f":{t['port']}" if t.get("port") else ""
        print(f"  + {t['name']:<28} {t['kind']}://{t['host']}{port}")
    for s in skipped:
        print(f"  = {s}  (already monitored)")
    for e in errors:
        print(f"  ! {e['line']}  ->  {e['error']}")
    print(f"\nadded {len(new)}, skipped {len(skipped)}, errors {len(errors)}")


def main():
    ap = argparse.ArgumentParser(description="netmon bulk host import")
    ap.add_argument("file")
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--offline", action="store_true", help="edit targets.json directly")
    ap.add_argument("--dry-run", action="store_true", help="parse and report only")
    a = ap.parse_args()

    text = Path(a.file).read_text(encoding="utf-8-sig")
    existing = json.loads(TARGETS_FILE.read_text()) if TARGETS_FILE.exists() else []

    if a.dry_run or a.offline:
        new, skipped, errors = parse_bulk(text, existing)
        report(new, skipped, errors)
        if a.offline and not a.dry_run and new:
            TARGETS_FILE.write_text(json.dumps(existing + new, indent=2))
            print("targets.json updated - restart the backend to pick it up")
        return 1 if errors else 0

    req = urllib.request.Request(
        f"{a.api}/api/targets/import", data=json.dumps({"text": text}).encode(),
        headers={"Content-Type": "application/json"})
    try:
        res = json.load(urllib.request.urlopen(req, timeout=10))
    except urllib.error.URLError as e:
        print(f"backend unreachable at {a.api} ({e.reason}).")
        print("start it, or re-run with --offline to edit targets.json directly.")
        return 2
    report(res["added"], res["skipped"], res["errors"])
    return 1 if res["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
