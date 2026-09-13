/**
 * Runs the browser engine outside a browser, against the same fixtures the
 * Python checker was verified on. If the two disagree, one of them is wrong --
 * and a student who gets different answers from the two would rightly stop
 * trusting both.
 *
 *   node browser/test-engine.mjs
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));
const repo = join(here, "..");

// --- load the engine, minus the browser-only interface section -------------
const html = readFileSync(join(here, "mechcheck.html"), "utf8");
const script = html.slice(html.indexOf("<script>") + 8, html.lastIndexOf("</script>"));
const engine = script.slice(0, script.indexOf("/* ===================== 7. Interface"));

const module = await import("data:text/javascript;base64," +
  Buffer.from(engine + "\nexport { runChecks, applyFixes, TexProject, parseBib, similarity, findMainDocument, RULES, SEV, collectFiles, readZip };").toString("base64"));
const { runChecks, applyFixes, parseBib, similarity, findMainDocument, RULES, SEV } = module;

// --- helpers ---------------------------------------------------------------
function loadDir(dir) {
  const files = new Map();
  (function walk(d) {
    for (const name of readdirSync(d)) {
      const full = join(d, name);
      if (statSync(full).isDirectory()) walk(full);
      else files.set(relative(dir, full).split(sep).join("/"), new Uint8Array(readFileSync(full)));
    }
  })(dir);
  return files;
}

let passed = 0, failed = 0;
const fail = (name, detail) => { failed++; console.log(`  FAIL  ${name}\n        ${detail}`); };
const pass = name => { passed++; console.log(`  ok    ${name}`); };
function check(name, cond, detail = "") { cond ? pass(name) : fail(name, detail); }

// --- 1. the engine loads and every rule is documented ----------------------
console.log("\nrule registry");
check("rules registered", RULES.length >= 100, `only ${RULES.length}`);
const undocumented = RULES.filter(r => !r.why || r.why.length < 20).map(r => r.id);
check("every rule explains itself", undocumented.length === 0, undocumented.join(", "));
const ids = RULES.map(r => r.id);
check("no duplicate rule ids", new Set(ids).size === ids.length,
      ids.filter((id, i) => ids.indexOf(id) !== i).join(", "));

// --- 2. parsing ------------------------------------------------------------
console.log("\nparsing");
{
  const bib = parseBib(`
@inproceedings{colley2021,
  author = {Colley, Mark and Rukzio, Enrico},
  title = {A Design Space for {External} Communication},
  booktitle = {Proceedings of AutomotiveUI},
  year = {2020},
  doi = {10.1145/3409120.3410646},
  pages = {101-110}
}
@article{other, author = "Doe, Jane", title = "Another", journal = "J", year = 2023,
  url = {https://doi.org/10.1000/xyz}}
`, "refs.bib");
  check("parses both delimiter styles", bib.length === 2, `got ${bib.length}`);
  check("surnames", JSON.stringify(bib[0].authorSurnames()) === '["Colley","Rukzio"]', JSON.stringify(bib[0].authorSurnames()));
  check("year", bib[0].year === 2020, String(bib[0].year));
  check("doi from url", bib[1].doi === "10.1000/xyz", bib[1].doi);
  check("title braces stripped for comparison", bib[0].title === "A Design Space for External Communication", bib[0].title);
  check("field line numbers", bib[0].lineOf("pages") > bib[0].line, `${bib[0].lineOf("pages")} vs ${bib[0].line}`);
}
check("similarity: subtitle tolerated",
      similarity("A Design Space for External Communication",
                 "A Design Space for External Communication of Vehicles") > 0.7);
check("similarity: different works separated",
      similarity("A Design Space for External Communication",
                 "Knitting Patterns of the Nineteenth Century") < 0.4);

// --- 3. the fixtures, checked exactly as the browser would -----------------
async function run(dir, options = {}) {
  return runChecks(loadDir(join(repo, "tests", "fixtures", dir)), { verify: false, ...options });
}
const rulesFired = r => new Set(r.findings.map(f => f.rule));

console.log("\nfixture: sample (thesis)");
{
  const r = await run("sample", { profile: "thesis", stage: "submission" });
  const fired = rulesFired(r);
  check("finds the main file", r.stats.main === "main.tex", r.stats.main);
  check("follows \\input across files", r.stats.files === 2, String(r.stats.files));
  check("FIG003 unreferenced figure", fired.has("FIG003"));
  check("REF001 undefined label", fired.has("REF001"));
  check("ABB001 abbreviation reintroduced", fired.has("ABB001"));
  check("FIG002 table without a label", fired.has("FIG002"));
  const verbatimLeak = r.findings.some(f => (f.context || "").includes("fig:notreal"));
  check("verbatim content ignored", !verbatimLeak);
  const commentLeak = [...fired].includes("REF001") &&
    r.findings.filter(f => f.rule === "REF001").some(f => f.message.includes("nothing"));
  check("commented-out reference ignored", !commentLeak);
}

console.log("\nfixture: paper (AutoUI, anonymous)");
{
  const r = await run("paper", { profile: "paper-anonymous", stage: "submission", venue: "autoui" });
  const fired = rulesFired(r);
  for (const id of ["VEN002", "VEN003", "VEN004", "ANON001", "ANON003", "ACC001", "ACC004", "POL005", "POL006", "POL007"])
    check(`${id} fires`, fired.has(id));
  check("ANON004 reported once per line",
        r.findings.filter(f => f.rule === "ANON004").length === 1,
        String(r.findings.filter(f => f.rule === "ANON004").length));
  check("POL008 defers to the venue pack", !fired.has("POL008"));
}

console.log("\nfixture: bib (offline rules only)");
{
  const r = await run("bib", { profile: "thesis" });
  const fired = rulesFired(r);
  check("BIB006 et al. in authors", fired.has("BIB006"));
  check("BIB008 page range", fired.has("BIB008"));
  check("bib entries parsed", r.stats.references === 5, String(r.stats.references));
}

console.log("\nfixture: style");
{
  const r = await run("style", { profile: "thesis" });
  const fired = rulesFired(r);
  for (const id of ["STY001", "STY002", "STY003", "STY005", "STY007", "STY013"])
    check(`${id} fires`, fired.has(id));
}

console.log("\nfixture: refstyle (autoref and citet preferences)");
{
  const r = await run("refstyle", { profile: "paper" });
  const fired = rulesFired(r);
  const ref008 = r.findings.filter(f => f.rule === "REF008");
  const ref009 = r.findings.filter(f => f.rule === "REF009");
  check("REF008 flags a word-prefixed reference", fired.has("REF008"));
  check("REF009 flags a name written before a citation", fired.has("REF009"));
  // Figure~ref, Table~ref, Figure~autoref (the doubled word) and Figure \ref.
  // Section~ref is deliberately absent: \autoref takes the word from the level
  // of the target, so it prints "Subsection" for a \subsection where the
  // convention is "Section" at every depth. Writing that word out is a choice.
  check("REF008 count", ref008.length === 4, String(ref008.length));
  check("REF008 leaves section references alone",
        !ref008.some(f => (f.message || "").includes("Section")),
        ref008.map(f => f.message).join(" | "));
  // "Colley et al." and "Rukzio and Colley". A lone surname is deliberately
  // not reported: on a real paper that shape produced nine wrong findings
  // ("Questionnaire~cite", "ANOVA~cite"), and it carries an auto-fix.
  check("REF009 count", ref009.length === 2, String(ref009.length));
  check("REF008 catches the doubled word", ref008.some(f => f.message.includes("twice")));
  check("REF009 suggests citet under acmart",
        ref009.every(f => (f.fix || "").includes("citet")), ref009.map(f => f.fix).join(" | "));
  // REF004 stands aside only where REF008 speaks. "Section \ref" is nobody
  // else's business, and a missing tie there is still a bad line break.
  const ref004 = r.findings.filter(f => f.rule === "REF004");
  check("REF004 stands aside where REF008 speaks", ref004.length === 1,
        ref004.map(f => f.message).join(" | "));
  check("REF004 still reports a missing tie on a section",
        ref004.every(f => (f.message || "").includes("Section")),
        ref004.map(f => f.message).join(" | "));
}

console.log("\nfixture: selftest (the document you paste into Overleaf)");
{
  const r = await run("selftest", { profile: "paper-anonymous", stage: "submission", venue: "autoui" });
  const counts = {};
  for (const f of r.findings) counts[f.rule] = (counts[f.rule] || 0) + 1;
  // The same list is asserted by tests/test_selftest.py. If the two ever
  // disagree, one implementation has drifted -- which is the single most
  // damaging thing that could happen to a checker people run in two places.
  const EXPECTED = {
    ABB001: 1, ACC001: 2, ACC004: 1, ANON001: 1, ANON003: 1, ANON004: 2, ANON005: 1,
    BIB006: 1, BIB008: 1, BIB009: 1, FIG003: 1, MET003: 1, MET004: 1,
    POL001: 1, POL002: 1, POL003: 1, POL004: 1, POL005: 1, POL006: 1, POL007: 1,
    REF001: 1, REF008: 2, REF009: 2, STY001: 1, STY003: 1, STY005: 1, STY007: 1,
    STY016: 1, VEN002: 2, VEN003: 1, VEN004: 2,
  };
  const wrong = [];
  for (const [id, n] of Object.entries(EXPECTED))
    if (counts[id] !== n) wrong.push(`${id}: expected ${n}, got ${counts[id] || 0}`);
  for (const id of Object.keys(counts))
    if (!(id in EXPECTED)) wrong.push(`${id}: unexpected (${counts[id]})`);
  check("self-test document produces exactly the documented findings",
        wrong.length === 0, wrong.join("; "));
  check("self-test totals", r.findings.length === 37, String(r.findings.length));
}

// --- 4. behaviour that protects the user ----------------------------------
console.log("\nbehaviour");
{
  const tex = new TextEncoder().encode(
    "\\documentclass{article}\n\\begin{document}\n" +
    "\\begin{figure}\\caption{A}\\label{fig:a}\\end{figure}  % mechcheck: off FIG003 -- decorative\n" +
    "\\end{document}\n");
  const r = await runChecks(new Map([["main.tex", tex]]), { profile: "thesis", verify: false });
  check("inline suppression works", !rulesFired(r).has("FIG003"));
  check("suppressed findings are counted", r.suppressed.length === 1, String(r.suppressed.length));
}
{
  const tex = new TextEncoder().encode("\\documentclass{article}\n\\begin{document}\nThis is TODO.\n\\end{document}\n");
  const draft = await runChecks(new Map([["main.tex", tex]]), { profile: "thesis", stage: "draft", verify: false });
  const final = await runChecks(new Map([["main.tex", tex]]), { profile: "thesis", stage: "final", verify: false });
  const sev = res => (res.findings.find(f => f.rule === "STY001") || {}).severity;
  check("draft stage demotes", sev(draft) === SEV.info, String(sev(draft)));
  check("final stage keeps errors blocking", sev(final) === SEV.error, String(sev(final)));
}
{
  const r = await runChecks(new Map([["main.tex", new TextEncoder().encode(
    "\\documentclass{article}\n\\begin{document}\\end{document}")]]), { profile: "thesis", verify: false });
  check("empty document does not crash", Array.isArray(r.findings));
}
{
  let threw = false;
  try { await runChecks(new Map([["notes.txt", new TextEncoder().encode("hello")]]), {}); }
  catch (err) { threw = /\.tex/i.test(err.message); }
  check("a project with no .tex explains itself", threw);
}
{
  // An unusual preamble must not stop the check: guess the root, and say so.
  const odd = new TextEncoder().encode("\\input{preamble}\n\\begin{document}\nSome text here.\n\\end{document}\n");
  const r = await runChecks(new Map([["odd.tex", odd]]), { profile: "thesis", verify: false });
  check("falls back to a best-guess main file", r.stats.main === "odd.tex", r.stats.main);
  check("and flags that it guessed", r.stats.mainGuessed === true);
}
{
  const r = await runChecks(new Map([["main.tex", new TextEncoder().encode(
    "\\documentclass{article}\n\\begin{document}\nText.\n\\end{document}")]]), { profile: "thesis", verify: false });
  check("online rules are skipped when verification is off",
        Object.keys(r.skipped).some(id => id.startsWith("BIO")));
  check("no rule crashed", !r.findings.some(f => f.rule === "INT001"),
        r.findings.filter(f => f.rule === "INT001").map(f => f.message).join("; "));
}

console.log("\nvolume: one habit must not bury everything else");
{
  const enc = new TextEncoder();
  const lines = [];
  for (let i = 0; i < 25; i++) lines.push(`This is is repeated line number ${i} here.`);
  const doc = "\\documentclass{article}\n\\begin{document}\n" + lines.join("\n") + "\n\\end{document}\n";
  const files = () => new Map([["main.tex", enc.encode(doc)]]);

  const capped = await runChecks(files(), { profile: "thesis", verify: false });
  const sty = capped.findings.filter(f => f.rule === "STY003");
  check("a rule is capped", sty.length === 10, String(sty.length));
  check("the rest are held, not dropped", capped.truncated.length === 15, String(capped.truncated.length));
  check("held findings are counted per rule",
        capped.truncatedByRule.STY003 === 15, JSON.stringify(capped.truncatedByRule));

  const total = capped.findings.concat(capped.truncated).filter(f => f.rule === "STY003").length;
  check("nothing is lost", total === 25, String(total));

  const uncapped = await runChecks(files(), { profile: "thesis", verify: false, maxPerRule: 0 });
  check("the cap can be turned off",
        uncapped.findings.filter(f => f.rule === "STY003").length === 25);
  check("and then nothing is held", uncapped.truncated.length === 0);

  const custom = await runChecks(files(), { profile: "thesis", verify: false, maxPerRule: 3 });
  check("a custom cap is honoured",
        custom.findings.filter(f => f.rule === "STY003").length === 3);

  // Python asserts the identical numbers in tests/test_volume.py.
  check("browser and Python agree on the cap", sty.length === 10 && capped.truncated.length === 15);
}

console.log("\nreal-paper false positives");
{
  const enc = new TextEncoder();
  const doc = (body, cls) => new Map([["main.tex",
    enc.encode("\\documentclass{" + (cls || "acmart") + "}\n\\begin{document}\n" + body + "\n\\end{document}\n")]]);
  const opts = { profile: "thesis", verify: false, maxPerRule: 0 };
  const fired = async (files, o) =>
    new Set((await runChecks(files, { ...opts, ...o })).findings.map(f => f.rule));

  check("a noun before a citation is not a name",
        !(await fired(doc("We used the Questionnaire~\\cite{a} and the Scale~\\cite{b}."))).has("REF009"));
  check("an acronym before a citation is not a name",
        !(await fired(doc("We used ANOVA~\\cite{a} and VR~\\cite{b}."))).has("REF009"));
  check("et al. is still reported",
        (await fired(doc("Colley et al.~\\cite{a} showed this."))).has("REF009"));
  check("two surnames are still reported",
        (await fired(doc("Rukzio and Colley~\\cite{a} disagree."))).has("REF009"));

  check("unreferenced section labels are exempt",
        !(await fired(doc("\\section{Method}\\label{sec:m}\nText here for it."))).has("REF002"));

  check("a section opening on a subsection is not empty",
        !(await fired(doc("\\section{Related Work}\n\\subsection{VR in training}\nPlenty of real content lives here indeed."))).has("STR004"));

  check("a product number is not a range",
        !(await fired(doc("The machine had a Core 7-1355 processor inside."))).has("STY007"));
  check("a real range is still reported",
        (await fired(doc("We recruited 10-20 participants for the study."))).has("STY007"));

  const theRules = [...(await fired(doc("A paper, not a thesis.", "acmart")))].filter(r => r.startsWith("THE"));
  check("thesis rules do not fire on a paper class", theRules.length === 0, theRules.join(","));

  // STR005: only the words after the first tell the two conventions apart,
  // so a one-word heading decides nothing and must not be counted as either.
  const sections = (...titles) =>
    titles.map(t => String.raw`\section{` + t + "}\n\nSome text in the section.").join("\n\n");

  check("one-word headings are not reported as miscapitalised",
        !(await fired(doc(sections("Motivation", "Participants", "Apparatus", "Analysis",
                                   "Study Design", "Design Implications")))).has("STR005"));
  check("a heading whose only other word is short is not reported",
        !(await fired(doc(sections("Research Gap", "Future Work", "Related Work",
                                   "Study Design", "Design Implications",
                                   "Summary of Contributions")))).has("STR005"));
  check("a genuine mixture of heading styles is still reported",
        (await fired(doc(sections("Study Design", "Design Implications",
                                  "Summary of Contributions", "Related Work Overview",
                                  "The odd one out here")))).has("STR005"));

  // ANON002: acmart removes its own acks environment under the anonymous
  // option (\excludecomment{acks}), so the content never reaches a reviewer.
  const acmartDoc = (body, options) => new Map([["main.tex",
    enc.encode("\\documentclass[" + options + "]{acmart}\n\\begin{document}\n" + body + "\n\\end{document}\n")]]);
  const ACKS = "\\begin{acks}\nWe thank all study participants.\n\\end{acks}";

  check("acks under the anonymous option is not reported",
        !(await fired(acmartDoc(ACKS, "manuscript,screen,review,anonymous"),
                      { profile: "paper-anonymous" })).has("ANON002"));
  check("acks without the anonymous option is still reported",
        (await fired(acmartDoc(ACKS, "manuscript,screen,review"),
                     { profile: "paper-anonymous" })).has("ANON002"));
  check("a plain acknowledgements section is still reported",
        (await fired(acmartDoc("\\section{Acknowledgements}\nWe thank the participants.",
                               "manuscript,screen,review,anonymous"),
                     { profile: "paper-anonymous" })).has("ANON002"));
  check("a funder named inside acks is not reported",
        !(await fired(acmartDoc("\\begin{acks}\nFunded by the Deutsche Forschungsgemeinschaft.\n\\end{acks}",
                                "manuscript,screen,review,anonymous"),
                      { profile: "paper-anonymous" })).has("ANON004"));
  check("a link inside anonsuppress is not reported",
        !(await fired(acmartDoc("\\begin{anonsuppress}\nCode: https://github.com/mcolley/study\n\\end{anonsuppress}",
                                "manuscript,screen,review,anonymous"),
                      { profile: "paper-anonymous" })).has("ANON003"));

  // ABB004: names of technologies and standards work as proper nouns.
  check("protocol and format names need no introduction",
        !(await fired(doc("The client speaks TCP and UDP, exchanges JSON over HTTPS, " +
                          "and stores the result as a PDF on an SSD."))).has("ABB004"));
  check("domain jargon is still reported",
        (await fired(doc("The ADAS relies on the eHMI, and the TOR was issued."))).has("ABB004"));

  // A figure is a PDF too: it must not be mistaken for the compiled output.
  const withFigure = doc("\\section{A}\nText here in the section.");
  withFigure.set("figures/plot.pdf", enc.encode("%PDF-1.4\n" + "x".repeat(400)));
  const r = await runChecks(withFigure, opts);
  check("a figure PDF is not treated as the compiled output",
        !r.stats.hasPdf, String(r.stats.hasPdf));
}

console.log("\nautomatic fixes");
{
  const enc = new TextEncoder();
  const source = String.raw`\documentclass{acmart}
\begin{document}
The Automated Driving System (ADS) is new. The ADS works well.
Later the Automated Driving System (ADS) appears again here.
As shown in Figure~\ref{fig:a} and Table~\ref{tab:b}.
Colley et al.~\cite{a} showed this. Bazilinskyy~\cite{b} did too.
This is is repeated, with a space before , this comma, and 10-20 people.
\end{document}
`;
  const load = text => new Map([["main.tex", enc.encode(text)]]);
  const opts = { profile: "paper", verify: false, maxPerRule: 0 };

  const before = await runChecks(load(source), opts);
  const fx = applyFixes(before);
  const fixed = fx.files.get("main.tex");

  check("a corrected file is produced", !!fixed);
  check("the prefixed reference becomes autoref", fixed.includes(String.raw`\autoref{fig:a}`));
  check("the name before a citation becomes citet", fixed.includes(String.raw`\citet{a}`));
  check("the repeated word is gone", fixed.includes("This is repeated,"));
  check("the space before punctuation is closed up", !fixed.includes(" ,"));
  check("the numeric range gets an en dash", fixed.includes("10--20"));

  // ABB001 must delete only the words that make the acronym.
  check("the second expansion is collapsed",
        fixed.includes("Later the ADS appears again here."), fixed.split("\n")[3]);
  check("the first expansion is kept",
        (fixed.match(/Automated Driving System \(ADS\)/g) || []).length === 1);

  // A lone surname is not a REF009 case, so the text must be untouched.
  check("a lone surname is left alone", fixed.includes(String.raw`Bazilinskyy~\cite{b}`));
  check("alt text is never fixed", !fx.applied.some(a => a.rule.startsWith("ACC")));

  // The safety property: re-check the corrected text; nothing may be worse.
  const after = await runChecks(load(fixed), opts);
  const tally = res => {
    const c = {};
    for (const f of res.findings.concat(res.truncated || [])) c[f.rule] = (c[f.rule] || 0) + 1;
    return c;
  };
  const b = tally(before), a = tally(after);
  const grew = Object.entries(a).filter(([k, v]) => v > (b[k] || 0));
  check("re-checking the corrected file finds nothing new", grew.length === 0, JSON.stringify(grew));
  for (const id of ["ABB001", "REF008", "REF009", "STY003", "STY005", "STY007"])
    check(`${id} is resolved`, !a[id], String(a[id]));

  // Python asserts the same behaviours in tests/test_fixer.py.
  const clean = await runChecks(load("\\documentclass{acmart}\n\\begin{document}\nOrdinary text here.\n\\end{document}\n"), opts);
  check("a clean document yields no fixes", applyFixes(clean).files.size === 0);
}

// --- 5. the zip path, which is how most people will actually use it -------
console.log("\nzip reading");
{
  const zipPath = join(here, "test-project.zip");
  let zipBytes = null;
  try { zipBytes = readFileSync(zipPath); } catch (err) { /* generated below if absent */ }
  if (!zipBytes) {
    console.log("  skip  no test-project.zip (run scripts that build it first)");
  } else {
    // collectFiles only needs .name and .arrayBuffer(), so a plain object does.
    const fake = { name: "overleaf-project.zip",
                   arrayBuffer: async () => zipBytes.buffer.slice(zipBytes.byteOffset, zipBytes.byteOffset + zipBytes.byteLength) };
    const files = await module.collectFiles([fake]);
    check("zip entries are decompressed", files.size === 3, `got ${files.size}: ${[...files.keys()]}`);
    check("nested paths survive", files.has("sections/extra.tex"), [...files.keys()].join(", "));
    const r = await runChecks(files, { profile: "thesis", verify: false });
    check("a zipped project checks end to end", r.stats.main === "main.tex", r.stats.main);
    check("bib inside the zip is read", r.stats.references === 1, String(r.stats.references));
  }
}

