"""Network access for the bibliography checks.

Standard library only, on purpose: ``pip install mechcheck`` must work on a bare
runner with no wheels to build and no lockfile to maintain.

Three habits keep us a good citizen of other people's free APIs:

* a real ``User-Agent`` with a contact address (Crossref's "polite pool")
* an on-disk cache, so re-running CI on an unchanged bibliography costs nothing
* a minimum interval between requests to the same host, plus honouring 429s
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_CACHE = os.path.join(os.path.expanduser("~"), ".cache", "mechcheck", "http")
CACHE_TTL_S = 30 * 24 * 3600     # bibliographic metadata is essentially static
MIN_INTERVAL_S = 0.12
TIMEOUT_S = 20

_last_call: dict = {}


class Fetcher:
    def __init__(self, mailto: str | None = None, cache_dir: str | None = None,
                 offline: bool = False, ttl: int = CACHE_TTL_S) -> None:
        self.mailto = mailto or os.environ.get("MECHCHECK_MAILTO") or ""
        self.cache_dir = cache_dir or os.environ.get("MECHCHECK_CACHE") or DEFAULT_CACHE
        self.offline = offline
        self.ttl = ttl
        self.stats = {"hit": 0, "miss": 0, "error": 0, "skipped": 0}

    # -- public ------------------------------------------------------------ #

    def get_json(self, url: str, params: dict | None = None, headers: dict | None = None):
        """Return parsed JSON, or ``None`` on any failure. Never raises."""
        full = _with_params(url, params)
        cached = self._read_cache(full)
        if cached is not None:
            self.stats["hit"] += 1
            return cached
        if self.offline:
            self.stats["skipped"] += 1
            return None
        body = self._fetch(full, headers or {})
        if body is None:
            self.stats["error"] += 1
            return None
        try:
            data = json.loads(body)
        except ValueError:
            self.stats["error"] += 1
            return None
        self._write_cache(full, data)
        self.stats["miss"] += 1
        return data

    # -- internals --------------------------------------------------------- #

    def _user_agent(self) -> str:
        from mechcheck import __version__

        contact = f" (mailto:{self.mailto})" if self.mailto else ""
        return f"mechcheck/{__version__}{contact}"

    def _fetch(self, url: str, headers: dict, attempts: int = 3):
        host = urllib.parse.urlparse(url).netloc
        for attempt in range(attempts):
            self._throttle(host)
            req = urllib.request.Request(url, headers={
                "User-Agent": self._user_agent(),
                "Accept": "application/json",
                **headers,
            })
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                    retry_after = exc.headers.get("Retry-After") if exc.headers else None
                    delay = float(retry_after) if (retry_after or "").isdigit() else 2.0 * (attempt + 1)
                    time.sleep(min(delay, 10.0))
                    continue
                return None
            except (urllib.error.URLError, TimeoutError, OSError):
                if attempt < attempts - 1:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                return None
        return None

    @staticmethod
    def _throttle(host: str) -> None:
        last = _last_call.get(host)
        if last is not None:
            wait = MIN_INTERVAL_S - (time.time() - last)
            if wait > 0:
                time.sleep(wait)
        _last_call[host] = time.time()

    def _cache_path(self, url: str) -> str:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
        return os.path.join(self.cache_dir, digest[:2], digest + ".json")

    def _read_cache(self, url: str):
        path = self._cache_path(url)
        try:
            stat = os.stat(path)
        except OSError:
            return None
        if self.ttl and (time.time() - stat.st_mtime) > self.ttl:
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def _write_cache(self, url: str, data) -> None:
        path = self._cache_path(url)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            os.replace(tmp, path)
        except OSError:
            pass


def _with_params(url: str, params: dict | None) -> str:
    if not params:
        return url
    clean = {k: v for k, v in params.items() if v not in (None, "")}
    if not clean:
        return url
    sep = "&" if "?" in url else "?"
    return url + sep + urllib.parse.urlencode(clean, quote_via=urllib.parse.quote)


# --------------------------------------------------------------------------- #
# the three services we query
# --------------------------------------------------------------------------- #

CROSSREF_WORK = "https://api.crossref.org/works/"
CROSSREF_QUERY = "https://api.crossref.org/works"
OPENALEX_DOI = "https://api.openalex.org/works/doi:"
OPENALEX_QUERY = "https://api.openalex.org/works"
DBLP_QUERY = "https://dblp.org/search/publ/api"


def crossref_by_doi(fetcher: Fetcher, doi: str):
    if not doi:
        return None
    url = CROSSREF_WORK + urllib.parse.quote(doi, safe="")
    data = fetcher.get_json(url, {"mailto": fetcher.mailto or None})
    if not isinstance(data, dict):
        return None
    return data.get("message")


def crossref_search(fetcher: Fetcher, title: str, author: str = "", rows: int = 3):
    if not title:
        return []
    data = fetcher.get_json(CROSSREF_QUERY, {
        "query.bibliographic": title,
        "query.author": author or None,
        "rows": rows,
        "select": "DOI,title,author,issued,container-title,type,score,is-referenced-by-count",
        "mailto": fetcher.mailto or None,
    })
    if not isinstance(data, dict):
        return []
    return ((data.get("message") or {}).get("items")) or []


def openalex_by_doi(fetcher: Fetcher, doi: str):
    if not doi:
        return None
    url = OPENALEX_DOI + urllib.parse.quote(doi, safe="/")
    data = fetcher.get_json(url, {"mailto": fetcher.mailto or None})
    return data if isinstance(data, dict) else None


def openalex_search(fetcher: Fetcher, title: str, rows: int = 3):
    if not title:
        return []
    data = fetcher.get_json(OPENALEX_QUERY, {
        "filter": f"title.search:{title[:200]}",
        "per-page": rows,
        "mailto": fetcher.mailto or None,
    })
    if not isinstance(data, dict):
        return []
    return data.get("results") or []


def dblp_search(fetcher: Fetcher, title: str, rows: int = 3):
    if not title:
        return []
    data = fetcher.get_json(DBLP_QUERY, {"q": title[:200], "format": "json", "h": rows})
    if not isinstance(data, dict):
        return []
    hits = (((data.get("result") or {}).get("hits") or {}).get("hit")) or []
    return [h.get("info", {}) for h in hits if isinstance(h, dict)]
