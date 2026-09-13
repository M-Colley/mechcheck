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

# TeX Live's installer only updates PATH for shells opened afterwards, and on
# Windows frequently not at all. Before giving up, look where it installs
# itself -- newest year first.
if ! command -v latexmk >/dev/null 2>&1; then
  while IFS= read -r d; do
    if [ -x "$d/latexmk" ] || [ -x "$d/latexmk.exe" ]; then
      PATH="$d:$PATH"; export PATH
      echo "Using TeX Live from $d (it was not on PATH)"
      break
    fi
  done < <(ls -d /c/texlive/*/bin/windows /c/texlive/*/bin/win32 \
                 /usr/local/texlive/*/bin/* /opt/texlive/*/bin/* \
                 "$HOME"/texlive/*/bin/* /Library/TeX/texbin 2>/dev/null | sort -r)
fi
if ! command -v latexmk >/dev/null 2>&1; then
  echo "latexmk not found on PATH, and no TeX Live installation in the usual places."
  echo "Install TeX Live (https://tug.org/texlive/) or add its bin directory to PATH, then re-run."
  exit 2
fi

echo "TeX: $(pdflatex --version 2>/dev/null | head -1)"
echo

cp ../mechcheck.sty . 2>/dev/null

# ---------------------------------------------------------------- default use
echo "demo.tex (hooks only, the default configuration)"
# latexmk skips a run when nothing changed, which would leave a stale or
# missing report and fail every assertion below for the wrong reason.
latexmk -C >/dev/null 2>&1
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

# The correct figure must not be reported. Counting is the honest test here:
# the messages do not name labels, so grepping for the good figure's label
# would pass no matter what. The demo has five figures, four of them faulty.
floats=$(grep -oE '[0-9]+ float\(s\) checked' mechcheck-report.txt 2>/dev/null | grep -oE '^[0-9]+' | head -1)
mc001=$(grep -c "MC001" mechcheck-report.txt 2>/dev/null)
if [ "${floats:-0}" = "5" ]; then
  ok "all five floats were seen"
else
  bad "expected 5 floats checked, report says '${floats:-none}'"
fi
if [ "$mc001" = "4" ]; then
  ok "no false positive: 4 of 5 figures reported, the well-formed one is not"
else
  bad "expected exactly 4 MC001 findings, got $mc001 (5 would mean the correct figure was flagged)"
fi

# Overleaf compiles main.tex with -jobname=output, so \jobname is not a file
# the author has. Locations must never be built from it.
if grep -qE "^(warn|error) MC[0-9]+ demo:" mechcheck-report.txt 2>/dev/null; then
  bad "locations were built from \jobname instead of the real file"
else
  ok "locations do not invent a filename from \jobname"
fi

# acmart patches space to warn about exactly the use the report page made.
if grep -q "vspace should only be used" compile.out 2>/dev/null; then
  bad "the report page provoked a class warning of its own"
else
  ok "the report page provokes no class warnings"
fi

if grep -qi "could not instrument" demo.log 2>/dev/null; then
  bad "the package could not attach to \\caption in this class"
else
  ok "instrumentation attached (self-check passed)"
fi

# --------------------------------------------------------- the opt-in path
echo
echo "demo-crossref.tex ([crossref], which patches \\label and \\ref)"
latexmk -C >/dev/null 2>&1
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
