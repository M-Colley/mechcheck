"""Core data model: findings, rules, and the registry.

Everything a rule needs is on :class:`RuleContext`; everything a rule produces
is a :class:`Finding`.  Rules never print, never exit, and never raise: a
crashing rule is caught by the runner and downgraded to an internal finding, so
one broken check can never block a student's submission.
"""

from __future__ import annotations

import dataclasses
import enum
import fnmatch
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Iterable, Iterator, Sequence

if TYPE_CHECKING:  # pragma: no cover
    from mechcheck.config import Config
    from mechcheck.texsource import TexProject


class Severity(enum.IntEnum):
    """Ordered so that ``max()`` picks the worst."""

    INFO = 10
    WARN = 20
    ERROR = 30
    #: Not a severity a finding can have: the threshold meaning "never fail".
    NEVER = 900

    @classmethod
    def parse(cls, value: object, default: "Severity" = None) -> "Severity":
        if isinstance(value, Severity):
            return value
        if isinstance(value, int):
            try:
                return cls(value)
            except ValueError:
                return cls.NEVER if value >= cls.ERROR else (default or cls.WARN)
        name = str(value or "").strip().upper()
        aliases = {
            "ERROR": cls.ERROR, "ERR": cls.ERROR, "FAIL": cls.ERROR, "BLOCK": cls.ERROR,
            "WARN": cls.WARN, "WARNING": cls.WARN,
            "INFO": cls.INFO, "NOTE": cls.INFO, "HINT": cls.INFO,
            "NEVER": cls.NEVER, "OFF": cls.NEVER, "NONE": cls.NEVER,
        }
        if name in aliases:
            return aliases[name]
        if default is not None:
            return default
        raise ValueError(f"unknown severity: {value!r}")

    @property
    def label(self) -> str:
        return self.name.lower()


class Category(str, enum.Enum):
    STRUCTURE = "structure"
    FLOATS = "floats"
    CROSSREF = "crossref"
    LANGUAGE = "language"
    STYLE = "style"
    BIB = "bib"
    BIB_ONLINE = "bib-online"
    COMPILE = "compile"
    METRICS = "metrics"
    ACCESSIBILITY = "accessibility"
    ANONYMITY = "anonymity"
    POLICY = "policy"
    STATS = "stats"
    INTERNAL = "internal"


@dataclass(frozen=True)
class Edit:
    """A span of one file's raw text, and what to put there instead.

    Only rules whose correction is fully determined attach one. "Delete the
    duplicated word" qualifies; "write alt text for this figure" never will.
    """

    file: str
    start: int          # offset into the file's raw text
    end: int            # exclusive
    replacement: str
    describe: str = ""  # shown in the preview, e.g. "Figure~\\ref{x} -> \\autoref{x}"


@dataclass(frozen=True)
class Finding:
    """One machine-checkable problem, anchored to a source location."""

    rule: str
    message: str
    severity: Severity = Severity.WARN
    file: str | None = None
    line: int | None = None
    col: int | None = None
    context: str | None = None
    fix: str | None = None
    #: Present only when the correction is unambiguous; see ``mechcheck fix``.
    edit: "Edit | None" = None
    # Free-form, used by reporters (e.g. the DOI a bib check resolved).
    data: dict = field(default_factory=dict)

    @property
    def location(self) -> str:
        if self.file and self.line:
            return f"{self.file}:{self.line}"
        if self.file:
            return self.file
        return "-"

    def to_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["severity"] = self.severity.label
        return d

    @property
    def fixable(self) -> bool:
        return self.edit is not None

    def sort_key(self) -> tuple:
        return (-int(self.severity), self.file or "", self.line or 0, self.rule)


