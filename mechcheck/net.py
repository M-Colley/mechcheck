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
#: Consecutive transport failures after which a host is left alone for the
#: rest of the run. Without it an outage cost about 20 s per reference.
MAX_HOST_FAILURES = 3

_last_call: dict = {}

#: Answers that say the resource does not exist, as opposed to "could not tell".
_ABSENT = (404, 410)


class Fetcher:
    def __init__(self, mailto: str | None = None, cache_dir: str | None = None,
                 offline: bool = False, ttl: int = CACHE_TTL_S) -> None:
        self.mailto = mailto or os.environ.get("MECHCHECK_MAILTO") or ""
        self.cache_dir = cache_dir or os.environ.get("MECHCHECK_CACHE") or DEFAULT_CACHE
        self.offline = offline
        self.ttl = ttl
        self.stats = {"hit": 0, "miss": 0, "error": 0, "skipped": 0}
        #: Full URLs the server answered 404/410 for: the only failures that
        #: may be reported as "does not exist".
        self.absent: set = set()
        self._host_failures: dict = {}

    # -- public ------------------------------------------------------------ #

    def get_json(self, url: str, params: dict | None = None, headers: dict | None = None):
        """Return parsed JSON, or ``None`` on any failure. Never raises.

        ``None`` alone does not say the resource is missing: :meth:`is_absent`
        does, and only when the server said so.
        """
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

    def is_absent(self, url: str, params: dict | None = None) -> bool:
        """True only if the server answered 404/410 for this request."""
        return _with_params(url, params) in self.absent

    def url_status(self, url: str):
        """What a bare URL answers: an HTTP status, ``"dns"``, or ``None``.

        ``None`` means "could not be determined" -- a timeout, a reset, a TLS
        failure, or offline. It is deliberately a third answer rather than a
        failure: a server that refuses a robot has not told us the link is
        broken, and only a definite answer may be reported as one.
        """
        key = "status:" + url
        cached = self._read_cache(key)
        if isinstance(cached, dict) and "status" in cached:
            self.stats["hit"] += 1
            return cached["status"]
        if self.offline:
            self.stats["skipped"] += 1
            return None
        status = self._probe(url)
        if status is not None:
            self._write_cache(key, {"status": status})
            self.stats["miss"] += 1
        else:
            self.stats["error"] += 1
        return status

    def _probe(self, url: str, attempts: int = 2):
        import http.client
        import socket

        try:
            host = urllib.parse.urlparse(url).netloc
        except ValueError:          # 'http://[::1/x' -- not a URL at all
            return None
        for attempt in range(attempts):
            self._throttle(host)
            # HEAD first; plenty of servers answer it with 405, so fall back.
            for method in ("HEAD", "GET"):
                req = urllib.request.Request(url, method=method, headers={
                    "User-Agent": self._user_agent(),
                    "Accept": "*/*",
                })
                try:
                    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                        return int(resp.status)
                except urllib.error.HTTPError as exc:
                    if exc.code in (405, 501) and method == "HEAD":
                        continue            # this server dislikes HEAD; try GET
                    if exc.code in (429, 500, 502, 503) and attempt < attempts - 1:
                        time.sleep(2.0)
                        break               # transient: start the attempt again
                    return int(exc.code)
                except urllib.error.URLError as exc:
                    if isinstance(exc.reason, socket.gaierror):
                        return "dns"        # the host itself does not exist
                    return None
                # InvalidURL (a URL wrapped across lines) and IncompleteRead
                # are http.client errors, not OSErrors.
                except (TimeoutError, OSError, ValueError, http.client.HTTPException):
                    return None
        return None

    # -- internals --------------------------------------------------------- #

    def _user_agent(self) -> str:
        from mechcheck import __version__

        contact = f" (mailto:{self.mailto})" if self.mailto else ""
        return f"mechcheck/{__version__}{contact}"

    def _fetch(self, url: str, headers: dict, attempts: int = 3):
        import http.client

        try:
            host = urllib.parse.urlparse(url).netloc
        except ValueError:
            return None
        for attempt in range(attempts):
            if self._host_failures.get(host, 0) >= MAX_HOST_FAILURES:
                return None             # this host is down for the run
            self._throttle(host)
            req = urllib.request.Request(url, headers={
                "User-Agent": self._user_agent(),
                "Accept": "application/json",
                **headers,
            })
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                    body = resp.read().decode("utf-8", errors="replace")
                self._host_failures[host] = 0
                return body
            except urllib.error.HTTPError as exc:
                self._host_failures[host] = 0       # the host answered
                if exc.code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                    retry_after = exc.headers.get("Retry-After") if exc.headers else None
                    delay = float(retry_after) if (retry_after or "").isdigit() else 2.0 * (attempt + 1)
                    time.sleep(min(delay, 10.0))
                    continue
                if exc.code in _ABSENT:
                    self.absent.add(url)
                return None
            except (urllib.error.URLError, TimeoutError, OSError, ValueError,
                    http.client.HTTPException):
                self._host_failures[host] = self._host_failures.get(host, 0) + 1
                if attempt < attempts - 1 and self._host_failures[host] < MAX_HOST_FAILURES:
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


def _crossref_doi_request(fetcher: Fetcher, doi: str):
    return CROSSREF_WORK + urllib.parse.quote(doi, safe=""), {"mailto": fetcher.mailto or None}


def _openalex_doi_request(fetcher: Fetcher, doi: str):
    return OPENALEX_DOI + urllib.parse.quote(doi, safe="/"), {"mailto": fetcher.mailto or None}


def crossref_by_doi(fetcher: Fetcher, doi: str):
    if not doi:
        return None
    data = fetcher.get_json(*_crossref_doi_request(fetcher, doi))
    if not isinstance(data, dict):
        return None
    return data.get("message")


def doi_absent(fetcher: Fetcher, doi: str) -> bool:
    """Both registries answered "no such DOI" -- not a timeout, not a 5xx."""
    return (fetcher.is_absent(*_crossref_doi_request(fetcher, doi))
            and fetcher.is_absent(*_openalex_doi_request(fetcher, doi)))


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
    data = fetcher.get_json(*_openalex_doi_request(fetcher, doi))
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
