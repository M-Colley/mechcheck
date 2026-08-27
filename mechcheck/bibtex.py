"""A tolerant BibTeX/BibLaTeX reader.

Deliberately tolerant: the point is to *find problems in* .bib files, so the
parser must survive the very malformedness it is meant to report.  It records a
line number for every entry and every field so findings can point at the exact
line a student needs to open.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

_ENTRY_START = re.compile(r"@(?P<type>[A-Za-z]+)\s*[{(]", re.MULTILINE)

_LATEX_ACCENTS = {
    r"\"a": "ä", r"\"o": "ö", r"\"u": "ü", r"\"A": "Ä", r"\"O": "Ö", r"\"U": "Ü",
    r"\ss": "ß", r"\'e": "é", r"\`e": "è", r"\^e": "ê", r"\'a": "á", r"\`a": "à",
    r"\'o": "ó", r"\'u": "ú", r"\'i": "í", r"\~n": "ñ", r"\c c": "ç", r"\v s": "š",
    r"\o": "ø", r"\aa": "å", r"\ae": "æ",
}

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


@dataclass
class BibEntry:
    key: str
    type: str
    fields: dict = field(default_factory=dict)
    field_lines: dict = field(default_factory=dict)
    line: int = 0
    file: str = ""
    raw: str = ""

    def get(self, name: str, default: str = "") -> str:
        return self.fields.get(name.lower(), default)

    def line_of(self, name: str) -> int:
        return self.field_lines.get(name.lower(), self.line)

    @property
    def year(self):
        for name in ("year", "date"):
            value = self.get(name)
            m = re.search(r"(1[6-9]\d{2}|20\d{2})", value)
            if m:
                return int(m.group(1))
        return None

    @property
    def doi(self) -> str:
        doi = self.get("doi").strip()
        if not doi:
            url = self.get("url")
            m = re.search(r"(?:doi\.org/|dx\.doi\.org/)(10\.\S+)", url)
            doi = m.group(1) if m else ""
        doi = doi.replace("\\_", "_").replace("{", "").replace("}", "").strip()
        doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.I)
        return doi.rstrip(".")

    @property
    def authors(self) -> list:
        raw = self.get("author") or self.get("editor")
        if not raw:
            return []
        return [a.strip() for a in re.split(r"\s+and\s+", raw, flags=re.IGNORECASE) if a.strip()]

    def author_surnames(self) -> list:
        out = []
        for a in self.authors:
            a = clean_latex(a)
            if "," in a:
                out.append(a.split(",")[0].strip())
            else:
                parts = a.split()
                out.append(parts[-1] if parts else "")
        return [s for s in out if s]

    @property
    def title(self) -> str:
        return clean_latex(self.get("title"))

    @property
    def venue(self) -> str:
        for name in ("booktitle", "journal", "journaltitle", "publisher", "howpublished"):
            value = self.get(name)
            if value:
                return clean_latex(value)
        return ""

    def is_preprint(self) -> bool:
        blob = " ".join([self.get("journal"), self.get("booktitle"), self.get("archiveprefix"),
                         self.get("eprint"), self.get("publisher"), self.get("note"),
                         self.get("url"), self.type]).lower()
        return any(k in blob for k in ("arxiv", "preprint", "biorxiv", "psyarxiv", "ssrn", "osf.io"))

    @property
    def arxiv_id(self) -> str:
        for source in (self.get("eprint"), self.get("url"), self.get("note"), self.get("journal")):
            m = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", source or "")
            if m:
                return m.group(1)
            m = re.search(r"arxiv[:/]\s*([a-z\-]+/\d{7})", source or "", re.I)
            if m:
                return m.group(1)
        return ""


def clean_latex(text: str) -> str:
    """Best-effort plain text from a BibTeX field, for comparison purposes."""
    if not text:
        return ""
    out = text
    for tex, ch in _LATEX_ACCENTS.items():
        out = out.replace("{" + tex + "}", ch).replace(tex + " ", ch).replace(tex, ch)
    out = re.sub(r"\\[a-zA-Z]+\s*", " ", out)
    out = out.replace("{", "").replace("}", "").replace("\\", "")
    out = out.replace("~", " ").replace("--", "-")
    out = unicodedata.normalize("NFKC", out)
    return re.sub(r"\s+", " ", out).strip()


def normalise_title(text: str) -> str:
    """Aggressively normalised title, for fuzzy comparison against an API result."""
    s = clean_latex(text).lower()
    s = re.sub(r"<[^>]+>", " ", s)          # Crossref titles carry HTML/MathML
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def similarity(a: str, b: str) -> float:
    """Token-level Jaccard blended with sequence ratio; 0..1, order-tolerant."""
    from difflib import SequenceMatcher

    na, nb = normalise_title(a), normalise_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = set(na.split()), set(nb.split())
    jac = len(ta & tb) / len(ta | tb) if (ta | tb) else 0.0
    seq = SequenceMatcher(None, na, nb).ratio()
    return round(0.5 * jac + 0.5 * seq, 4)


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #

def parse_file(path: str) -> list:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return []
    return parse(text, path)


def parse(text: str, path: str = "") -> list:
    entries = []
    line_starts = _line_index(text)
    for m in _ENTRY_START.finditer(text):
        etype = m.group("type").lower()
        if etype in ("comment", "preamble"):
            continue
        opener = text[m.end() - 1]
        closer = "}" if opener == "{" else ")"
        body, end = _read_until_close(text, m.end() - 1, opener, closer)
        if body is None:
            continue
        raw = text[m.start():end]
        line = _line_of(line_starts, m.start())
        if etype == "string":
            continue
        key, fields, field_offsets = _parse_body(body)
        field_lines = {name: _line_of(line_starts, m.end() - 1 + off)
                       for name, off in field_offsets.items()}
        entries.append(BibEntry(key=key, type=etype, fields=fields, field_lines=field_lines,
                                line=line, file=path, raw=raw))
    return entries


def _line_index(text: str) -> list:
    out, pos = [0], 0
    for line in text.split("\n"):
        pos += len(line) + 1
        out.append(pos)
    return out


def _line_of(starts: list, offset: int) -> int:
    from bisect import bisect_right

    return max(1, bisect_right(starts, offset))


def _read_until_close(text: str, pos: int, opener: str, closer: str):
    depth = 0
    i = pos
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return text[pos + 1:i], i + 1
        i += 1
    return None, n


def _parse_body(body: str):
    """Split ``key, field = {value}, ...`` tolerating missing commas and braces."""
    comma = _find_top_level(body, ",")
    if comma == -1:
        return body.strip(), {}, {}
    key = body[:comma].strip()
    rest = body[comma + 1:]
    fields = {}
    offsets = {}
    base = comma + 1
    pos = 0
    n = len(rest)
    while pos < n:
        eq = _find_top_level(rest, "=", pos)
        if eq == -1:
            break
        name = rest[pos:eq].strip().strip(",").strip().lower()
        value, after = _read_value(rest, eq + 1)
        if name and name.isascii() and re.match(r"^[a-z][a-z0-9_\-:]*$", name):
            fields[name] = value
            offsets[name] = base + pos
        pos = after
        nxt = _find_top_level(rest, ",", pos)
        pos = (nxt + 1) if nxt != -1 else n
    return key, fields, offsets


def _find_top_level(text: str, ch: str, start: int = 0) -> int:
    depth = 0
    quote = False
    i = start
    while i < len(text):
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == '"' and depth == 0:
            quote = not quote
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == ch and depth == 0 and not quote:
            return i
        i += 1
    return -1


def _read_value(text: str, pos: int):
    n = len(text)
    while pos < n and text[pos] in " \t\r\n":
        pos += 1
    parts = []
    while pos < n:
        if text[pos] == "{":
            depth, i = 0, pos
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            parts.append(text[pos + 1:i])
            pos = i + 1
        elif text[pos] == '"':
            i = pos + 1
            depth = 0
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                elif text[i] == '"' and depth == 0:
                    break
                i += 1
            parts.append(text[pos + 1:i])
            pos = i + 1
        else:
            i = pos
            while i < n and text[i] not in ",}#\n":
                i += 1
            token = text[pos:i].strip()
            if token:
                parts.append(_MONTH_NAMES.get(token.lower(), token))
            pos = i
        while pos < n and text[pos] in " \t\r\n":
            pos += 1
        if pos < n and text[pos] == "#":
            pos += 1
            while pos < n and text[pos] in " \t\r\n":
                pos += 1
            continue
        break
    return re.sub(r"\s+", " ", "".join(parts)).strip(), pos


_MONTH_NAMES = {name: name for name in _MONTHS}


def load_all(paths) -> list:
    out = []
    for p in paths:
        out.extend(parse_file(p))
    return out