@dataclass(frozen=True)
class RuleMeta:
    """Everything needed to document a rule without running it.

    ``docs/rules.md`` is generated from these, so the rule list can never drift
    out of sync with the implementation.
    """

    id: str
    title: str
    category: Category
    severity: Severity
    rationale: str
    fix: str = ""
    #: Rule needs network access (Crossref/OpenAlex/DBLP).
    online: bool = False
    #: Rule needs a compiled PDF and/or .log to be present.
    needs_build: bool = False
    #: Rule needs an external binary (chktex, texcount, ...).
    needs_tool: str | None = None
    #: Profiles in which this rule is on by default; empty means "all".
    profiles: tuple[str, ...] = ()
    #: Only meaningful for theses / only for papers, etc. Purely documentation.
    applies_to: str = "both"


RuleFn = Callable[["RuleContext"], Iterable[Finding]]


@dataclass
class Rule:
    meta: RuleMeta
    fn: RuleFn

    @property
    def id(self) -> str:
        return self.meta.id


class Registry:
    """Global rule registry, populated by the ``@rule`` decorator on import."""

    def __init__(self) -> None:
        self._rules: dict[str, Rule] = {}

    def add(self, rule: Rule) -> None:
        if rule.id in self._rules:
            raise ValueError(f"duplicate rule id: {rule.id}")
        self._rules[rule.id] = rule

    def __iter__(self) -> Iterator[Rule]:
        return iter(sorted(self._rules.values(), key=lambda r: r.id))

    def __len__(self) -> int:
        return len(self._rules)

    def get(self, rule_id: str) -> Rule | None:
        return self._rules.get(rule_id)

    def matching(self, patterns: Sequence[str]) -> list[Rule]:
        out = []
        for rule in self:
            if any(fnmatch.fnmatch(rule.id, p) or rule.meta.category.value == p for p in patterns):
                out.append(rule)
        return out


REGISTRY = Registry()


def rule(
    id: str,
    title: str,
    category: Category,
    severity: Severity = Severity.WARN,
    rationale: str = "",
    fix: str = "",
    online: bool = False,
    needs_build: bool = False,
    needs_tool: str | None = None,
    profiles: tuple[str, ...] = (),
    applies_to: str = "both",
) -> Callable[[RuleFn], RuleFn]:
    """Register a rule. The decorated function is returned unchanged."""

    def decorate(fn: RuleFn) -> RuleFn:
        why = rationale.strip()
        if not why:
            doc = (fn.__doc__ or "").strip().splitlines()
            why = doc[0].strip() if doc else ""
        meta = RuleMeta(
            id=id, title=title, category=category, severity=severity,
            rationale=why,
            fix=fix, online=online, needs_build=needs_build, needs_tool=needs_tool,
            profiles=profiles, applies_to=applies_to,
        )
        REGISTRY.add(Rule(meta=meta, fn=fn))
        return fn

    return decorate


@dataclass
class RuleContext:
    """Everything the rules are allowed to look at."""

    project: "TexProject"
    config: "Config"
    root: str
    #: Populated only when a build is available (``--build-dir``).
    log_text: str | None = None
    pdf_path: str | None = None
    #: Shared cache for expensive lookups (network responses, tool output).
    cache: dict = field(default_factory=dict)
    #: Set when --offline; online rules skip themselves.
    offline: bool = False

    def opt(self, rule_id: str, key: str, default=None):
        """Per-rule option from config, e.g. ``ctx.opt("MET001", "max_words", 25000)``."""
        return self.config.rule_option(rule_id, key, default)

    def edit_span(self, start: int, end: int, replacement: str, describe: str = ""):
        """Build an :class:`Edit` from a span of ``project.text``.

        Returns ``None`` if the span is not safely rewritable -- across files,
        or into verbatim -- so a rule can simply pass the result along.
        """
        mapped = self.project.to_file_span(start, end)
        if mapped is None:
            return None
        path, a, b = mapped
        return Edit(file=path, start=a, end=b, replacement=replacement,
                    describe=describe or f"{self.project.raw_text(path)[a:b]} -> {replacement}")

    def finding(self, rule_id: str, message: str, **kw) -> Finding:
        sev = self.config.severity_for(rule_id)
        kw.setdefault("severity", sev)
        return Finding(rule=rule_id, message=message, **kw)
