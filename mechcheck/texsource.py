"""Reading a LaTeX project the way a checker needs to see it.

Design note: every transformation *masks* characters with spaces instead of
deleting them.  ``raw``, ``code`` and ``prose`` therefore all have identical
lengths and identical offsets, so a regex match found in the prose view maps
back to an exact file/line/column in the original source with no bookkeeping.
"""

from __future__ import annotations

import os
import re
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Iterable

# Environments whose body must not be parsed as LaTeX at all.
VERBATIM_ENVS = {
    "verbatim", "verbatim*", "Verbatim", "Verbatim*", "lstlisting", "minted",
    "alltt", "semiverbatim", "comment", "filecontents", "filecontents*",
    "sagesilent", "asy", "pycode", "codeblock",
}

# Environments that are mathematics: masked out of the prose view.
MATH_ENVS = {
    "equation", "equation*", "align", "align*", "alignat", "alignat*", "gather",
    "gather*", "multline", "multline*", "flalign", "flalign*", "eqnarray",
    "eqnarray*", "displaymath", "math", "split", "IEEEeqnarray", "dmath",
}

FLOAT_ENVS = {"figure", "figure*", "table", "table*", "wrapfigure",
              "sidewaysfigure", "sidewaystable", "listing", "algorithm", "algorithm*"}

# Commands whose *entire* invocation carries no prose (masked away completely).
NON_PROSE_COMMANDS = {
    "label", "ref", "cref", "Cref", "autoref", "eqref", "pageref", "vref",
    "cite", "citep", "citet", "citeauthor", "citeyear", "citealp", "nocite",
    "includegraphics", "input", "include", "usepackage", "documentclass",
    "bibliography", "bibliographystyle", "addbibresource", "url", "href",
    "def", "newcommand", "renewcommand", "providecommand", "DeclareMathOperator",
    "setlength", "addtolength", "vspace", "hspace", "graphicspath", "geometry",
    "lstinputlisting", "toprule", "midrule", "bottomrule", "cmidrule", "hline",
    "centering", "raggedright", "noindent", "clearpage", "newpage", "pagebreak",
    "linebreak", "ccsdesc", "acmDOI", "acmISBN", "orcid", "affiliation",
    "email", "institution", "streetaddress", "postcode", "country", "city",
}

_CONTROL_WORD = re.compile(r"\\([A-Za-z@]+\*?|.)", re.DOTALL)


# --------------------------------------------------------------------------- #
# low-level scanning helpers
# --------------------------------------------------------------------------- #

def read_group(text: str, pos: int, open_ch: str = "{", close_ch: str = "}"):
    """Read a balanced group starting at ``pos``.

    Returns ``(inner_text, index_after_group)`` or ``None`` if ``text[pos]`` is
    not ``open_ch`` or the group never closes.
    """
    if pos >= len(text) or text[pos] != open_ch:
        return None
    depth = 0
    i = pos
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\" and i + 1 < n:
            i += 2
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return text[pos + 1:i], i + 1
        i += 1
    return None


def skip_space(text: str, pos: int) -> int:
    n = len(text)
    while pos < n and text[pos] in " \t\r\n":
        pos += 1
    return pos


@dataclass(frozen=True)
class Command:
    """One command invocation found in the flattened project text."""

    name: str
    start: int              # offset of the backslash
    end: int                # offset just past the last consumed argument
    args: tuple = ()
    opts: tuple = ()
    #: offsets of each mandatory argument's *content*
    arg_spans: tuple = ()

    def arg(self, i: int = 0, default: str = "") -> str:
        return self.args[i] if i < len(self.args) else default

    def opt(self, i: int = 0, default: str = "") -> str:
        return self.opts[i] if i < len(self.opts) else default


@dataclass(frozen=True)
class Environment:
    name: str
    start: int              # offset of \begin
    body_start: int
    body_end: int           # offset of \end
    end: int
    opts: tuple = ()

    def body(self, text: str) -> str:
        return text[self.body_start:self.body_end]


