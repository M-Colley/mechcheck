"""Running the rules: isolation, suppression, baselines.

Two properties matter more than speed here:

1. **A broken rule must never block a student.**  Every rule runs inside a
   try/except; a crash becomes one INFO finding naming the rule, and the rest
   of the run continues.
2. **Suppression must be local and visible.**  A student who disagrees with a
   check writes ``% mechcheck: off FIG001 -- decorative divider`` next to the
   line.  The reason is required, so the escape hatch stays auditable when a
   supervisor reads the diff.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import dataclass, field

from mechcheck.config import Config
from mechcheck.model import REGISTRY, Finding, RuleContext, Severity
from mechcheck.texsource import TexProject

_SUPPRESS = re.compile(
    r"%\s*mechcheck:\s*(?P<scope>off-file|off-next|off)\b(?P<rules>[^-\n]*)(?:--\s*(?P<reason>.*))?",
    re.IGNORECASE,
)


@dataclass
class Suppression:
    file: str
    line: int
    scope: str          # off | off-next | off-file
    rules: tuple        # empty means "everything"
    reason: str
    used: bool = False

    def covers(self, finding: Finding) -> bool:
        if self.rules and finding.rule not in self.rules:
            return False
        if finding.file != self.file:
            return False
        if self.scope == "off-file":
            return True
        if finding.line is None:
            return False
        if self.scope == "off":
            return finding.line == self.line
        return finding.line == self.line + 1


@dataclass
class RunResult:
    findings: list = field(default_factory=list)
    suppressed: list = field(default_factory=list)
    #: Findings held back by the per-rule cap. Counted, never silently dropped.
    truncated: list = field(default_factory=list)
    skipped: dict = field(default_factory=dict)      # rule id -> why
    unused_suppressions: list = field(default_factory=list)
    duration_s: float = 0.0
    project: TexProject | None = None
    config: Config | None = None

    @property
    def worst(self) -> Severity | None:
        return max((f.severity for f in self.findings), default=None)

    def counts(self) -> dict:
        """Everything found, including what the cap held back.

        The headline must not shrink because the list was shortened.
        """
        out = {"error": 0, "warn": 0, "info": 0}
        for f in self.findings + self.truncated:
            out[f.severity.label] += 1
        return out

    def truncated_by_rule(self) -> dict:
        counts: dict = {}
        for f in self.truncated:
            counts[f.rule] = counts.get(f.rule, 0) + 1
        return counts

    def should_fail(self) -> bool:
        threshold = self.config.fail_on if self.config else Severity.ERROR
        return any(f.severity >= threshold for f in self.findings + self.truncated)


def collect_suppressions(project: TexProject) -> list:
    out = []
    for line in project.lines:
        m = _SUPPRESS.search(line.raw)
        if not m:
            continue
        raw_rules = (m.group("rules") or "").replace(",", " ").split()
        out.append(Suppression(
            file=line.file,
            line=line.lineno,
            scope=m.group("scope").lower(),
            rules=tuple(r.strip().upper() for r in raw_rules if r.strip()),
            reason=(m.group("reason") or "").strip(),
        ))
    return out


def load_baseline(path: str | None) -> set:
    """A baseline freezes today's findings so a checker can be adopted mid-thesis."""
    if not path or not os.path.isfile(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return set()
    return {tuple(k) for k in data.get("fingerprints", [])}


def fingerprint(f: Finding) -> tuple:
    """Location-independent enough to survive edits elsewhere in the file."""
    return (f.rule, f.file or "", (f.context or f.message)[:120])


def run(root: str, config: Config, only=None, offline: bool = False,
        build_dir: str | None = None, baseline: str | None = None,
        main: str | None = None) -> RunResult:
    started = time.time()
    project = TexProject.load(root, main or config.data.get("main"))
    result = RunResult(project=project, config=config)

    log_text, pdf_path = _find_build_outputs(root, build_dir, project)
    ctx = RuleContext(project=project, config=config, root=os.path.abspath(root),
                      log_text=log_text, pdf_path=pdf_path, offline=offline)

    only_set = {r.strip().upper() for r in (only or []) if r.strip()}

    for rule in REGISTRY:
        meta = rule.meta
        if only_set and meta.id not in only_set:
            continue
        if not only_set and not config.enabled(meta.id):
            result.skipped[meta.id] = "disabled by configuration"
            continue
        if meta.online and offline:
            result.skipped[meta.id] = "needs network (--offline)"
            continue
        if meta.needs_build and not (log_text or pdf_path):
            result.skipped[meta.id] = "needs a compiled PDF/log (--build-dir)"
            continue
        if meta.needs_tool and not shutil.which(meta.needs_tool):
            result.skipped[meta.id] = f"needs `{meta.needs_tool}` on PATH"
            continue
        try:
            produced = list(rule.fn(ctx) or [])
        except Exception as exc:  # a broken rule must not break the run
            produced = [Finding(
                rule="INT001",
                message=f"rule {meta.id} crashed: {type(exc).__name__}: {exc}",
                severity=Severity.INFO,
                fix="Report this at the mechcheck repository; the other rules still ran.",
            )]
        result.findings.extend(produced)

    _apply_suppressions(result, project)
    _apply_baseline(result, baseline)
    result.findings.sort(key=lambda f: f.sort_key())
    _apply_cap(result, config.max_per_rule)
    result.duration_s = time.time() - started
    return result


def _apply_suppressions(result: RunResult, project: TexProject) -> None:
    suppressions = collect_suppressions(project)
    kept = []
    for finding in result.findings:
        hit = next((s for s in suppressions if s.covers(finding)), None)
        if hit is None:
            kept.append(finding)
            continue
        hit.used = True
        result.suppressed.append(finding)
    result.findings = kept
    result.unused_suppressions = [s for s in suppressions if not s.used]


def _apply_cap(result: RunResult, max_per_rule: int) -> None:
    """Keep the first N findings of each rule; count the rest.

    Runs after sorting, so what survives is the most severe and earliest of
    each kind -- the ones worth looking at first.
    """
    if not max_per_rule:
        return
    kept, held = [], []
    seen: dict = {}
    for finding in result.findings:
        seen[finding.rule] = seen.get(finding.rule, 0) + 1
        (kept if seen[finding.rule] <= max_per_rule else held).append(finding)
    result.findings = kept
    result.truncated = held


def _apply_baseline(result: RunResult, baseline: str | None) -> None:
    frozen = load_baseline(baseline)
    if not frozen:
        return
    kept = []
    for finding in result.findings:
        if fingerprint(finding) in frozen:
            result.suppressed.append(finding)
        else:
            kept.append(finding)
    result.findings = kept


def write_baseline(path: str, result: RunResult) -> int:
    payload = {
        "note": "Findings frozen when mechcheck was adopted. Delete a line to start enforcing it.",
        "created": time.strftime("%Y-%m-%d"),
        "fingerprints": sorted(list(fingerprint(f)) for f in result.findings + result.suppressed),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False)
    return len(payload["fingerprints"])


def _find_build_outputs(root: str, build_dir: str | None, project: TexProject):
    """Locate the .log and .pdf a compile produced, if there was one."""
    stem = os.path.splitext(os.path.basename(project.main))[0]
    search = [build_dir] if build_dir else [root, os.path.join(root, "build"),
                                            os.path.join(root, "out"), os.path.join(root, "output")]
    log_text = None
    pdf_path = None
    for d in search:
        if not d or not os.path.isdir(d):
            continue
        for name in (stem + ".log", "main.log"):
            cand = os.path.join(d, name)
            if log_text is None and os.path.isfile(cand):
                try:
                    with open(cand, "r", encoding="utf-8", errors="replace") as fh:
                        log_text = fh.read()
                except OSError:
                    pass
        for name in (stem + ".pdf", "main.pdf"):
            cand = os.path.join(d, name)
            if pdf_path is None and os.path.isfile(cand):
                pdf_path = cand
        if log_text is None:
            for fn in sorted(os.listdir(d)):
                if fn.endswith(".log"):
                    try:
                        with open(os.path.join(d, fn), "r", encoding="utf-8", errors="replace") as fh:
                            head = fh.read()
                    except OSError:
                        continue
                    if "This is pdfTeX" in head or "This is LuaHBTeX" in head or "This is XeTeX" in head:
                        log_text = head
                        break
    return log_text, pdf_path
