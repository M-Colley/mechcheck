"""Applying the fixes that are safe to apply.

A rule only reaches this file when its correction is fully determined: delete
the duplicated word, drop the second expansion of an abbreviation, turn
``Figure~\\ref{x}`` into ``\\autoref{x}``. Anything needing a sentence rewritten
-- alt text above all -- stays a finding for a person to act on.

The safety comes from checking the work rather than trusting it. After writing,
the whole project is re-checked: the findings that were fixed must be gone, and
**nothing new may appear**. A fix that introduces a problem is reported as such,
loudly, instead of being left in somebody's thesis.
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class FixReport:
    applied: list = field(default_factory=list)      # (rule, file, describe)
    skipped: list = field(default_factory=list)      # (rule, file, why)
    files_changed: list = field(default_factory=list)
    before: Counter = field(default_factory=Counter)
    after: Counter = field(default_factory=Counter)
    new_findings: list = field(default_factory=list)
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        return not self.new_findings

    def resolved(self) -> Counter:
        out = Counter()
        for rule, count in self.before.items():
            gone = count - self.after.get(rule, 0)
            if gone > 0:
                out[rule] = gone
        return out


def collect_edits(findings) -> dict:
    """Group applicable edits by file, latest first so offsets stay valid."""
    by_file: dict = {}
    for finding in findings:
        edit = getattr(finding, "edit", None)
        if edit is None:
            continue
        by_file.setdefault(edit.file, []).append((finding, edit))
    for path in by_file:
        by_file[path].sort(key=lambda pair: pair[1].start, reverse=True)
    return by_file


def apply_to_text(text: str, pairs: list, report: FixReport, path: str) -> str:
    """Apply edits to one file's text, refusing any that overlap another."""
    written_from = len(text)          # edits run right-to-left
    for finding, edit in pairs:
        if edit.end > written_from:
            report.skipped.append((finding.rule, path, "overlaps an earlier fix"))
            continue
        if not (0 <= edit.start <= edit.end <= len(text)):
            report.skipped.append((finding.rule, path, "span no longer matches the file"))
            continue
        text = text[:edit.start] + edit.replacement + text[edit.end:]
        written_from = edit.start
        report.applied.append((finding.rule, path, edit.describe))
    return text


def fix(root: str, config, run_checks, only=None, offline: bool = True,
        dry_run: bool = False, baseline: str | None = None) -> FixReport:
    """Check, apply every safe fix, then check again to prove it helped.

    ``run_checks`` is injected so this module never imports the runner, which
    keeps the dependency pointing one way.
    """
    report = FixReport(dry_run=dry_run)

    first = run_checks(root, config, only=only, offline=offline, baseline=baseline)
    report.before = Counter(f.rule for f in first.findings + first.truncated)

    # The cap is a reading aid, not a fixing one: fix everything fixable.
    all_findings = first.findings + first.truncated
    by_file = collect_edits(all_findings)
    if not by_file:
        report.after = report.before
        return report

    for path, pairs in sorted(by_file.items()):
        full = os.path.join(root, path)
        try:
            with open(full, "r", encoding="utf-8", newline="") as fh:
                original = fh.read()
        except OSError as exc:
            report.skipped.append(("-", path, f"could not read: {exc}"))
            continue

        # The parser works on text split by "\n"; normalise so offsets line up,
        # and restore the file's own line endings afterwards.
        crlf = "\r\n" in original
        text = original.replace("\r\n", "\n")
        updated = apply_to_text(text, pairs, report, path)
        if updated == text:
            continue
        report.files_changed.append(path)
        if dry_run:
            continue
        try:
            with open(full, "w", encoding="utf-8", newline="") as fh:
                fh.write(updated.replace("\n", "\r\n") if crlf else updated)
        except OSError as exc:
            report.skipped.append(("-", path, f"could not write: {exc}"))

    if dry_run:
        report.after = report.before
        return report

    second = run_checks(root, config, only=only, offline=offline, baseline=baseline)
    report.after = Counter(f.rule for f in second.findings + second.truncated)

    # Anything that got worse is the important signal here.
    for rule, count in report.after.items():
        grew = count - report.before.get(rule, 0)
        if grew > 0:
            report.new_findings.append((rule, grew))
    return report


def render(report: FixReport) -> str:
    out = []
    verb = "would fix" if report.dry_run else "fixed"
    if not report.applied:
        return "Nothing here can be fixed automatically.\n" \
               "Only rules with exactly one right answer carry a fix; the rest need a person."

    counts = Counter(rule for rule, _f, _d in report.applied)
    out.append(f"{verb} {len(report.applied)} finding(s) "
               f"in {len(report.files_changed)} file(s):")
    for rule, n in sorted(counts.items()):
        out.append(f"  {rule:<8} {n}")

    shown = report.applied[:12]
    out.append("")
    for rule, path, describe in shown:
        out.append(f"  {path}: {describe}")
    if len(report.applied) > len(shown):
        out.append(f"  … and {len(report.applied) - len(shown)} more")

    if report.skipped:
        out.append("")
        out.append(f"{len(report.skipped)} skipped:")
        for rule, path, why in report.skipped[:8]:
            out.append(f"  {rule} in {path}: {why}")

    if report.dry_run:
        out.append("")
        out.append("Nothing was written. Run without --dry-run to apply.")
        return "\n".join(out)

    out.append("")
    resolved = report.resolved()
    if resolved:
        out.append("Re-checked: " + ", ".join(f"{r} -{n}" for r, n in sorted(resolved.items())))
    if report.new_findings:
        out.append("")
        out.append("WARNING — the re-check found problems that were not there before:")
        for rule, n in report.new_findings:
            out.append(f"  {rule} +{n}")
        out.append("Review the diff before committing. This should not happen; please report it.")
    else:
        out.append("Re-checked: nothing new appeared.")
    return "\n".join(out)