@dataclass
class SourceLine:
    file: str
    lineno: int
    raw: str
    code: str
    verbatim: bool = False
    #: offset of this line's first character inside ``TexProject.text``
    offset: int = 0


@dataclass
class TexFile:
    path: str               # project-relative, forward slashes
    abspath: str
    lines: list = field(default_factory=list)
    missing: bool = False


# --------------------------------------------------------------------------- #
# masking
# --------------------------------------------------------------------------- #

_MASK = " "


def _mask(s: str) -> str:
    """Replace every character with a space, preserving newlines and length."""
    return "".join("\n" if c == "\n" else _MASK for c in s)


def strip_comments_line(line: str) -> str:
    """Mask the comment part of a single line, keeping length identical."""
    out = []
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if c == "\\" and i + 1 < n:
            out.append(line[i:i + 2])
            i += 2
            continue
        if c == "%":
            out.append(_MASK * (n - i))
            break
        out.append(c)
        i += 1
    return "".join(out)


_VERB_INLINE = re.compile(r"\\(?:verb\*?|lstinline|mintinline)\s*(\{[^}]*\})?(.)")


def _mask_inline_verb(line: str) -> str:
    r"""Mask ``\verb|...|`` bodies so their % and braces do not confuse us."""
    out = line
    for m in list(_VERB_INLINE.finditer(line)):
        delim = m.group(2)
        if delim is None or delim.isalnum() or delim == "{":
            continue
        close = out.find(delim, m.end())
        if close == -1:
            continue
        span = out[m.start():close + 1]
        out = out[:m.start()] + _mask(span) + out[close + 1:]
    return out


_BEGIN_ENV = re.compile(r"\\begin\s*\{([^}]*)\}")
_END_ENV = re.compile(r"\\end\s*\{([^}]*)\}")


# --------------------------------------------------------------------------- #
# the project
# --------------------------------------------------------------------------- #

