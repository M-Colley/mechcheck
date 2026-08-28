/**
 * Generate extension/engine.js from browser/mechcheck.html.
 *
 * The HTML page is the single source of truth for the checking logic, so the
 * extension cannot drift away from it: this script lifts sections 1-6 (the
 * model, the rules, the venue packs, the runner) and leaves section 7 (the
 * page's own interface) behind. The extension brings its own interface.
 *
 *   node browser/build-extension.mjs
 *
 * The generated file is committed, so nobody has to run this to install the
 * extension. Run it after editing mechcheck.html.
 */
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));
const repo = join(here, "..");

const html = readFileSync(join(here, "mechcheck.html"), "utf8");
const script = html.slice(html.indexOf("<script>") + 8, html.lastIndexOf("</script>"));
const marker = "/* ===================== 7. Interface";
const cut = script.indexOf(marker);
if (cut === -1) throw new Error("could not find the interface section marker in mechcheck.html");
const engine = script.slice(0, cut).trimEnd();

const header = `/* GENERATED FILE -- do not edit.
 *
 * Built from browser/mechcheck.html by browser/build-extension.mjs, so the
 * extension and the standalone page run byte-for-byte the same checks. Edit
 * mechcheck.html and re-run the build.
 *
 * Built: ${new Date().toISOString().slice(0, 10)}
 */

`;

const footer = `

/* The content script needs these; a content script shares one isolated world
   with the other scripts on its list, so plain globals are enough. */
globalThis.mechcheck = {
  runChecks, applyFixes, collectFiles, readZip, normalisePath, findMainDocument,
  RULES, RULES_BY_ID, SEV, SEV_NAME, VENUES, PROFILES, STAGES, Config,
};
`;

mkdirSync(join(repo, "extension"), { recursive: true });
const out = join(repo, "extension", "engine.js");
writeFileSync(out, header + engine + footer, "utf8");

const rules = (engine.match(/^rule\(\{ id:"/gm) || []).length;
console.log(`wrote extension/engine.js  (${(header + engine + footer).length.toLocaleString()} bytes, ${rules} rules)`);

/* The harness references engine.js and content.js by relative path, which some
   local-file viewers cannot resolve. Emit a self-contained copy too, so the
   panel can be exercised by opening a single file anywhere. */
const harnessPath = join(repo, "extension", "test-harness.html");
try {
  const harness = readFileSync(harnessPath, "utf8");
  const contentJs = readFileSync(join(repo, "extension", "content.js"), "utf8");
  // Replacer *functions*, not strings: the engine is full of template literals,
  // and `$&`-style sequences in a string replacement would be interpreted.
  const inlined = harness
    .replace('<script src="engine.js"></script>',
             () => "<script>\n" + header + engine + footer + "\n</script>")
    .replace('<script src="content.js"></script>',
             () => "<script>\n" + contentJs + "\n</script>");
  const out2 = join(repo, "extension", "test-harness.built.html");
  writeFileSync(out2, inlined, "utf8");
  console.log(`wrote extension/test-harness.built.html  (${inlined.length.toLocaleString()} bytes, self-contained)`);
} catch (err) {
  console.log("skipped the self-contained harness:", err.message);
}
