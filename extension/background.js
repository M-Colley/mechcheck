/* Service worker.
 *
 * It exists for one reason: in Manifest V3 a content script may not make
 * cross-origin requests, but a service worker with host_permissions may. So
 * every Crossref / OpenAlex / DBLP lookup is relayed through here.
 *
 * It also owns the response cache. Bibliographic metadata is effectively
 * static, so a cached answer is as good as a fresh one and costs the APIs
 * nothing -- which matters when twenty students check the same shared .bib.
 */

const MEMORY = new Map();
const CACHE_PREFIX = "cache:";
const CACHE_TTL_MS = 30 * 24 * 60 * 60 * 1000;   // metadata does not change
const MIN_INTERVAL_MS = 120;                      // be a good citizen
const ALLOWED = [/^https:\/\/api\.crossref\.org\//, /^https:\/\/api\.openalex\.org\//,
                 /^https:\/\/dblp\.org\//];

let lastCall = 0;

async function throttle() {
  const wait = MIN_INTERVAL_MS - (Date.now() - lastCall);
  if (wait > 0) await new Promise(r => setTimeout(r, wait));
  lastCall = Date.now();
}

async function cacheRead(key) {
  if (MEMORY.has(key)) return MEMORY.get(key);
  try {
    const stored = await chrome.storage.local.get(CACHE_PREFIX + key);
    const entry = stored[CACHE_PREFIX + key];
    if (entry && Date.now() - entry.at < CACHE_TTL_MS) {
      MEMORY.set(key, entry.value);
      return entry.value;
    }
  } catch (err) { /* storage full or unavailable: just fetch again */ }
  return undefined;
}

async function cacheWrite(key, value) {
  MEMORY.set(key, value);
  try { await chrome.storage.local.set({ [CACHE_PREFIX + key]: { at: Date.now(), value } }); }
  catch (err) { /* quota: the in-memory copy still serves this session */ }
}

async function fetchJson(url, key) {
  const cached = await cacheRead(key);
  if (cached !== undefined) return { ok: true, data: cached, cached: true };

  if (!ALLOWED.some(re => re.test(url))) return { ok: false, error: "blocked host" };

  for (let attempt = 0; attempt < 3; attempt++) {
    await throttle();
    try {
      const res = await fetch(url, { headers: { "Accept": "application/json" } });
      if (res.status === 404) { await cacheWrite(key, null); return { ok: true, data: null }; }
      if (res.status === 429 || res.status >= 500) {
        await new Promise(r => setTimeout(r, 1000 * (attempt + 1)));
        continue;
      }
      if (!res.ok) return { ok: false, error: "HTTP " + res.status };
      const data = await res.json();
      await cacheWrite(key, data);
      return { ok: true, data };
    } catch (err) {
      if (attempt === 2) return { ok: false, error: String(err && err.message || err) };
      await new Promise(r => setTimeout(r, 500 * (attempt + 1)));
    }
  }
  return { ok: false, error: "gave up after three attempts" };
}

chrome.runtime.onMessage.addListener((msg, sender, respond) => {
  if (!msg || msg.type !== "mechcheck:fetch") return false;
  fetchJson(msg.url, msg.key).then(respond);
  return true;   // keep the message channel open for the async reply
});

chrome.runtime.onInstalled.addListener(async ({ reason }) => {
  if (reason !== "install") return;
  // Sensible defaults so the first check is useful without visiting settings.
  const existing = await chrome.storage.sync.get("settings");
  if (!existing.settings) {
    await chrome.storage.sync.set({
      settings: { profile: "thesis", stage: "submission", venue: "", verify: false, autorun: false },
    });
  }
});
