"""Command line interface.

    mechcheck check .                     # what CI runs
    mechcheck check . --stage draft       # nothing blocks, everything is reported
    mechcheck check . --venue chi         # + CHI's submission requirements
    mechcheck rules --markdown            # regenerate docs/rules.md
    mechcheck explain FIG002              # what one rule means and why
    mechcheck init . --venue autoui       # drop a config + workflow into a project
    mechcheck baseline .                  # freeze today's findings, enforce from here on
"""

from __future__ import annotations

import argparse
import os
import sys

from mechcheck import report as reporters
from mechcheck.config import Config, PROFILES, STAGES, available_venues
from mechcheck.model import REGISTRY, Severity
from mechcheck.runner import run, write_baseline

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mechcheck",
        description="Mechanical checks for LaTeX theses and papers.",
    )
    sub = p.add_subparsers(dest="command")

    check = sub.add_parser("check", help="run the checks")
    check.add_argument("path", nargs="?", default=".", help="project root (default: .)")
    check.add_argument("--main", help="main .tex file (default: auto-detect)")
    check.add_argument("--config", help="path to mechcheck.yaml")
    check.add_argument("--profile", choices=sorted(PROFILES), help="which rule set applies")
    check.add_argument("--stage", choices=sorted(STAGES),
                       help="draft = report only, submission = normal, final = warnings become errors")
    check.add_argument("--venue", help=f"venue pack: {', '.join(available_venues()) or 'none installed'}")
    check.add_argument("--format", "-f", default="text", choices=sorted(reporters.RENDERERS),
                       help="output format")
    check.add_argument("--output", "-o", help="write the report to a file instead of stdout")
    check.add_argument("--also", action="append", default=[], metavar="FORMAT=PATH",
                       help="additionally write another format, e.g. --also sarif=mechcheck.sarif")
    check.add_argument("--only", action="append", default=[], metavar="RULE",
                       help="run only these rules (repeatable)")
    check.add_argument("--offline", action="store_true", help="skip rules that need the network")
    check.add_argument("--build-dir", help="directory holding the compiled .pdf/.log")
    check.add_argument("--baseline", default=".mechcheck-baseline.json",
                       help="findings to ignore (created by `mechcheck baseline`)")
    check.add_argument("--no-baseline", action="store_true", help="ignore the baseline file")
    check.add_argument("--max-per-rule", type=int, metavar="N",
                       help="show at most N findings per rule (0 = all; default 10)")
    check.add_argument("--fail-on", choices=["error", "warn", "info", "never"],
                       help="exit non-zero at this severity (default: error)")
    check.add_argument("--show-skipped", action="store_true",
                       help="list the rules that did not run in this check, and why")

    rules = sub.add_parser("rules", help="list the rules")
    rules.add_argument("--markdown", action="store_true", help="emit docs/rules.md")
    rules.add_argument("--category", help="filter by category")

    explain = sub.add_parser("explain", help="explain one rule")
    explain.add_argument("rule")

    init = sub.add_parser("init", help="write a starter mechcheck.yaml (and optionally CI + .sty)")
    init.add_argument("path", nargs="?", default=".")
    init.add_argument("--venue")
    init.add_argument("--profile", choices=sorted(PROFILES), default="thesis")
    init.add_argument("--with-ci", action="store_true", help="also write .github/workflows/mechcheck.yml")
    init.add_argument("--with-sty", action="store_true", help="also copy mechcheck.sty into the project")
    init.add_argument("--force", action="store_true")

    fixp = sub.add_parser("fix", help="apply the fixes that are unambiguous")
    fixp.add_argument("path", nargs="?", default=".")
    fixp.add_argument("--config")
    fixp.add_argument("--profile", choices=sorted(PROFILES))
    fixp.add_argument("--stage", choices=sorted(STAGES))
    fixp.add_argument("--venue")
    fixp.add_argument("--only", action="append", default=[], metavar="RULE",
                      help="fix only these rules (repeatable)")
    fixp.add_argument("--dry-run", action="store_true",
                      help="show what would change and write nothing")

    base = sub.add_parser("baseline", help="freeze current findings so only new ones fail")
    base.add_argument("path", nargs="?", default=".")
    base.add_argument("--config")
    base.add_argument("--profile", choices=sorted(PROFILES))
    base.add_argument("--venue")
    base.add_argument("--offline", action="store_true")
    base.add_argument("--out", default=".mechcheck-baseline.json")

    terms = sub.add_parser("terms", help="the concepts this document has more than one name for")
    terms.add_argument("path", nargs="?", default=".")
    terms.add_argument("--config")
    terms.add_argument("--main")
    terms.add_argument("--profile", choices=sorted(PROFILES))
    terms.add_argument("--venue")

    sub.add_parser("venues", help="list the installed venue packs")
    return p


def _overrides(args) -> dict:
    out = {}
    for key in ("profile", "stage", "venue", "main"):
        value = getattr(args, key, None)
        if value:
            out[key] = value
    if getattr(args, "max_per_rule", None) is not None:
        out["max_per_rule"] = args.max_per_rule
    fail_on = getattr(args, "fail_on", None)
    if fail_on:
        out["fail_on"] = fail_on
    return out


