#!/usr/bin/env bash
# Verify mechcheck.sty against a real LaTeX installation.
#
# This is the one part of the toolchain that cannot be tested without TeX: it
# compiles a document containing four planted faults and asserts both that each
# is reported AND that the well-formed figure is not. A checker that cries wolf
# on correct input is worse than no checker, so the negative case is the one
# that matters most.
#
#   bash latex/verify-sty.sh
#
# Mirrors the `latex` job in .github/workflows/mechcheck.yml.

set -uo pipefail
cd "$(dirname "$0")/demo" || exit 1

pass=0
fail=0
ok()   { echo "  ok    $1"; pass=$((pass+1)); }
bad()  { echo "  FAIL  $1"; fail=$((fail+1)); }

if ! command -v latexmk >/dev/null 2>&1; then
  echo "latexmk not found on PATH."
  echo "If TeX Live is installed, open a new shell so PATH is picked up."
  exit 2
fi

echo "TeX: $(pdflatex --version 2>/dev/null | head -1)"
echo

cp ../mechcheck.sty . 2>/dev/null

# ---------------------------------------------------------------- default use
echo "demo.tex (hooks only, the default configuration)"
rm -f mechcheck-report.txt
if latexmk -pdf -interaction=nonstopmode -file-line-error demo.tex >compile.out 2>&1; then
  ok "compiles"
else
  bad "compiles — see latex/demo/compile.out"
  echo "        $(grep -m3 '^!' compile.out | tr '\n' ' ')"
fi

if [ -f mechcheck-report.txt ]; then
  ok "writes mechcheck-report.txt"
else
  bad "writes mechcheck-report.txt (the package produced no report)"
fi

for rule in MC001 MC002 MC003 MC004; do
  if grep -q "$rule" mechcheck-report.txt 2>/dev/null; then
    ok "$rule detected"
  else
    bad "$rule NOT detected"
  fi
done

# The correct figure must not be reported, and the package must not have
# quietly disabled itself.
if grep -q "fig:good" mechcheck-report.txt 2>/dev/null; then
  bad "false positive: the well-formed figure was reported"
else
  ok "no false positive on the well-formed figure"
fi

if grep -qi "could not instrument" demo.log 2>/dev/null; then
  bad "the package could not attach to \\caption in this class"
else
  ok "instrumentation attached (self-check passed)"
fi

# --------------------------------------------------------- the opt-in path
echo
echo "demo-crossref.tex ([crossref], which patches \\label and \\ref)"
rm -f mechcheck-report.txt
if latexmk -pdf -interaction=nonstopmode -file-line-error demo-crossref.tex >compile-crossref.out 2>&1; then
  ok "compiles"
else
  bad "compiles — see latex/demo/compile-crossref.out"
  echo "        $(grep -m3 '^!' compile-crossref.out | tr '\n' ' ')"
fi

if grep -q "MC006" mechcheck-report.txt 2>/dev/null; then
  ok "MC006 undefined reference detected"
else
  bad "MC006 NOT detected"
fi

# ------------------------------------------------- the CLI on the same demo
echo
echo "the CLI must agree with the package about this document"
if command -v python >/dev/null 2>&1; then
  ( cd ../.. && python -m mechcheck.cli check latex/demo --offline --build-dir latex/demo \
      --fail-on never --no-baseline >/dev/null 2>&1 ) \
    && ok "mechcheck CLI runs against the compiled demo" \
    || bad "mechcheck CLI failed on the compiled demo"
else
  echo "  skip  python not on PATH"
fi

echo
echo "--- report ---"
cat mechcheck-report.txt 2>/dev/null || echo "(none)"
echo
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ] || exit 1