class TexProject:
    """A flattened, comment-stripped view of a multi-file LaTeX project."""

    def __init__(self, root: str, main: str) -> None:
        self.root = os.path.abspath(root)
        self.main = main
        self.files: list = []
        self.lines: list = []
        self.text: str = ""
        self.prose: str = ""
        self.missing_inputs: list = []
        self._line_offsets: list = []
        self._by_path: dict = {}
        self._cmd_cache: dict = {}
        self._env_cache: dict = {}

    # -- construction ------------------------------------------------------ #

    @classmethod
    def load(cls, root: str, main: str | None = None, encoding: str = "utf-8") -> "TexProject":
        root = os.path.abspath(root)
        main = main or find_main_document(root) or "main.tex"
        proj = cls(root, main)
        proj._read_file(main, seen=set(), encoding=encoding)
        proj._finalise()
        return proj

    def _resolve(self, path: str):
        r"""Resolve an \input target to a project-relative path that exists."""
        cand = path.strip().strip('"').replace("\\", "/")
        options = [cand]
        if not cand.lower().endswith(".tex"):
            options.append(cand + ".tex")
        for opt in options:
            full = os.path.normpath(os.path.join(self.root, opt))
            if os.path.isfile(full):
                return os.path.relpath(full, self.root).replace(os.sep, "/")
        return None

    def _read_file(self, relpath: str, seen: set, encoding: str, _depth: int = 0) -> None:
        if _depth > 24 or relpath in seen:
            return
        seen.add(relpath)
        abspath = os.path.normpath(os.path.join(self.root, relpath))
        tf = TexFile(path=relpath, abspath=abspath)
        self.files.append(tf)
        self._by_path[relpath] = tf
        try:
            with open(abspath, "r", encoding=encoding, errors="replace") as fh:
                raw_lines = fh.read().split("\n")
        except OSError:
            tf.missing = True
            return

        verbatim_env = None
        for i, raw in enumerate(raw_lines, start=1):
            raw = raw.rstrip("\r")
            if verbatim_env is not None:
                code = _mask(raw)
                m = _END_ENV.search(raw)
                if m and m.group(1).strip() == verbatim_env:
                    verbatim_env = None
                    code = raw  # keep the \end{...} visible to the parser
                tf.lines.append(SourceLine(relpath, i, raw, code, verbatim=True))
                continue

            code = _mask_inline_verb(raw)
            code = strip_comments_line(code)
            tf.lines.append(SourceLine(relpath, i, raw, code))

            mb = _BEGIN_ENV.search(code)
            if mb and mb.group(1).strip() in VERBATIM_ENVS:
                verbatim_env = mb.group(1).strip()

            for child in self._child_inputs(code):
                resolved = self._resolve(child)
                if resolved:
                    self._read_file(resolved, seen, encoding, _depth + 1)
                elif not _looks_like_variable(child):
                    self.missing_inputs.append((relpath, i, child))

    @staticmethod
    def _child_inputs(code: str) -> list:
        out = []
        for m in re.finditer(r"\\(input|include|subfile|subfileinclude|includestandalone)\s*\{", code):
            grp = read_group(code, m.end() - 1)
            if grp:
                out.append(grp[0])
        for m in re.finditer(r"\\(subimport|import)\*?\s*\{", code):
            g1 = read_group(code, m.end() - 1)
            if not g1:
                continue
            g2 = read_group(code, skip_space(code, g1[1]))
            if g2:
                out.append(g1[0].rstrip("/") + "/" + g2[0])
        return out

    def _finalise(self) -> None:
        chunks = []
        offset = 0
        for tf in self.files:
            for ln in tf.lines:
                ln.offset = offset
                self.lines.append(ln)
                self._line_offsets.append(offset)
                chunks.append(ln.code)
                offset += len(ln.code) + 1  # +1 for the joining newline
        self.text = "\n".join(chunks)
        self.prose = build_prose_view(self.text)

    # -- location mapping -------------------------------------------------- #

    def locate(self, offset: int) -> tuple:
        """Map a ``self.text`` offset to ``(file, lineno, column)`` (1-based col)."""
        if not self._line_offsets:
            return (self.main, 1, 1)
        ln = self.line_at(offset)
        return (ln.file, ln.lineno, offset - ln.offset + 1)

    def line_at(self, offset: int) -> SourceLine:
        idx = bisect_right(self._line_offsets, offset) - 1
        idx = max(0, min(idx, len(self.lines) - 1))
        return self.lines[idx]

    def excerpt(self, offset: int, width: int = 90) -> str:
        ln = self.line_at(offset)
        s = ln.raw.strip()
        return s if len(s) <= width else s[:width - 1] + "\u2026"

    # -- queries ----------------------------------------------------------- #

    def commands(self, name: str, max_args: int = 1, source: str | None = None) -> list:
        r"""All invocations of ``\name`` with up to ``max_args`` brace arguments."""
        key = (name, max_args)
        if source is None and key in self._cmd_cache:
            return self._cmd_cache[key]
        text = self.text if source is None else source
        out = parse_commands(text, name, max_args)
        if source is None:
            self._cmd_cache[key] = out
        return out

    def any_commands(self, names: Iterable, max_args: int = 1) -> list:
        out = []
        for n in names:
            out.extend(self.commands(n, max_args))
        out.sort(key=lambda c: c.start)
        return out

    def environments(self, name: str) -> list:
        if name in self._env_cache:
            return self._env_cache[name]
        out = parse_environments(self.text, name)
        self._env_cache[name] = out
        return out

    def floats(self) -> list:
        out = []
        for env in FLOAT_ENVS:
            out.extend(self.environments(env))
        out.sort(key=lambda e: e.start)
        return out

    def bib_files(self) -> list:
        """Resolved .bib paths referenced by the project."""
        names = []
        for cmd in self.any_commands(["bibliography", "addbibresource"], 1):
            for part in cmd.arg(0).split(","):
                part = part.strip()
                if part:
                    names.append(part)
        out = []
        for n in names:
            cand = n if n.lower().endswith(".bib") else n + ".bib"
            full = os.path.normpath(os.path.join(self.root, cand))
            if os.path.isfile(full):
                out.append(full)
        if not out:  # projects that let latexmk/biblatex find the .bib
            for dirpath, dirnames, filenames in os.walk(self.root):
                dirnames[:] = [d for d in dirnames
                               if not d.startswith(".") and d not in {"node_modules", "build", "out"}]
                for fn in filenames:
                    if fn.lower().endswith(".bib"):
                        out.append(os.path.join(dirpath, fn))
        seen = set()
        uniq = []
        for p in out:
            key = os.path.normcase(os.path.abspath(p))
            if key not in seen:
                seen.add(key)
                uniq.append(p)
        return uniq

    def documentclass(self) -> tuple:
        cmds = self.commands("documentclass", 1)
        if not cmds:
            return ("", [])
        c = cmds[0]
        opts = [o.strip() for o in c.opt(0).split(",") if o.strip()]
        return (c.arg(0).strip(), opts)

    def packages(self) -> dict:
        out: dict = {}
        for c in self.commands("usepackage", 1):
            opts = [o.strip() for o in c.opt(0).split(",") if o.strip()]
            for name in c.arg(0).split(","):
                name = name.strip()
                if name:
                    out.setdefault(name, []).extend(opts)
        return out

    def is_thesis_like(self) -> bool:
        cls, _ = self.documentclass()
        return cls.lower() in {"book", "report", "scrbook", "scrreprt", "memoir", "thesis"} or bool(
            self.commands("chapter", 1))

    def rel(self, path: str) -> str:
        try:
            return os.path.relpath(path, self.root).replace(os.sep, "/")
        except ValueError:
            return path


