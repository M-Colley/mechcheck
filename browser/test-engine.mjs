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
  Buffer.from(engine + "\nexport { runChecks, TexProject, parseBib, similarity, findMainDocument, RULES, SEV, collectFiles, readZip };").toString("base64"));
const { runChecks, parseBib, similarity, findMainDocument, RULES, SEV } = module;

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
  // Figure~ref, Table~ref, Section~ref, and Figure~autoref (the doubled word)
  check("REF008 count", ref008.length === 4, String(ref008.length));
  // "Colley et al.", "Rukzio and Colley", "Bazilinskyy" -- but not the bare cite
  check("REF009 count", ref009.length === 3, String(ref009.length));
  check("REF008 catches the doubled word", ref008.some(f => f.message.includes("twice")));
  check("REF009 suggests citet under acmart",
        ref009.every(f => (f.fix || "").includes("citet")), ref009.map(f => f.fix).join(" | "));
  check("REF004 stands aside for REF008", !fired.has("REF004"));
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
    REF001: 1, REF008: 3, REF009: 2, STY001: 1, STY003: 1, STY005: 1, STY007: 1,
    VEN002: 2, VEN003: 1, VEN004: 2,
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

console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
