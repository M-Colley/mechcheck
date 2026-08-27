"""A deliberately tiny YAML subset parser.

``mechcheck.yaml`` is read by three things: this Python package, GitHub Actions,
and ``mechcheck.sty`` running inside Overleaf's LaTeX compiler.  The LaTeX side
can only realistically parse a *restricted* subset, so the subset -- not full
YAML -- is the contract:

* two-space indentation, no tabs
* ``key: value`` mappings, nested by indentation
* ``- item`` sequences of scalars, and sequences of one-line ``key: value`` maps
* scalars: bare, 'single' or "double" quoted, ``true``/``false``/``null``, numbers
* ``#`` comments, blank lines
* inline flow lists ``[a, b, c]`` on one line

If PyYAML is installed we use it (a strict superset), but nothing here depends
on that.  Keep any config you write inside the subset above, or the
Overleaf-side checks will silently fall back to their defaults.
"""

from __future__ import annotations

import re

_INT = re.compile(r"^[+-]?\d+$")
_FLOAT = re.compile(r"^[+-]?\d+\.\d+$")


# --------------------------------------------------------------------------- #
# scalars
# --------------------------------------------------------------------------- #

def _scalar(raw: str):
    s = raw.strip()
    if not s:
        return ""
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        return s[1:-1]
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        return [_scalar(p) for p in _split_flow(inner)] if inner else []
    low = s.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "~", "none"):
        return None
    if _INT.match(s):
        return int(s)
    if _FLOAT.match(s):
        return float(s)
    return s


def _split_flow(inner: str) -> list:
    out, buf, quote = [], [], None
    for ch in inner:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
            buf.append(ch)
            continue
        if ch == ",":
            out.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    if buf:
        out.append("".join(buf))
    return [p for p in (p.strip() for p in out) if p != ""]


def _strip_comment(line: str) -> str:
    out, quote = [], None
    for i, ch in enumerate(line):
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
            out.append(ch)
            continue
        if ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


def _split_key(body: str):
    """Split ``key: value`` outside quotes. Returns ``(key, value)`` or None."""
    quote = None
    for i, ch in enumerate(body):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
            continue
        if ch == ":" and (i + 1 == len(body) or body[i + 1] in " \t"):
            return body[:i].strip().strip("'\""), body[i + 1:].strip()
    return None


# --------------------------------------------------------------------------- #
# recursive-descent over indentation
# --------------------------------------------------------------------------- #

def _prepare(text: str) -> list:
    """Return ``[(indent, body), ...]`` for non-empty, non-comment lines."""
    rows = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        line = _strip_comment(raw.replace("\t", "  "))
        if not line.strip():
            continue
        rows.append((len(line) - len(line.lstrip(" ")), line.strip()))
    return rows


def _parse_block(rows: list, i: int, indent: int):
    """Parse every row at ``indent`` starting at ``i``. Returns ``(value, i)``."""
    if i >= len(rows):
        return {}, i
    if rows[i][1].startswith("- "):
        return _parse_seq(rows, i, indent)
    return _parse_map(rows, i, indent)


def _parse_map(rows: list, i: int, indent: int):
    out: dict = {}
    while i < len(rows):
        ind, body = rows[i]
        if ind < indent:
            break
        if ind > indent:  # stray over-indent: skip rather than fail
            i += 1
            continue
        kv = _split_key(body)
        if kv is None:
            i += 1
            continue
        key, value = kv
        if value == "":
            child_i = i + 1
            if child_i < len(rows) and rows[child_i][0] > ind:
                out[key], i = _parse_block(rows, child_i, rows[child_i][0])
            else:
                out[key] = {}
                i += 1
        else:
            out[key] = _scalar(value)
            i += 1
    return out, i


def _parse_seq(rows: list, i: int, indent: int):
    out: list = []
    while i < len(rows):
        ind, body = rows[i]
        if ind < indent or not body.startswith("- "):
            break
        if ind > indent:
            i += 1
            continue
        item = body[2:].strip()
        kv = _split_key(item) if not item.startswith(("'", '"', "[")) else None
        if kv is not None:
            entry = {}
            key, value = kv
            entry[key] = _scalar(value) if value else {}
            i += 1
            # further keys of the same mapping item, indented past the dash
            while i < len(rows) and rows[i][0] > indent and not rows[i][1].startswith("- "):
                sub = _split_key(rows[i][1])
                if sub:
                    entry[sub[0]] = _scalar(sub[1])
                i += 1
            out.append(entry)
        else:
            out.append(_scalar(item))
            i += 1
    return out, i


def loads_builtin(text: str) -> dict:
    """Parse with the built-in subset parser, ignoring PyYAML.

    Exposed so the test-suite can exercise the parser that ships to users who
    have no third-party packages -- otherwise it would only ever be tested on
    machines where PyYAML happens to be missing.
    """
    rows = _prepare(text)
    if not rows:
        return {}
    value, _ = _parse_block(rows, 0, rows[0][0])
    return value if isinstance(value, dict) else {}


def loads(text: str) -> dict:
    """Parse the subset. Never raises on malformed input; bad lines are skipped."""
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except ImportError:
        pass
    except Exception:
        return {}
    return loads_builtin(text)


def load(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return loads(fh.read())
    except OSError:
        return {}


def dumps(data, indent: int = 0) -> str:
    """Emit the same subset (used by ``mechcheck init``)."""
    pad = " " * indent
    lines = []
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, dict) and v:
                lines.append(f"{pad}{k}:")
                lines.append(dumps(v, indent + 2))
            elif isinstance(v, list) and v:
                lines.append(f"{pad}{k}:")
                for item in v:
                    lines.append(f"{pad}  - {_emit_scalar(item)}")
            elif isinstance(v, (dict, list)):
                lines.append(f"{pad}{k}: []" if isinstance(v, list) else f"{pad}{k}:")
            else:
                lines.append(f"{pad}{k}: {_emit_scalar(v)}")
    return "\n".join(l for l in lines if l != "")


def _emit_scalar(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if s == "" or s[0] in "[{'\"#-" or ": " in s or s.strip() != s:
        return "'" + s.replace("'", "''") + "'"
    return s