def _looks_like_variable(name: str) -> bool:
    return "\\" in name or "#" in name


# --------------------------------------------------------------------------- #
# parsing primitives usable without a project (handy in tests)
# --------------------------------------------------------------------------- #

def parse_commands(text: str, name: str, max_args: int = 1) -> list:
    r"""Find ``\name`` invocations and their ``[opt]``/``{arg}`` arguments."""
    out = []
    esc = re.escape(name)
    # A trailing letter must not continue the control word (\ref must not match \reflect).
    pattern = re.compile(r"\\" + esc + (r"(?![A-Za-z@])" if name[-1:].isalpha() else ""))
    for m in pattern.finditer(text):
        # An escaped backslash before it means this is not a control word.
        if _is_escaped(text, m.start()):
            continue
        pos = m.end()
        if pos < len(text) and text[pos] == "*":
            pos += 1
        opts = []
        args = []
        spans = []
        while len(args) < max_args:
            nxt = skip_space(text, pos)
            if nxt < len(text) and text[nxt] == "[":
                grp = read_group(text, nxt, "[", "]")
                if not grp:
                    break
                opts.append(grp[0])
                pos = grp[1]
                continue
            if nxt < len(text) and text[nxt] == "{":
                grp = read_group(text, nxt, "{", "}")
                if not grp:
                    break
                args.append(grp[0])
                spans.append((nxt + 1, nxt + 1 + len(grp[0])))
                pos = grp[1]
                continue
            break
        out.append(Command(name=name, start=m.start(), end=pos, args=tuple(args),
                           opts=tuple(opts), arg_spans=tuple(spans)))
    return out


def _is_escaped(text: str, pos: int) -> bool:
    """True if the backslash at ``pos`` is itself escaped by a preceding one."""
    n = 0
    i = pos - 1
    while i >= 0 and text[i] == "\\":
        n += 1
        i -= 1
    return n % 2 == 1


