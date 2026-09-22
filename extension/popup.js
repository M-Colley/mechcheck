/* The toolbar popup: settings, and a way to start a check without hunting for
   the button on the page. The venue list is read from the shared engine rather
   than duplicated here, so adding a venue stays a one-file change. */

/* A paper being submitted to CHI, matching the command line and the page. */
const DEFAULTS = { profile: "paper", stage: "submission", venue: "chi", verify: false, autorun: false };
const $ = id => document.getElementById(id);
const FIELDS = ["profile", "stage", "venue", "verify", "autorun"];

function populateVenues() {
  const venues = (globalThis.mechcheck && globalThis.mechcheck.VENUES) || {};
  const select = $("venue");
  for (const [key, pack] of Object.entries(venues)) {
    const option = document.createElement("option");
    option.value = key;
    option.textContent = pack.name || key;
    select.appendChild(option);
  }
}

async function load() {
  let settings = { ...DEFAULTS };
  try {
    const stored = await chrome.storage.sync.get("settings");
    settings = { ...DEFAULTS, ...(stored.settings || {}) };
  } catch (err) { /* first run, or sync unavailable */ }
  for (const id of FIELDS) {
    const node = $(id);
    if (node.type === "checkbox") node.checked = !!settings[id];
    else node.value = settings[id];
  }
}

async function save() {
  const settings = {};
  for (const id of FIELDS) {
    const node = $(id);
    settings[id] = node.type === "checkbox" ? node.checked : node.value;
  }
  try { await chrome.storage.sync.set({ settings }); } catch (err) { /* ignore */ }
}

async function activeProjectTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.url) return null;
  return /^https:\/\/[^/]*overleaf\.com\/project\/[0-9a-fA-F]{16,32}/.test(tab.url) ? tab : null;
}

async function updateHint() {
  const tab = await activeProjectTab();
  const hint = $("hint");
  const button = $("check");
  if (tab) {
    button.disabled = false;
    hint.innerHTML = "Findings appear in a panel at the bottom right of the project. "
      + "Silence one with <b>% mechcheck: off RULE -- reason</b> in the source.";
  } else {
    button.disabled = true;
    hint.textContent = "Open an Overleaf project in this tab first — the checks read the project "
      + "you have open, using the session you are already signed into.";
  }
}

async function check() {
  const tab = await activeProjectTab();
  if (!tab) return;
  await save();
  $("check").disabled = true;
  $("check").textContent = "Checking…";
  try {
    await chrome.tabs.sendMessage(tab.id, { type: "mechcheck:run" });
    window.close();
  } catch (err) {
    $("check").disabled = false;
    $("check").textContent = "Check this project";
    $("hint").textContent = "The page has not loaded the extension yet. Reload the Overleaf tab and try again.";
  }
}

for (const id of FIELDS) $(id).addEventListener("change", save);
$("check").addEventListener("click", check);

populateVenues();
load().then(updateHint);
