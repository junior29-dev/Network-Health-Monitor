"""
Host line parser shared by the API, the dashboard import box, and the CLI.

Accepted forms (one per line, or separated by spaces / commas):

    1.1.1.1                    no port        -> ICMP ping
    router.lan                 no port        -> ICMP ping
    github.com:443             with port      -> TCP connect
    [2001:db8::1]:443          IPv6 + port    -> TCP connect
    2001:4860:4860::8888       bare IPv6      -> ICMP ping
    tcp://10.0.0.5:22          explicit scheme
    icmp://10.0.0.1            explicit scheme
    dns://example.com          DNS resolve time
    nas=192.168.1.20:445       custom display name (name=target)
    # comment                  ignored (also trailing  " # comment")

A JSON array in targets.json format is accepted too.
"""
import ipaddress
import json
import re

SCHEMES = {"icmp", "tcp", "dns"}
NAME_RE = re.compile(r"^[\w.\-:]{1,48}$")
HOST_RE = re.compile(
    r"^(?=.{1,253}$)[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)


def _valid_host(h: str) -> bool:
    try:
        ipaddress.ip_address(h)
        return True
    except ValueError:
        return bool(HOST_RE.match(h))


def _default_name(kind: str, host: str, port) -> str:
    if kind == "tcp":
        return f"{host}:{port}"
    if kind == "dns":
        return f"dns:{host}"
    return host


def build_target(kind, host, port=None, name=None) -> dict:
    kind = (kind or "").lower()
    if kind not in SCHEMES:
        raise ValueError(f"unknown kind '{kind}' (use icmp, tcp, dns)")
    if not _valid_host(host):
        raise ValueError(f"invalid host '{host}'")
    if port is not None:
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError(f"bad port '{port}' (1-65535)")
    if kind == "tcp" and port is None:
        raise ValueError("tcp needs a port, e.g. tcp://host:443")
    if kind in ("icmp", "dns") and port is not None:
        raise ValueError(f"{kind} does not use a port")
    if name is not None and not NAME_RE.match(name):
        raise ValueError(f"bad name '{name}' (letters, digits, . _ - : up to 48 chars)")
    t = {"name": name or _default_name(kind, host, port), "host": host, "kind": kind}
    if port is not None:
        t["port"] = port
    return t


def parse_token(tok: str) -> dict:
    s, name, kind = tok.strip(), None, None
    if "=" in s:
        name, s = (p.strip() for p in s.split("=", 1))
    if "://" in s:
        scheme, s = s.split("://", 1)
        kind = scheme.lower()
        if kind not in SCHEMES:
            raise ValueError(f"unknown scheme '{scheme}' (use icmp, tcp, dns)")
    s = s.rstrip("/")
    host, port = s, None
    if s.startswith("["):
        m = re.match(r"^\[([^\]]+)\](?::(\d+))?$", s)
        if not m:
            raise ValueError("bad IPv6 syntax, use [addr]:port")
        host, port = m.group(1), m.group(2)
    elif s.count(":") == 1:
        host, port = s.split(":")
    if port is not None:
        if not str(port).isdigit():
            raise ValueError(f"bad port '{port}'")
        port = int(port)
    if kind is None:
        kind = "tcp" if port is not None else "icmp"
    return build_target(kind, host, port, name)


def _key(t: dict):
    return (t["kind"], t["host"].lower(), t.get("port"))


def parse_bulk(text: str, existing: list[dict]):
    """Returns (new_targets, skipped_duplicates, errors)."""
    seen = {_key(t) for t in existing}
    names = {t["name"] for t in existing}
    new, skipped, errors = [], [], []

    def accept(t: dict, raw: str):
        if _key(t) in seen:
            skipped.append(raw)
            return
        base, n = t["name"], 2
        while t["name"] in names:
            t["name"] = f"{base}-{n}"
            n += 1
        seen.add(_key(t))
        names.add(t["name"])
        new.append(t)

    stripped = text.strip()
    if stripped.startswith("["):
        try:
            items = json.loads(stripped)
            for it in items:
                raw = json.dumps(it)
                try:
                    accept(build_target(it.get("kind"), it.get("host", ""), it.get("port"), it.get("name")), raw)
                except Exception as e:
                    errors.append({"line": raw, "error": str(e)})
            return new, skipped, errors
        except json.JSONDecodeError:
            pass  # fall through: probably an IPv6 line starting with [

    for line in text.splitlines():
        line = re.split(r"(?:^|\s)#", line)[0]
        for tok in re.split(r"[,\s]+", line):
            if not tok:
                continue
            try:
                accept(parse_token(tok), tok)
            except ValueError as e:
                errors.append({"line": tok, "error": str(e)})
    return new, skipped, errors