def parse_environments(text: str, name: str) -> list:
    r"""Find ``\begin{name} ... \end{name}`` blocks, respecting nesting."""
    out = []
    begin_re = re.compile(r"\\begin\s*\{" + re.escape(name) + r"\}")
    end_re = re.compile(r"\\end\s*\{" + re.escape(name) + r"\}")
    starts = [m for m in begin_re.finditer(text) if not _is_escaped(text, m.start())]
    ends = [m for m in end_re.finditer(text) if not _is_escaped(text, m.start())]
    stack = []
    events = sorted([(m.start(), 0, m.end(), m) for m in starts]
                    + [(m.start(), 1, m.end(), m) for m in ends])
    for _pos, kind, _e, m in events:
        if kind == 0:
            stack.append(m)
        elif stack:
            b = stack.pop()
            pos = b.end()
            opts = []
            while True:
                nxt = skip_space(text, pos)
                if nxt < len(text) and text[nxt] == "[":
                    grp = read_group(text, nxt, "[", "]")
                    if not grp:
                        break
                    opts.append(grp[0])
                    pos = grp[1]
                    continue
                break
            out.append(Environment(name=name, start=b.start(), body_start=pos,
                                   body_end=m.start(), end=m.end(), opts=tuple(opts)))
    out.sort(key=lambda e: e.start)
    return out


def build_prose_view(text: str) -> str:
    """Mask maths, non-prose commands and control words; keep readable text.

    Same length as ``text``, so offsets are interchangeable.
    """
    buf = list(text)

    def blank(a: int, b: int) -> None:
        for i in range(max(0, a), min(len(buf), b)):
            if buf[i] != "\n":
                buf[i] = " "

    # 1. display and inline maths
    for m in re.finditer(r"\\\[.*?\\\]|\\\(.*?\\\)", text, re.DOTALL):
        blank(m.start(), m.end())
    for m in re.finditer(r"(?<!\\)\$\$.*?(?<!\\)\$\$|(?<!\\)\$.*?(?<!\\)\$", text, re.DOTALL):
        blank(m.start(), m.end())
    for env in MATH_ENVS:
        for e in parse_environments(text, env):
            blank(e.start, e.end)
    for env in ("tabular", "tabular*", "tabularx", "longtable", "tikzpicture", "axis"):
        for e in parse_environments(text, env):
            blank(e.body_start, e.body_end)

    # 2. commands that carry no prose at all
    for name in NON_PROSE_COMMANDS:
        for c in parse_commands(text, name, max_args=3):
            blank(c.start, c.end)

    # 3. remaining control words and environment delimiters: keep their argument
    #    text but drop the markup itself.
    for m in re.finditer(r"\\(?:begin|end)\s*\{[^}]*\}", text):
        blank(m.start(), m.end())
    for m in _CONTROL_WORD.finditer(text):
        if _is_escaped(text, m.start()):
            continue
        blank(m.start(), m.end())
    for i, ch in enumerate(buf):
        if ch in "{}&~^_":
            buf[i] = " "
    return "".join(buf)


# --------------------------------------------------------------------------- #
# project discovery
# --------------------------------------------------------------------------- #

_MAIN_HINTS = ("main.tex", "thesis.tex", "paper.tex", "root.tex", "master.tex",
               "document.tex", "manuscript.tex", "dissertation.tex", "report.tex")


def find_main_document(root: str):
    r"""Pick the main .tex file the way latexmk/Overleaf would.

    Preference order: files containing ``\documentclass`` and ``\begin{document}``,
    tie-broken by conventional names, then by shallowest path, then by size.
    """
    candidates = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".")
                       and d not in {"node_modules", "build", "out", "_minted", "__pycache__"}]
        for fn in filenames:
            if not fn.lower().endswith(".tex"):
                continue
            full = os.path.join(dirpath, fn)
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as fh:
                    head = fh.read(200_000)
            except OSError:
                continue
            if "\\documentclass" not in head or "\\begin{document}" not in head:
                continue
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            hint = _MAIN_HINTS.index(fn.lower()) if fn.lower() in _MAIN_HINTS else len(_MAIN_HINTS)
            depth = rel.count("/")
            candidates.append((hint, depth, -len(head), rel))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][3]
