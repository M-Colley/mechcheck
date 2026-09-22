/* The Overleaf-side interface.
 *
 * How it gets your project: it asks Overleaf for the same zip the Download →
 * Source menu item produces, using the session you are already logged into.
 * That is deliberately the least clever option available -- no scraping of the
 * editor's DOM, which would only ever see the file you have open and would
 * break every time Overleaf ships a new editor.
 *
 * Everything renders inside a shadow root, so Overleaf's stylesheet and this
 * panel cannot reach into each other.
 */

(() => {
  "use strict";

  const M = globalThis.mechcheck;
  if (!M) { console.error("mechcheck: engine did not load"); return; }

  const PROJECT_ID = (location.pathname.match(/\/project\/([0-9a-fA-F]{16,32})/) || [])[1];

  let host = null, root = null, panel = null;
  let lastResult = null, running = false;
  let lastOutputAttempts = [];
  let lastAdopted = [], lastConfigPath = null;

  /* A paper being submitted to CHI, as everywhere else. A thesis picks the
     thesis profile, and the project's own mechcheck.yaml overrides both. */
  const DEFAULTS = { profile: "paper", stage: "submission", venue: "chi", verify: false, autorun: false };

  async function getSettings() {
    try {
      const stored = await chrome.storage.sync.get("settings");
      return { ...DEFAULTS, ...(stored.settings || {}) };
    } catch (err) { return { ...DEFAULTS }; }
  }

  /* ---------- getting the project ---------- */

  async function fetchProjectZip(projectId = PROJECT_ID) {
    const res = await fetch(`/project/${projectId}/download/zip`, {
      credentials: "same-origin",
      headers: { "Accept": "application/zip" },
    });
    if (!res.ok) throw new Error(`Overleaf refused the download (HTTP ${res.status}). `
      + "Reload the page and make sure you are still signed in.");
    const buffer = await res.arrayBuffer();
    if (buffer.byteLength < 30) throw new Error("Overleaf returned an empty project.");
    return M.readZip(buffer);
  }

  /* The compiled log and PDF unlock the compile, page-count and PDF-metadata
     checks -- including ANON006, which reads the author name out of the PDF
     and is the classic way a carefully anonymised paper de-anonymises itself.

     Guessing the URL does not work: Overleaf serves output from
     /project/<id>/build/<buildId>/output/<file>, with a clsiserverid query
     parameter that routes to the machine holding that build. Neither is
     knowable from the outside.

     But the editor has already downloaded both files to show you the PDF, so
     the exact URLs -- build id, query string and all -- are sitting in this
     page's resource timeline. Reusing them costs nothing, triggers no compile,
     and stays correct when Overleaf changes the scheme again. */
  const OUTPUT_PATTERNS = [
    /\/(?:download\/)?project\/[0-9a-fA-F]+\/build\/[0-9a-fA-F-]+\/output\/([\w.-]+)/,
    /\/project\/[0-9a-fA-F]+\/output\/([\w.-]+)/,
  ];

  function discoverOutputUrls() {
    const found = new Map();
    try {
      for (const entry of performance.getEntriesByType("resource")) {
        for (const pattern of OUTPUT_PATTERNS) {
          const m = pattern.exec(entry.name);
          if (m) { found.set(m[1], entry.name); break; }   // later entries win
        }
      }
    } catch (err) { /* resource timing unavailable */ }
    return found;
  }

  async function fetchOutputs(files) {
    const discovered = discoverOutputUrls();
    const attempts = [];

    // Whatever the editor actually fetched, in the form it fetched it.
    for (const [name, url] of discovered) {
      if (/\.(log|pdf)$/i.test(name)) attempts.push([name, url]);
    }
    // The editor fetches the log too, but if only the PDF is in the timeline,
    // the log sits beside it under the same build.
    const pdfUrl = discovered.get("output.pdf");
    if (pdfUrl && !discovered.has("output.log"))
      attempts.push(["output.log", pdfUrl.replace(/output\.pdf/, "output.log")]);
    // Last resort: the path older Overleaf versions served.
    attempts.push(["output.log", `/project/${PROJECT_ID}/output/output.log`]);
    attempts.push(["output.pdf", `/project/${PROJECT_ID}/output/output.pdf`]);

    const tried = [];
    for (const [name, url] of attempts) {
      if (files.has(name)) continue;               // already have this one
      try {
        const res = await fetch(url, { credentials: "same-origin" });
        tried.push(`${url.split("?")[0]} -> ${res.status}`);
        if (!res.ok) continue;
        const buf = new Uint8Array(await res.arrayBuffer());
        if (buf.byteLength > 100) files.set(name, buf);
      } catch (err) {
        tried.push(`${url.split("?")[0]} -> ${err.message}`);
      }
    }
    lastOutputAttempts = tried;
    return files;
  }

  /* ---------- running ---------- */

  const relayFetch = async (url, key) => {
    try {
      const reply = await chrome.runtime.sendMessage({ type: "mechcheck:fetch", url, key });
      return reply && reply.ok ? reply.data : null;
    } catch (err) {
      return null;   // extension reloaded mid-run, or the worker was evicted
    }
  };

  /* A project that carries a mechcheck.yaml has already decided its profile,
     stage and venue. Adopt them rather than making the student match three
     controls to a file they may not know is there; the rest of the file
     (disabled rules, ignore lists, the project's own vocabulary) the engine
     reads for itself. */
  function adoptProjectConfig(files, settings) {
    lastAdopted = [];
    const project = M.readProjectConfig(files);
    lastConfigPath = project ? project.path : null;
    if (!project || !root) return;
    for (const key of ["profile", "stage", "venue"]) {
      const value = project.data[key];
      if (value === undefined || value === null) continue;
      const node = root.querySelector("." + key);
      const wanted = String(value);
      if (!node || ![...node.options].some(o => o.value === wanted) || settings[key] === wanted) continue;
      node.value = wanted;
      settings[key] = wanted;
      lastAdopted.push(`${key} = ${wanted}`);
    }
  }

  async function run() {
    if (running) return;
    running = true;
    const settings = await getSettings();
    setStatus("Asking Overleaf for the project…");
    try {
      const files = await fetchProjectZip();
      setStatus("Reading the compiled output…");
      await fetchOutputs(files);
      adoptProjectConfig(files, settings);
      setStatus(`Checking ${files.size} file${files.size === 1 ? "" : "s"}…`);

      const result = await M.runChecks(files, {
        ...settings,
        fetchJson: settings.verify ? relayFetch : undefined,
        onProgress: (frac, id) => setProgress(frac),
      });
      lastResult = result;
      render(result, settings);
    } catch (err) {
      renderError(err);
    } finally {
      running = false;
      setProgress(0);
    }
  }

  /* ---------- the panel ---------- */

  const CSS = `
:host { all: initial; }
* { box-sizing: border-box; }
.wrap {
  /* Clear of the bottom-right corner: other Overleaf extensions put their own
     button there, and two overlapping circles is nobody's idea of a good time. */
  position: fixed; right: 16px; bottom: 96px; z-index: 2147483000;
  font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
  color-scheme: light dark;
}
.launcher {
  display: flex; align-items: center; gap: 8px;
  background: #3a4ea8; color: #fff; border: none; border-radius: 999px;
  padding: 10px 16px; font-size: 13px; font-weight: 600; cursor: pointer;
  box-shadow: 0 2px 6px rgba(0,0,0,.2), 0 10px 30px -12px rgba(0,0,0,.5);
}
.launcher:hover { background: #33469a; }
.launcher .badge {
  background: rgba(255,255,255,.22); border-radius: 999px; padding: 1px 7px;
  font-variant-numeric: tabular-nums; font-size: 12px;
}
.launcher .badge.err { background: #b23026; }
.panel {
  width: min(440px, calc(100vw - 32px)); max-height: min(680px, calc(100vh - 90px));
  background: #fff; color: #171a21; border: 1px solid #d8dde6; border-radius: 10px;
  box-shadow: 0 4px 12px rgba(0,0,0,.12), 0 24px 60px -20px rgba(0,0,0,.4);
  display: flex; flex-direction: column; overflow: hidden; font-size: 13px;
}
@media (prefers-color-scheme: dark) {
  .panel { background: #151922; color: #e5e8ef; border-color: #2a303c; }
  .head, .foot { background: #1c212c !important; border-color: #2a303c !important; }
  .finding { border-color: #21262f !important; }
  .ctx { background: #0e1116 !important; color: #a3abbd !important; }
  select, .btn { background: #1c212c !important; color: #e5e8ef !important; border-color: #2a303c !important; }
  .rule { background: #1c212c !important; }
}
.head {
  display: flex; align-items: center; gap: 8px; padding: 10px 12px;
  border-bottom: 1px solid #d8dde6; background: #f7f8fa;
}
.head .title { font-weight: 600; flex: 1; }
.head .close { background: none; border: none; font-size: 18px; cursor: pointer; color: inherit; opacity: .6; padding: 0 4px; }
.head .close:hover { opacity: 1; }
.controls { display: flex; flex-wrap: wrap; gap: 6px; padding: 8px 12px; border-bottom: 1px solid #d8dde6; }
select, .btn {
  font: inherit; font-size: 12px; padding: 4px 8px; border: 1px solid #d8dde6;
  border-radius: 5px; background: #fff; color: inherit; cursor: pointer;
}
.btn.primary { background: #3a4ea8; color: #fff; border-color: #3a4ea8; font-weight: 600; }
.btn:disabled { opacity: .5; cursor: not-allowed; }
label.toggle { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; cursor: pointer; }
.summary { display: flex; gap: 6px; padding: 8px 12px; border-bottom: 1px solid #d8dde6; flex-wrap: wrap; }
.pill {
  font-size: 12px; padding: 3px 9px; border-radius: 999px; border: 1px solid #d8dde6;
  background: #fff; cursor: pointer; font-variant-numeric: tabular-nums; color: inherit;
}
.pill[aria-pressed="false"] { opacity: .45; }
.pill.err { border-color: #b23026; color: #b23026; }
.pill.warn { border-color: #9a6207; color: #9a6207; }
.stats { font-size: 11px; opacity: .65; padding: 0 12px 8px; }
.body { overflow-y: auto; flex: 1; }
.finding { padding: 8px 12px; border-bottom: 1px solid #eef1f6; display: flex; gap: 8px; }
.stripe { width: 3px; border-radius: 2px; flex: none; background: #9aa2b4; }
.finding.error .stripe { background: #b23026; }
.finding.warn .stripe { background: #9a6207; }
.finding .main { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 3px; }
.finding .top { display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap; }
.rule { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 11px;
        background: #eef1f6; border-radius: 3px; padding: 1px 5px; }
.loc { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 11px; opacity: .6; }
.msg { line-height: 1.45; }
.ctx { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 11px;
       background: #f7f8fa; border-radius: 4px; padding: 4px 6px; overflow-x: auto; white-space: pre; }
.fix { font-size: 12px; opacity: .8; }
.empty { padding: 28px 16px; text-align: center; opacity: .75; line-height: 1.6; }
.empty b { display: block; font-size: 15px; margin-bottom: 4px; opacity: 1; }
.note { padding: 8px 12px; font-size: 12px; background: #fff8e6; border-bottom: 1px solid #f0e3bd; color: #6b4d09; }
.note.bad { background: #fdecea; border-color: #f5c6c2; color: #8c231b; }
.foot { padding: 6px 12px; font-size: 11px; opacity: .6; border-top: 1px solid #d8dde6; background: #f7f8fa;
        display: flex; justify-content: space-between; gap: 8px; }
.progress { height: 2px; background: #eef1f6; }
.progress i { display: block; height: 100%; background: #3a4ea8; width: 0; transition: width .15s linear; }
.hidden { display: none !important; }
`;

  function ensureUI() {
    if (host) return;
    host = document.createElement("div");
    host.id = "mechcheck-host";
    root = host.attachShadow({ mode: "open" });
    root.innerHTML = `<style>${CSS}</style>
<div class="wrap">
  <div class="panel hidden" part="panel">
    <div class="head">
      <span class="title">mechcheck</span>
      <button class="close" title="Close">×</button>
    </div>
    <div class="controls">
      <select class="profile" title="Profile"></select>
      <select class="stage" title="Stage"></select>
      <select class="venue" title="Venue"></select>
      <label class="toggle"><input type="checkbox" class="verify"> verify refs</label>
      <button class="btn primary check">Check</button>
      <button class="btn fix" disabled>Fix</button>
    </div>
    <div class="progress"><i></i></div>
    <div class="note hidden"></div>
    <div class="summary hidden"></div>
    <div class="stats"></div>
    <div class="body"></div>
    <div class="foot"><span class="status">Ready</span><span class="copy btn">Copy report</span></div>
  </div>
  <button class="launcher">mechcheck<span class="badge hidden"></span></button>
</div>`;
    document.documentElement.appendChild(host);

    const q = sel => root.querySelector(sel);
    q(".launcher").addEventListener("click", () => {
      const p = q(".panel");
      p.classList.toggle("hidden");
      if (!p.classList.contains("hidden") && !lastResult && !running) run();
    });
    q(".close").addEventListener("click", () => q(".panel").classList.add("hidden"));
    q(".check").addEventListener("click", run);
    q(".fix").addEventListener("click", () => showFixes());
    q(".copy").addEventListener("click", copyReport);

    fillSelect(q(".profile"), Object.keys(M.PROFILES).map(k => [k, k]));
    fillSelect(q(".stage"), Object.keys(M.STAGES).map(k => [k, k]));
    fillSelect(q(".venue"), [["", "no venue"]].concat(
      Object.entries(M.VENUES).map(([k, v]) => [k, v.name])));

    for (const sel of [".profile", ".stage", ".venue", ".verify"]) {
      q(sel).addEventListener("change", async () => {
        const settings = {
          profile: q(".profile").value, stage: q(".stage").value,
          venue: q(".venue").value, verify: q(".verify").checked,
        };
        try { await chrome.storage.sync.set({ settings }); } catch (err) { /* ignore */ }
        if (lastResult) run();
      });
    }
    getSettings().then(s => {
      q(".profile").value = s.profile; q(".stage").value = s.stage;
      q(".venue").value = s.venue; q(".verify").checked = !!s.verify;
      if (s.autorun) run();
    });
  }

  function fillSelect(select, pairs) {
    select.innerHTML = "";
    for (const [value, label] of pairs) {
      const opt = document.createElement("option");
      opt.value = value; opt.textContent = label;
      select.appendChild(opt);
    }
  }

  const setStatus = text => { if (root) root.querySelector(".status").textContent = text; };
  const setProgress = frac => { if (root) root.querySelector(".progress i").style.width = Math.round(frac * 100) + "%"; };

  function setNote(text, bad) {
    if (!root) return;
    const note = root.querySelector(".note");
    note.classList.toggle("hidden", !text);
    note.classList.toggle("bad", !!bad);
    note.textContent = text || "";
  }

  const filters = { error: true, warn: true, info: true };

  function render(result, settings) {
    ensureUI();
    const q = sel => root.querySelector(sel);
    const counts = { error: 0, warn: 0, info: 0 };
    // Totals cover everything found, including what the per-rule cap held back.
    for (const f of result.findings.concat(result.truncated || []))
      counts[M.SEV_NAME[f.severity]]++;

    const badge = root.querySelector(".badge");
    const total = counts.error + counts.warn;
    badge.classList.toggle("hidden", total === 0);
    badge.classList.toggle("err", counts.error > 0);
    badge.textContent = String(total);

    const summary = q(".summary");
    summary.classList.remove("hidden");
    summary.innerHTML = "";
    for (const key of ["error", "warn", "info"]) {
      const b = document.createElement("button");
      b.className = "pill" + (key === "error" ? " err" : key === "warn" ? " warn" : "");
      b.setAttribute("aria-pressed", String(filters[key]));
      b.textContent = `${counts[key]} ${key}`;
      b.addEventListener("click", () => { filters[key] = !filters[key]; render(result, settings); });
      summary.appendChild(b);
    }

    const s = result.stats;
    q(".stats").textContent = `${s.main} · ${s.words.toLocaleString()} words · `
      + `${s.references} reference${s.references === 1 ? "" : "s"} · ${s.floats} float${s.floats === 1 ? "" : "s"}`
      + (s.pages ? ` · ${s.pages} pages` : "")
      + (s.hasLog ? "" : " · no .log, compile checks skipped")
      + (Object.keys(result.truncatedByRule || {}).length
         ? " · repeated findings listed once: "
           + Object.entries(result.truncatedByRule).sort()
               .map(([r, n]) => `${r} +${n}`).join(", ")
         : "");
    // When the output files could not be reached, say what was tried rather
    // than leaving a bare "skipped" that nobody can act on.
    q(".stats").title = s.hasLog ? "" :
      ("Tried:\n" + (lastOutputAttempts.join("\n") || "nothing — the editor had not "
       + "fetched the output yet in this page load. Recompile, then check again."));

    const config = s.configPath
      ? `Using this project's ${s.configPath}`
        + (lastAdopted.length ? `, which set ${lastAdopted.join(" · ")}. ` : ". ")
      : "";
    if (s.mainGuessed)
      setNote(config + `Guessed ${s.main} as the main file — no file had both \\documentclass and \\begin{document}.`, true);
    else if (settings.verify && s.netBlocked)
      setNote(config + "Reference lookups could not reach the internet. Everything else ran.", true);
    else if (!settings.verify)
      setNote(config + "Reference verification is off. Turn on “verify refs” to check that your citations exist.");
    else setNote(config);

    const body = q(".body");
    body.innerHTML = "";
    const shown = result.findings.filter(f => filters[M.SEV_NAME[f.severity]]);
    if (!result.findings.length) {
      body.innerHTML = `<div class="empty"><b>Nothing mechanical left to fix.</b>The remaining work is the thinking.</div>`;
    } else if (!shown.length) {
      body.innerHTML = `<div class="empty">Nothing matches these filters.</div>`;
    }
    for (const f of shown) {
      const row = document.createElement("div");
      row.className = "finding " + M.SEV_NAME[f.severity];
      const stripe = document.createElement("div"); stripe.className = "stripe";
      const main = document.createElement("div"); main.className = "main";
      const top = document.createElement("div"); top.className = "top";
      const rule = document.createElement("span"); rule.className = "rule"; rule.textContent = f.rule;
      const loc = document.createElement("span"); loc.className = "loc";
      loc.textContent = f.file ? f.file + (f.line ? ":" + f.line : "") : "";
      top.append(rule, loc);
      const msg = document.createElement("div"); msg.className = "msg"; msg.textContent = f.message;
      main.append(top, msg);
      if (f.context) {
        const ctx = document.createElement("div"); ctx.className = "ctx"; ctx.textContent = f.context;
        main.appendChild(ctx);
      }
      if (f.fix) {
        const fix = document.createElement("div"); fix.className = "fix"; fix.textContent = "Fix: " + f.fix;
        main.appendChild(fix);
      }
      row.append(stripe, main);
      body.appendChild(row);
    }

    const fixable = result.findings.concat(result.truncated || []).filter(f => f.edit).length;
    const fixButton = root.querySelector(".fix");
    fixButton.disabled = !fixable;
    fixButton.textContent = fixable ? `Fix ${fixable}` : "Fix";

    setStatus(`${counts.error} error${counts.error === 1 ? "" : "s"}, ${counts.warn} warning${counts.warn === 1 ? "" : "s"}`
      + (result.suppressed.length ? ` · ${result.suppressed.length} silenced` : ""));
  }

  function renderError(err) {
    ensureUI();
    root.querySelector(".panel").classList.remove("hidden");
    root.querySelector(".body").innerHTML =
      `<div class="empty"><b>Could not check this project</b>${escapeHtml(err.message || String(err))}</div>`;
    setStatus("Failed");
    setNote("");
  }

  /* A content script cannot edit the Overleaf document -- it is a CRDT synced
     over a websocket, and writing into it behind the editor's back is a good
     way to corrupt somebody's paper. Handing over the corrected file is the
     honest option: copy, select all in Overleaf, paste. */
  function showFixes(result) {
    // Defaulting to the last run keeps the click handler trivial; taking a
    // result explicitly is what lets the harness exercise this path.
    const target = (result && result.findings) ? result : lastResult;
    if (!target) return;
    const fx = M.applyFixes(target);
    const body = root.querySelector(".body");
    body.innerHTML = "";
    if (!fx.files.size) {
      body.innerHTML = `<div class="empty">Nothing here can be fixed automatically.</div>`;
      return;
    }
    const intro = document.createElement("div");
    intro.className = "note";
    intro.textContent = `${fx.applied.length} fix(es) ready. Copy the corrected file, then in `
      + "Overleaf open it, select all, and paste. Only rules with exactly one right answer "
      + "are fixed; alt text and anything needing judgement are left alone.";
    body.appendChild(intro);

    for (const [path, text] of fx.files) {
      const n = fx.applied.filter(a => a.path === path).length;
      const row = document.createElement("div");
      row.className = "finding";
      const stripe = document.createElement("div"); stripe.className = "stripe";
      const main = document.createElement("div"); main.className = "main";
      const top = document.createElement("div"); top.className = "top";
      const name = document.createElement("span"); name.className = "rule"; name.textContent = path;
      const count = document.createElement("span"); count.className = "loc";
      count.textContent = `${n} change${n === 1 ? "" : "s"}`;
      top.append(name, count);
      const button = document.createElement("button");
      button.className = "btn primary";
      button.textContent = "Copy corrected file";
      button.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(text);
          button.textContent = "Copied — paste over the file in Overleaf";
        } catch (err) {
          button.textContent = "Could not copy (clipboard blocked)";
        }
      });
      const what = document.createElement("div");
      what.className = "fix";
      what.textContent = fx.applied.filter(a => a.path === path)
        .slice(0, 6).map(a => a.describe).join(" · ");
      main.append(top, what, button);
      row.append(stripe, main);
      body.appendChild(row);
    }
    setStatus(`${fx.applied.length} fix(es) ready to copy`);
  }

  const escapeHtml = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function reportMarkdown(result) {
    const counts = { error: 0, warn: 0, info: 0 };
    for (const f of result.findings) counts[M.SEV_NAME[f.severity]]++;
    const lines = [`# mechcheck — ${result.stats.main}`, "",
      `${counts.error} errors, ${counts.warn} warnings, ${counts.info} notes`, ""];
    for (const f of result.findings) {
      const icon = { error: "❌", warn: "⚠️", info: "ℹ️" }[M.SEV_NAME[f.severity]];
      lines.push(`- ${icon} \`${f.rule}\` ${f.file || ""}${f.line ? ":" + f.line : ""} — ${f.message}`);
    }
    return lines.join("\n");
  }

  async function copyReport() {
    if (!lastResult) return;
    try {
      await navigator.clipboard.writeText(reportMarkdown(lastResult));
      setStatus("Report copied");
    } catch (err) {
      setStatus("Could not copy — check clipboard permission");
    }
  }

  /* ---------- popup messages ---------- */
  chrome.runtime.onMessage.addListener((msg, sender, respond) => {
    if (!msg || msg.type !== "mechcheck:run") return false;
    ensureUI();
    root.querySelector(".panel").classList.remove("hidden");
    run().then(() => respond({ ok: true })).catch(e => respond({ ok: false, error: String(e) }));
    return true;
  });

  /* Only mount on an actual project page; the same script also loads on the
     project list, where there is nothing to check. */
  if (PROJECT_ID) ensureUI();

  /* A seam for the test harness, which drives the panel with a stubbed
     chrome API and a mocked fetch. Costs nothing in production and means the
     rendering path is not shipped untested. */
  globalThis.__mechcheckContent = { run, render, renderError, ensureUI, reportMarkdown,
                                    fetchProjectZip, fetchOutputs, showFixes, PROJECT_ID };
})();
