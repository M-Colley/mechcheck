"""Reporters.

The same run is rendered for four different readers:

* ``text``     -- the student at their terminal
* ``markdown`` -- the GitHub job summary and the PR comment (what the supervisor sees)
* ``github``   -- workflow commands, so findings appear on the diff itself
* ``sarif``    -- GitHub code scanning, so findings persist and get triaged
* ``json``     -- anything else, including the weekly supervisor digest
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict

from mechcheck.model import REGISTRY, Severity

_ICON = {Severity.ERROR: "x", Severity.WARN: "!", Severity.INFO: "i"}
_MD_ICON = {Severity.ERROR: "❌", Severity.WARN: "⚠️", Severity.INFO: "ℹ️"}
_ANSI = {Severity.ERROR: "\033[31m", Severity.WARN: "\033[33m", Severity.INFO: "\033[36m"}
_RESET = "\033[0m"
_DIM = "\033[2m"


def _color_enabled(force: bool | None = None) -> bool:
    if force is not None:
        return force
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("GITHUB_ACTIONS"):
        return False
    try:
        import sys

        return sys.stdout.isatty()
    except Exception:
        return False


def render_text(result, color: bool | None = None, show_fix: bool = True) -> str:
    use_color = _color_enabled(color)
    out = []
    by_file = defaultdict(list)
    for f in result.findings:
        by_file[f.file or "(project)"].append(f)

    for path in sorted(by_file):
        out.append(f"\n{path}")
        for f in sorted(by_file[path], key=lambda x: (x.line or 0, x.rule)):
            loc = f":{f.line}" if f.line else ""
            head = f"  {_ICON[f.severity]} {f.severity.label:<5} {f.rule}{loc}"
            if use_color:
                head = f"  {_ANSI[f.severity]}{_ICON[f.severity]} {f.severity.label:<5}{_RESET} {f.rule}{loc}"
            out.append(f"{head}  {f.message}")
            if f.context:
                ctx = f"      {f.context}"
                out.append(f"{_DIM}{ctx}{_RESET}" if use_color else ctx)
            if show_fix and f.fix:
                fix = f"      fix: {f.fix}"
                out.append(f"{_DIM}{fix}{_RESET}" if use_color else fix)

    for rule_id, held in sorted(getattr(result, "truncated_by_rule", lambda: {})().items()):
        out.append(f"  … and {held} more {rule_id}. `mechcheck explain {rule_id}` says why, "
                   f"or raise max_per_rule to list them all.")

    counts = result.counts()
    out.append("")
    summary = (f"{counts['error']} error(s), {counts['warn']} warning(s), "
               f"{counts['info']} note(s) in {result.duration_s:.1f}s")
    if result.truncated:
        summary += f"; {len(result.truncated)} not listed"
    if result.suppressed:
        summary += f"; {len(result.suppressed)} suppressed"
    out.append(summary)
    if result.skipped:
        out.append(f"{len(result.skipped)} rule(s) did not run — add --show-skipped to see which, and why")
    if not result.findings:
        out.append("Nothing mechanical left to fix. The remaining work is the thinking.")
    return "\n".join(out)


def render_skipped(result) -> str:
    """Which rules did not run in this check, grouped by the reason (``--show-skipped``)."""
    by_reason = defaultdict(list)
    for rule_id, why in result.skipped.items():
        by_reason[why].append(rule_id)
    out = ["", f"{len(result.skipped)} rule(s) did not run:"]
    for why, ids in sorted(by_reason.items()):
        out.append(f"  {why}")
        out.append("    " + ", ".join(sorted(ids)))
    return "\n".join(out)


def render_github(result) -> str:
    """Workflow commands: findings land as annotations on the changed lines."""
    lines = []
    for f in result.findings:
        level = {Severity.ERROR: "error", Severity.WARN: "warning", Severity.INFO: "notice"}[f.severity]
        props = []
        if f.file:
            props.append(f"file={f.file}")
        if f.line:
            props.append(f"line={f.line}")
        if f.col:
            props.append(f"col={f.col}")
        props.append(f"title={f.rule}")
        msg = f.message.replace("\n", " ")
        if f.fix:
            msg += f" — fix: {f.fix}"
        msg = msg.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        lines.append(f"::{level} {','.join(props)}::{msg}")
    return "\n".join(lines)


def render_markdown(result, title: str = "mechcheck", max_rows: int = 60) -> str:
    counts = result.counts()
    cfg = result.config
    bits = []
    verdict = "✅ **passed**" if not result.should_fail() else "❌ **blocked**"
    bits.append(f"### {title}: {verdict}")
    meta = []
    if cfg:
        meta.append(f"profile `{cfg.profile}`")
        meta.append(f"stage `{cfg.stage}`")
        if cfg.venue:
            meta.append(f"venue `{cfg.venue}`")
    if result.project:
        meta.append(f"main `{result.project.main}`")
        meta.append(f"{len(result.project.files)} file(s)")
    bits.append(" · ".join(meta))
    bits.append("")
    bits.append(f"| | count |\n|---|---|\n| ❌ errors | {counts['error']} |\n"
                f"| ⚠️ warnings | {counts['warn']} |\n| ℹ️ notes | {counts['info']} |")
    bits.append("")

    if result.findings:
        bits.append("| | rule | where | what |")
        bits.append("|---|---|---|---|")
        for f in result.findings[:max_rows]:
            where = f"`{f.location}`" if f.file else ""
            msg = f.message.replace("|", "\\|")
            bits.append(f"| {_MD_ICON[f.severity]} | `{f.rule}` | {where} | {msg} |")
        if len(result.findings) > max_rows:
            bits.append(f"\n_…and {len(result.findings) - max_rows} more. Run `mechcheck check` locally for the full list._")
    else:
        bits.append("_No mechanical issues found._")

    held = getattr(result, "truncated_by_rule", lambda: {})()
    if held:
        bits.append("")
        bits.append("**Repeated findings, listed once each:** "
                    + ", ".join(f"`{r}` +{n}" for r, n in sorted(held.items())))

    top = Counter(f.rule for f in result.findings).most_common(3)
    if top:
        bits.append("")
        bits.append("**Most frequent:** " + ", ".join(f"`{r}` ({n}×)" for r, n in top))
        bits.append("")
        bits.append("<details><summary>What these rules mean</summary>\n")
        for rule_id, _n in top:
            rule = REGISTRY.get(rule_id)
            if rule:
                bits.append(f"- **`{rule_id}` {rule.meta.title}** — {rule.meta.rationale}"
                            + (f" _Fix:_ {rule.meta.fix}" if rule.meta.fix else ""))
        bits.append("\n</details>")

    if result.suppressed:
        bits.append("")
        bits.append(f"_{len(result.suppressed)} finding(s) suppressed by `% mechcheck: off` comments or the baseline._")
    return "\n".join(bits)


def render_json(result) -> str:
    payload = {
        "version": 1,
        "profile": result.config.profile if result.config else None,
        "stage": result.config.stage if result.config else None,
        "venue": result.config.venue if result.config else None,
        "main": result.project.main if result.project else None,
        "duration_s": round(result.duration_s, 3),
        "counts": result.counts(),
        "failed": result.should_fail(),
        "findings": [f.to_dict() for f in result.findings],
        "suppressed": [f.to_dict() for f in result.suppressed],
        "skipped": result.skipped,
        "truncated": [f.to_dict() for f in getattr(result, "truncated", [])],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def render_sarif(result) -> str:
    """SARIF 2.1.0, so GitHub code scanning can track findings over time."""
    rules_used = {}
    results = []
    for f in result.findings:
        rule = REGISTRY.get(f.rule)
        if f.rule not in rules_used:
            rules_used[f.rule] = {
                "id": f.rule,
                "name": (rule.meta.title if rule else f.rule).replace(" ", ""),
                "shortDescription": {"text": rule.meta.title if rule else f.rule},
                "fullDescription": {"text": rule.meta.rationale if rule else ""},
                "help": {"text": (rule.meta.fix if rule else "") or ""},
                "properties": {"category": rule.meta.category.value if rule else "other"},
                "defaultConfiguration": {
                    "level": {Severity.ERROR: "error", Severity.WARN: "warning",
                              Severity.INFO: "note"}[f.severity]
                },
            }
        entry = {
            "ruleId": f.rule,
            "level": {Severity.ERROR: "error", Severity.WARN: "warning",
                      Severity.INFO: "note"}[f.severity],
            "message": {"text": f.message + (f"\nFix: {f.fix}" if f.fix else "")},
        }
        if f.file:
            entry["locations"] = [{
                "physicalLocation": {
                    "artifactLocation": {"uri": f.file},
                    "region": {"startLine": max(1, f.line or 1),
                               **({"startColumn": f.col} if f.col else {})},
                }
            }]
        results.append(entry)

    doc = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "mechcheck",
                "informationUri": "https://github.com/M-Colley/mechcheck",
                "rules": list(rules_used.values()),
            }},
            "results": results,
        }],
    }
    return json.dumps(doc, indent=1, ensure_ascii=False)


def render_rules_md() -> str:
    """``docs/rules.md`` is generated, so it can never drift from the code."""
    by_cat = defaultdict(list)
    for rule in REGISTRY:
        by_cat[rule.meta.category.value].append(rule)

    out = ["# Rule reference", "",
           f"{len(REGISTRY)} rules. Generated by `mechcheck rules --markdown` — do not edit by hand.",
           "",
           "Every rule can be switched off for one line with a source comment:", "",
           "```latex",
           "\\includegraphics{decorative-divider}  % mechcheck: off FIG002 -- decorative, no content to describe",
           "```", ""]
    for cat in sorted(by_cat):
        out.append(f"## {cat}")
        out.append("")
        out.append("| id | severity | what it checks | why | how to fix |")
        out.append("|---|---|---|---|---|")
        for rule in sorted(by_cat[cat], key=lambda r: r.id):
            m = rule.meta
            flags = []
            if m.online:
                flags.append("network")
            if m.needs_build:
                flags.append("needs build")
            if m.needs_tool:
                flags.append(f"needs {m.needs_tool}")
            sev = m.severity.label + (f" ({', '.join(flags)})" if flags else "")
            out.append(f"| `{m.id}` | {sev} | {m.title} | {m.rationale} | {m.fix} |")
        out.append("")
    return "\n".join(out)


RENDERERS = {
    "text": render_text,
    "github": render_github,
    "markdown": render_markdown,
    "json": render_json,
    "sarif": render_sarif,
}