console.log("\nrules added in September 2026 (the same cases as tests/test_new_rules.py)");
{
  const enc = new TextEncoder();
  const doc = (body, preamble = "", cls = "article") => new Map([["main.tex",
    enc.encode("\\documentclass{" + cls + "}\n" + preamble + "\\begin{document}\n" + body + "\n\\end{document}\n")]]);
  const opts = { profile: "all", verify: false, maxPerRule: 0 };
  const firedIn = async (files, o) => new Set((await runChecks(files, { ...opts, ...o })).findings.map(f => f.rule));
  const findingsOf = async (files, id, o) => (await runChecks(files, { ...opts, ...o })).findings.filter(f => f.rule === id);
  const fixedText = async files => applyFixes(await runChecks(files, opts)).files.get("main.tex") || "";
  const FIGURE = p => String.raw`\begin{figure}\includegraphics{` + p + String.raw`}\caption{A}\label{fig:a}\end{figure} See \autoref{fig:a}.`;
  let files, f, r;

  // FIG012 / FIG008 / FIG015: where the graphics really are
  files = doc(FIGURE("Figures/Plot.png")); files.set("figures/plot.png", enc.encode("png"));
  f = await firedIn(files);
  check("FIG012 a case mismatch is FIG012, not FIG008", f.has("FIG012") && !f.has("FIG008"), [...f].join(","));
  check("FIG012 the fix is the disk spelling", (await findingsOf(files, "FIG012"))[0].edit.replacement === "figures/plot.png");
  files = doc(FIGURE("figures/plot.png")); files.set("figures/plot.png", enc.encode("png"));
  f = await firedIn(files);
  check("FIG012 the exact spelling passes", !f.has("FIG012") && !f.has("FIG008"), [...f].join(","));
  files = doc(FIGURE("figures/plot")); files.set("figures/plot.PNG", enc.encode("png"));
  f = await firedIn(files);
  check("FIG012 an upper-case extension is fine when none is written", !f.has("FIG012") && !f.has("FIG008"), [...f].join(","));
  files = doc(FIGURE("figures/nothing.png")); files.set("figures/plot.png", enc.encode("png"));
  check("FIG008 a genuinely missing graphic is still FIG008", (await firedIn(files)).has("FIG008"));
  f = await firedIn(doc(FIGURE("C:/Users/mark/Desktop/plot.png")));
  check("FIG015 an absolute path", f.has("FIG015") && !f.has("FIG008"), [...f].join(","));
  f = await firedIn(doc(FIGURE(String.raw`\figdir/plot`)));
  check("FIG015 a macro-built path is neither missing nor absolute", !f.has("FIG015") && !f.has("FIG008"), [...f].join(","));

  // FIG013, FIG014
  check("FIG013 center inside a float",
        (await firedIn(doc(String.raw`\begin{figure}\begin{center}x\end{center}\caption{A}\label{fig:a}\end{figure} See \autoref{fig:a}.`))).has("FIG013"));
  check("FIG013 centering is fine",
        !(await firedIn(doc(String.raw`\begin{figure}\centering x\caption{A}\label{fig:a}\end{figure} See \autoref{fig:a}.`))).has("FIG013"));
  check("FIG014 a float referred to by position",
        (await findingsOf(doc("Shown in the figure below, and the table above lists them."), "FIG014")).length === 2);
  check("FIG014 a numbered reference is fine",
        !(await firedIn(doc(String.raw`Shown in Figure~\ref{fig:a} and \autoref{tab:b}.`))).has("FIG014"));

  // REF010, REF011
  r = await findingsOf(doc(String.raw`Prior work~\cite{a}\cite{b} agrees.`), "REF010");
  check("REF010 adjacent citations", r.length === 1 && r[0].edit.replacement === String.raw`\cite{a,b}`);
  check("REF010 the fix merges them",
        (await fixedText(doc(String.raw`Prior work~\cite{a}\cite{b} agrees.`))).includes(String.raw`\cite{a,b} agrees`));
  r = await findingsOf(doc(String.raw`Prior work~\cite{a}, \cite{b} \cite{c} agrees.`), "REF010");
  check("REF010 a chain of three is one finding", r.length === 1 && r[0].edit.replacement === String.raw`\cite{a,b,c}`,
        r.map(x => x.edit && x.edit.replacement).join(" | "));
  check("REF010 'and' between citations is left alone", !(await firedIn(doc(String.raw`Both \cite{a} and \cite{b} agree.`))).has("REF010"));
  check("REF010 different commands are not merged", !(await firedIn(doc(String.raw`See \citep{a}\citet{b} here.`, "", "acmart"))).has("REF010"));
  check("REF011 a citation as the subject", (await firedIn(doc(String.raw`Some text here. \cite{a} showed that this works.`))).has("REF011"));
  check("REF011 'In [12], the authors'", (await firedIn(doc(String.raw`Some text here. In \cite{a}, the authors argue this.`))).has("REF011"));
  check("REF011 a citation after a name is not a noun", !(await firedIn(doc(String.raw`Colley et al. \cite{a} showed that this works.`))).has("REF011"));
  check("REF011 mid-sentence is fine", !(await firedIn(doc(String.raw`This was shown earlier \cite{a} and confirmed since.`))).has("REF011"));

  // STY015 - STY020
  check("STY015 a typed ellipsis is fixed",
        (await fixedText(doc("Wait for it... and then it happens."))).includes(String.raw`Wait for it\dots{} and then`));
  check("STY015 \\dots is fine", !(await firedIn(doc(String.raw`Wait for it\dots{} and then.`))).has("STY015"));
  r = await findingsOf(doc("The code is at https://github.com/x/y for review."), "STY016");
  check("STY016 a bare URL, with no fix when nothing can wrap it", r.length === 1 && r[0].edit === null);
  check("STY016 wrapped URLs are fine",
        !(await firedIn(doc(String.raw`See \url{https://github.com/x/y} and \href{https://example.org/a_b}{the page}.`, "\\usepackage{hyperref}\n"))).has("STY016"));
  check("STY016 a preamble macro is fine",
        !(await firedIn(doc(String.raw`See \repo.`, String.raw`\newcommand{\repo}{https://github.com/x/y}` + "\n"))).has("STY016"));
  check("STY016 the fix wraps when hyperref is loaded",
        (await fixedText(doc("The code is at https://github.com/x/y.", "\\usepackage{hyperref}\n"))).includes(String.raw`\url{https://github.com/x/y}.`));
  check("STY017 a space before footnote is closed",
        (await fixedText(doc(String.raw`A claim \footnote{Source.} here.`))).includes(String.raw`A claim\footnote{Source.} here.`));
  check("STY017 an attached footnote is fine", !(await firedIn(doc(String.raw`A claim\footnote{Source.} here.`))).has("STY017"));
  check("STY018 a sentence starting with a numeral", (await firedIn(doc("We ran a study. 12 participants took part in it."))).has("STY018"));
  check("STY018 numbers inside a sentence are fine", !(await firedIn(doc("We recruited 12 participants, and Table 3 lists the values."))).has("STY018"));
  check("STY019 \\bf and $$", (await findingsOf(doc(String.raw`{\bf Bold} text and $$x = 1$$ here.`), "STY019")).length === 2);
  check("STY019 modern syntax is fine",
        !(await firedIn(doc(String.raw`\textbf{Bold} and \begin{itemize}\item one\end{itemize} and \[ x = 1 \] and \ttfamily.`))).has("STY019"));
  check("STY020 a mistyped et al. is fixed",
        (await fixedText(doc("Colley et. al. showed it. Rukzio et al showed it too."))).includes("Colley et al. showed it. Rukzio et al. showed it too."));
  check("STY020 a correct et al. is fine", !(await firedIn(doc(String.raw`Colley et al.~\cite{a} showed it, and they also agree.`))).has("STY020"));

  // STR010 - STR013
  r = await findingsOf(doc("Text.", "\\usepackage{subfigure}\n"), "STR010");
  check("STR010 an obsolete package names its replacement", r.length === 1 && r[0].fix.includes("subcaption"));
  check("STR010 utf8x is obsolete", (await firedIn(doc("Text.", "\\usepackage[utf8x]{inputenc}\n"))).has("STR010"));
  check("STR010 current packages are fine", !(await firedIn(doc("Text.", "\\usepackage{subcaption}\n\\usepackage[utf8]{inputenc}\n"))).has("STR010"));
  r = await findingsOf(doc("Text.", "\\usepackage{graphicx}\n\\usepackage{graphicx}\n"), "STR011");
  check("STR011 loaded twice is a note", r.length === 1 && r[0].severity === SEV.info);
  r = await findingsOf(doc("Text.", "\\usepackage[table]{xcolor}\n\\usepackage[dvipsnames]{xcolor}\n"), "STR011");
  check("STR011 an option clash is a warning", r.length === 1 && r[0].severity === SEV.warn && r[0].message.includes("option clash"));
  check("STR011 one branch of a switch is not a duplicate",
        !(await firedIn(doc("Text.", String.raw`\def\draftmode{}` + "\n" + String.raw`\ifdefined\draftmode` + "\n"
                                    + String.raw`  \usepackage[draft]{thesis}` + "\n" + String.raw`\else` + "\n"
                                    + String.raw`  \usepackage[final]{thesis}` + "\n" + String.raw`\fi` + "\n"))).has("STR011"));
  check("STR011 fontenc per encoding is fine", !(await firedIn(doc("Text.", "\\usepackage[T1]{fontenc}\n\\usepackage[T2A]{fontenc}\n"))).has("STR011"));
  check("STR012 cleveref before hyperref", (await firedIn(doc("Text.", "\\usepackage{cleveref}\n\\usepackage{hyperref}\n"))).has("STR012"));
  check("STR012 cleveref after hyperref is fine", !(await firedIn(doc("Text.", "\\usepackage{hyperref}\n\\usepackage{cleveref}\n"))).has("STR012"));
  check("STR012 hyperref out of sight is not assumed missing", !(await firedIn(doc("Text.", "\\usepackage{cleveref}\n"))).has("STR012"));
  files = doc(String.raw`\input{Chapters/Intro}`); files.set("chapters/intro.tex", enc.encode("Intro text here."));
  f = await firedIn(files);
  check("STR013 an input with the wrong case is STR013, not STR001", f.has("STR013") && !f.has("STR001"), [...f].join(","));
  files = doc(String.raw`\input{chapters/intro}`); files.set("chapters/intro.tex", enc.encode("Intro text here."));
  f = await firedIn(files);
  check("STR013 an exact input is fine", !f.has("STR013") && !f.has("STR001"), [...f].join(","));
  f = await firedIn(doc(String.raw`\input{C:/Users/mark/thesis/intro.tex}`));
  check("STR013 an absolute input is STR013, not STR001", f.has("STR013") && !f.has("STR001"), [...f].join(","));
  files = doc(String.raw`\input{chapters/nowhere}`); files.set("chapters/intro.tex", enc.encode("Intro."));
  f = await firedIn(files);
  check("STR001 a missing input is still STR001", f.has("STR001") && !f.has("STR013"), [...f].join(","));

  // BIB013 - BIB017
  const bibdoc = bib => { const m = doc(String.raw`Cited~\cite{k1}.` + "\n" + String.raw`\bibliography{refs}`); m.set("refs.bib", enc.encode(bib)); return m; };
  const entry = (key, fields) => "@inproceedings{" + key + ",\n"
    + Object.entries({ author: "Doe, Jane", title: "A Quiet Title", year: "2020", ...fields }).map(([k, v]) => `  ${k} = {${v}},`).join("\n") + "\n}\n";
  check("BIB013 a booktitle starting with In", (await firedIn(bibdoc(entry("k1", { booktitle: "In Proceedings of the CHI Conference" })))).has("BIB013"));
  check("BIB013 a booktitle that merely starts with the letters is fine", !(await firedIn(bibdoc(entry("k1", { booktitle: "Interaction Design and Children" })))).has("BIB013"));
  check("BIB014 a title in capitals", (await firedIn(bibdoc(entry("k1", { title: "A STUDY OF VERY LOUD TITLES", booktitle: "CHI" })))).has("BIB014"));
  check("BIB014 an ordinary title is fine", !(await firedIn(bibdoc(entry("k1", { title: "A Study of the ACM and IEEE Styles", booktitle: "CHI" })))).has("BIB014"));
  check("BIB015 a url that repeats the doi", (await firedIn(bibdoc(entry("k1", { booktitle: "CHI", doi: "10.1145/1.2", url: "https://doi.org/10.1145/1.2" })))).has("BIB015"));
  check("BIB015 a url to somewhere else is fine", !(await firedIn(bibdoc(entry("k1", { booktitle: "CHI", doi: "10.1145/1.2", url: "https://example.org/paper" })))).has("BIB015"));
  check("BIB016 a title ending with a period", (await firedIn(bibdoc(entry("k1", { title: "A Quiet Title.", booktitle: "CHI" })))).has("BIB016"));
  check("BIB016 a title ending in an initial is fine", !(await firedIn(bibdoc(entry("k1", { title: "Proceedings of Part A.", booktitle: "CHI" })))).has("BIB016"));
  r = await findingsOf(bibdoc(entry("k1", { booktitle: "CHI" }) + entry("K1", { booktitle: "UIST" })), "BIB017");
  check("BIB017 a duplicate key", r.length === 1 && r[0].severity === SEV.error);
  check("BIB017 distinct keys are fine", !(await firedIn(bibdoc(entry("k1", { booktitle: "CHI" }) + entry("k2", { booktitle: "UIST" })))).has("BIB017"));

  // LOG010, LOG011
  const withLog = body => { const m = doc("Text here."); m.set("main.log", enc.encode("This is pdfTeX, Version 3.141592653-2.6-1.40.29 (TeX Live 2026)\n" + body)); return m; };
  r = await findingsOf(withLog("LaTeX Warning: Float too large for page by 31.5pt on input line 88.\n"), "LOG010");
  check("LOG010 a float too large for the page", r.length === 1 && r[0].line === 88);
  r = await findingsOf(withLog("Package hyperref Warning: Token not allowed in a PDF string (Unicode):\n(hyperref)                removing `\\cite' on input line 12.\n"), "LOG011");
  check("LOG011 a token hyperref dropped from a bookmark", r.length === 1 && r[0].line === 12 && r[0].message.includes("cite"));
  f = await firedIn(withLog("Output written on main.pdf (3 pages).\n"));
  check("LOG010/LOG011 a clean log reports neither", !f.has("LOG010") && !f.has("LOG011"));

  // POL010
  const STUDY = "Participants completed a questionnaire during the user study, and each participant was thanked afterwards.";
  check("POL010 a study that never states N", (await firedIn(doc(STUDY + " We report the results below in prose."))).has("POL010"));
  for (const s of [" We recruited 24 participants.", " The sample (N = 24) was balanced.",
                   " Twenty-four participants took part.", " Report how many people took part."])
    check("POL010 satisfied by:" + s, !(await firedIn(doc(STUDY + s))).has("POL010"));
}

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
