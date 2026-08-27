"""Supervisor digest: one table for every thesis you are supervising.

Run over a list of repositories, check each one, and emit a single Markdown
summary. The intent is not to grade anybody automatically -- it is to answer,
in five seconds on a Monday morning, the two questions that otherwise cost a
meeting each: *is it still compiling* and *is it moving*.

    python scripts/digest.py --config students.yaml --out digest.md

students.yaml::

    students:
      - name: A. Student
        repo: my-org/thesis-astudent
        topic: 'External communication of AVs'
        due: 2026-11-30
        venue: null
        profile: thesis
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mechcheck import minyaml  # noqa: E402


def run(cmd, cwd=None, timeout=600):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def clone(repo: str, target: str) -> bool:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    url = f"https://github.com/{repo}.git"
    if token:
        url = f"https://x-access-token:{token}@github.com/{repo}.git"
    result = run(["git", "clone", "--depth", "50", url, target])
    return result.returncode == 0


def last_commit(path: str):
    result = run(["git", "log", "-1", "--format=%cI|%an|%s"], cwd=path)
    if result.returncode != 0 or not result.stdout.strip():
        return None, None, None
    when, author, subject = (result.stdout.strip().split("|", 2) + ["", ""])[:3]
    try:
        stamp = datetime.fromisoformat(when).date()
    except ValueError:
        stamp = None
    return stamp, author, subject


def check(path: str, profile: str | None, venue: str | None, offline: bool) -> dict:
    cmd = [sys.executable, "-m", "mechcheck.cli", "check", path,
           "--format", "json", "--fail-on", "never", "--no-baseline"]
    if profile:
        cmd += ["--profile", profile]
    if venue:
        cmd += ["--venue", venue]
    if offline:
        cmd += ["--offline"]
    result = run(cmd)
    try:
        return json.loads(result.stdout)
    except ValueError:
        return {"counts": {"error": 0, "warn": 0, "info": 0}, "findings": [],
                "error": (result.stderr or "check failed")[:200]}


def word_count(path: str, profile: str | None) -> int:
    """Word count via the same code path the rules use, without a full run."""
    try:
        from mechcheck.config import Config
        from mechcheck.model import RuleContext
        from mechcheck.rules.metrics import word_count as count_words
        from mechcheck.texsource import TexProject

        project = TexProject.load(path)
        ctx = RuleContext(project=project, config=Config.load(path), root=path)
        return count_words(ctx)
    except Exception:
        return 0


def status_icon(errors: int, stale_days) -> str:
    if stale_days is not None and stale_days > 21:
        return "🕸️"
    if errors == 0:
        return "✅"
    if errors <= 5:
        return "⚠️"
    return "❌"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Weekly supervision digest.")
    parser.add_argument("--config", default="students.yaml")
    parser.add_argument("--out", default="digest.md")
    parser.add_argument("--offline", action="store_true",
                        help="skip the bibliography lookups (much faster)")
    parser.add_argument("--keep", action="store_true", help="do not delete the clones")
    args = parser.parse_args(argv)

    config = minyaml.load(args.config)
    students = config.get("students") or []
    if not students:
        print(f"no students listed in {args.config}", file=sys.stderr)
        return 2

    today = date.today()
    rows = []
    workdir = tempfile.mkdtemp(prefix="mechcheck-digest-")
    try:
        for entry in students:
            name = entry.get("name") or entry.get("repo", "?")
            repo = entry.get("repo")
            if not repo:
                continue
            target = os.path.join(workdir, repo.replace("/", "__"))
            if not clone(repo, target):
                rows.append({"name": name, "repo": repo, "status": "🚫",
                             "note": "could not clone"})
                continue

            source = target
            if os.path.isdir(os.path.join(target, "paper")):
                source = os.path.join(target, "paper")  # the Overleaf mirror layout

            when, _author, subject = last_commit(target)
            stale = (today - when).days if when else None
            result = check(source, entry.get("profile"), entry.get("venue"), args.offline)
            counts = result.get("counts", {})
            words = word_count(source, entry.get("profile"))

            due = entry.get("due")
            days_left = None
            if due:
                try:
                    days_left = (datetime.strptime(str(due), "%Y-%m-%d").date() - today).days
                except ValueError:
                    days_left = None

            rows.append({
                "name": name,
                "repo": repo,
                "status": status_icon(counts.get("error", 0), stale),
                "errors": counts.get("error", 0),
                "warnings": counts.get("warn", 0),
                "words": words,
                "last": when.isoformat() if when else "-",
                "stale": stale,
                "subject": (subject or "")[:48],
                "due": due,
                "days_left": days_left,
                "topic": entry.get("topic", ""),
                "top": _top_rules(result.get("findings", [])),
            })
    finally:
        if not args.keep:
            shutil.rmtree(workdir, ignore_errors=True)

    markdown = render(rows, today)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(markdown)
    print(markdown)
    return 0


def _top_rules(findings: list, n: int = 3) -> str:
    from collections import Counter

    counts = Counter(f.get("rule") for f in findings if f.get("severity") in ("error", "warn"))
    return ", ".join(f"{rule} ×{c}" for rule, c in counts.most_common(n))


def render(rows: list, today: date) -> str:
    out = [f"# Supervision digest — {today.isoformat()}", ""]
    if not rows:
        return "\n".join(out + ["Nothing to report."])

    needs_attention = [r for r in rows if r.get("status") in ("❌", "🚫", "🕸️")]
    if needs_attention:
        out.append("**Worth a message this week:** "
                   + ", ".join(f"{r['name']}" for r in needs_attention))
        out.append("")

    out.append("| | Student | Words | Errors | Warn | Last commit | Due | Most frequent |")
    out.append("|---|---|---:|---:|---:|---|---|---|")
    for r in sorted(rows, key=lambda x: (x.get("status") != "❌", x.get("name", ""))):
        if r.get("note"):
            out.append(f"| {r['status']} | {r['name']} | | | | {r['note']} | | |")
            continue
        stale = f"{r['last']}"
        if r.get("stale") is not None and r["stale"] > 14:
            stale += f" ({r['stale']}d ago)"
        due = r.get("due") or ""
        if r.get("days_left") is not None:
            due = f"{due} ({r['days_left']}d)"
        out.append(
            f"| {r['status']} | [{r['name']}](https://github.com/{r['repo']}) "
            f"| {r['words']:,} | {r['errors']} | {r['warnings']} | {stale} | {due} "
            f"| {r['top']} |")

    out.append("")
    out.append("<sub>✅ clean · ⚠️ a few errors · ❌ many errors · 🕸️ no commits for three weeks "
               "· 🚫 repository unreachable</sub>")
    out.append("")
    out.append("Counts are mechanical only. They say nothing about whether the argument is any "
               "good — that is what the meeting is for.")
    return "\n".join(out)


if __name__ == "__main__":
    sys.exit(main())