def cmd_check(args) -> int:
    root = os.path.abspath(args.path)
    if not os.path.isdir(root):
        print(f"mechcheck: not a directory: {root}", file=sys.stderr)
        return EXIT_USAGE

    config = Config.load(root, explicit=args.config, overrides=_overrides(args))
    baseline = None if args.no_baseline else os.path.join(root, args.baseline)

    result = run(root, config, only=args.only, offline=args.offline,
                 build_dir=args.build_dir, baseline=baseline, main=args.main)

    text = reporters.RENDERERS[args.format](result)
    if args.output:
        _write(args.output, text)
    else:
        print(text)
    if getattr(args, "show_skipped", False) and result.skipped:
        print(reporters.render_skipped(result))

    for spec in args.also:
        fmt, _, path = spec.partition("=")
        fmt = fmt.strip()
        if fmt not in reporters.RENDERERS or not path:
            print(f"mechcheck: ignoring --also {spec!r}", file=sys.stderr)
            continue
        _write(path, reporters.RENDERERS[fmt](result))

    # GitHub job summary, when we are inside Actions.
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path and args.format != "markdown":
        try:
            with open(summary_path, "a", encoding="utf-8") as fh:
                fh.write(reporters.render_markdown(result) + "\n")
        except OSError:
            pass

    if getattr(args, "fail_on", None) == "never":
        return EXIT_OK
    return EXIT_FINDINGS if result.should_fail() else EXIT_OK


def _write(path: str, text: str) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")


def cmd_rules(args) -> int:
    if args.markdown:
        print(reporters.render_rules_md())
        return EXIT_OK
    for rule in REGISTRY:
        m = rule.meta
        if args.category and m.category.value != args.category:
            continue
        flags = []
        if m.online:
            flags.append("net")
        if m.needs_build:
            flags.append("build")
        if m.needs_tool:
            flags.append(m.needs_tool)
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        print(f"{m.id:<8} {m.severity.label:<5} {m.category.value:<14} {m.title}{suffix}")
    print(f"\n{len(REGISTRY)} rules")
    return EXIT_OK


def cmd_explain(args) -> int:
    rule = REGISTRY.get(args.rule.strip().upper())
    if not rule:
        print(f"mechcheck: no such rule: {args.rule}", file=sys.stderr)
        return EXIT_USAGE
    m = rule.meta
    print(f"{m.id}  {m.title}")
    print(f"  category   {m.category.value}")
    print(f"  severity   {m.severity.label}")
    print(f"  applies to {m.applies_to}")
    if m.online:
        print("  network    yes (skipped with --offline)")
    if m.needs_build:
        print("  needs      a compiled PDF/log")
    if m.needs_tool:
        print(f"  needs      `{m.needs_tool}` on PATH")
    print(f"\n  why    {m.rationale}")
    if m.fix:
        print(f"  fix    {m.fix}")
    print(f"\n  silence one occurrence:  % mechcheck: off {m.id} -- your reason")
    print(f"  silence a whole file:    % mechcheck: off-file {m.id} -- your reason")
    return EXIT_OK


def cmd_venues(_args) -> int:
    from mechcheck.config import load_venue

    names = available_venues()
    if not names:
        print("no venue packs installed")
        return EXIT_OK
    for name in names:
        data = load_venue(name)
        print(f"{name:<10} {data.get('name', '')}")
        if data.get("updated"):
            print(f"{'':<10} checked against the CFP on {data['updated']} — reverify before you submit")
    return EXIT_OK


def cmd_init(args) -> int:
    from mechcheck.scaffold import init_project

    return init_project(args.path, profile=args.profile, venue=args.venue,
                        with_ci=args.with_ci, with_sty=args.with_sty, force=args.force)


def cmd_fix(args) -> int:
    from mechcheck import fixer

    root = os.path.abspath(args.path)
    if not os.path.isdir(root):
        print(f"mechcheck: not a directory: {root}", file=sys.stderr)
        return EXIT_USAGE
    config = Config.load(root, explicit=args.config, overrides=_overrides(args))
    report = fixer.fix(root, config, run, only=args.only, offline=True,
                       dry_run=args.dry_run)
    print(fixer.render(report))
    return EXIT_OK if report.ok else EXIT_FINDINGS


def cmd_terms(args) -> int:
    """Survey the vocabulary, so a group can write its own from a real thesis."""
    from mechcheck.rules.terminology import render_survey

    root = os.path.abspath(args.path)
    if not os.path.isdir(root):
        print(f"mechcheck: not a directory: {root}", file=sys.stderr)
        return EXIT_USAGE
    config = Config.load(root, explicit=args.config, overrides=_overrides(args))
    # One rule is enough to build the project; the survey does its own reading.
    result = run(root, config, only=["TRM001"], offline=True, baseline=None, main=args.main)
    print(render_survey(result))
    return EXIT_OK


def cmd_baseline(args) -> int:
    root = os.path.abspath(args.path)
    config = Config.load(root, explicit=args.config, overrides=_overrides(args))
    result = run(root, config, offline=args.offline, baseline=None)
    path = os.path.join(root, args.out)
    n = write_baseline(path, result)
    print(f"froze {n} finding(s) into {args.out}")
    print("New problems will now fail; the frozen ones stay silent until you delete their lines.")
    return EXIT_OK


def main(argv=None) -> int:
    import mechcheck.rules  # noqa: F401  (registers every rule)

    # Windows consoles still default to cp1252; the reports contain dashes and
    # arrows, and a UnicodeEncodeError here would look like a tool crash.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return EXIT_USAGE
    handlers = {
        "check": cmd_check,
        "rules": cmd_rules,
        "explain": cmd_explain,
        "init": cmd_init,
        "fix": cmd_fix,
        "baseline": cmd_baseline,
        "terms": cmd_terms,
        "venues": cmd_venues,
    }
    try:
        return handlers[args.command](args)
    except KeyboardInterrupt:
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
