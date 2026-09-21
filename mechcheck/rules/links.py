"""Links in the body, and whether they still lead anywhere.

The bibliography has its own verification (``BIO*``); this is about the URLs
in the running text — the artifact, the supplementary material, the
questionnaire. Those are the links a reviewer actually follows, and a 404 at
submission costs the paper the evidence it was pointing at.

The rule reports only a **definite** answer. A server that times out, refuses
a robot with 403, or sits behind a paywall has not told us the link is
broken, and saying so anyway would be exactly the kind of wrong finding this
checker spends its credibility on. Only 404, 410 and a hostname that does not
resolve are reported.
"""

from __future__ import annotations

import re

from mechcheck.model import Category, Severity, rule

#: Wrapped, or bare in the text. The bare form deliberately stops at the
#: punctuation that usually ends a sentence rather than the URL.
_BARE_URL = re.compile(r"(?<![\w/@.-])https?://[^\s{}<>\"'\\]+", re.IGNORECASE)

#: Hosts whose 404 means nothing: they refuse robots wholesale, or the link
#: is behind a login that every reviewer has and this checker does not.
_UNCHECKABLE = (
    "doi.org", "dx.doi.org", "linkedin.com", "twitter.com", "x.com", "facebook.com",
    "instagram.com", "researchgate.net", "sciencedirect.com", "springer.com",
    "ieeexplore.ieee.org", "onlinelibrary.wiley.com", "tandfonline.com",
    "jstor.org", "sci-hub", "localhost", "127.0.0.1", "example.com", "example.org",
)


def _urls(ctx) -> dict:
    """Every distinct URL in the document, mapped to where it first appears."""
    cached = ctx.cache.get("body_urls")
    if cached is not None:
        return cached
    found: dict = {}
    text = ctx.project.text
    for name, args in (("url", 1), ("nolinkurl", 1), ("href", 1), ("doi", 1)):
        for cmd in ctx.project.commands(name, args):
            target = cmd.arg(0).strip()
            if target.startswith("http"):
                found.setdefault(target, cmd.start)
    for m in _BARE_URL.finditer(text):
        found.setdefault(m.group(0).rstrip(".,;:)]}"), m.start())
    ctx.cache["body_urls"] = found
    return found


def _checkable(url: str) -> bool:
    host = re.sub(r"^https?://", "", url, flags=re.IGNORECASE).split("/")[0].lower()
    return not any(bad in host for bad in _UNCHECKABLE)


@rule("URL001", "Link in the text does not resolve", Category.POLICY, Severity.WARN, online=True,
      rationale="A reviewer following the artifact link is the best thing that can happen to a paper, and a 404 is the worst. Unlike a broken citation nobody notices until later, this one is discovered by exactly the person deciding on the work.",
      fix="Fix the address, or point at an archived copy with a persistent identifier (Zenodo, OSF, a DOI) that cannot move.")
def dead_link(ctx):
    from mechcheck import net

    fetcher = ctx.cache.get("fetcher")
    if fetcher is None:
        mailto = ctx.opt("URL001", "mailto", None) or ctx.config.data.get("mailto")
        fetcher = net.Fetcher(mailto=mailto, offline=ctx.offline)
        ctx.cache["fetcher"] = fetcher

    limit = int(ctx.opt("URL001", "max_links", 40) or 40)
    for url, offset in sorted(_urls(ctx).items(), key=lambda kv: kv[1])[:limit]:
        if not _checkable(url):
            continue
        status = fetcher.url_status(url)
        # Only a definite answer is reported: None means the check could not
        # be made, and 403 means a robot was refused, not that the page is gone.
        if status == "dns":
            detail = "the host does not exist"
        elif status in (404, 410):
            detail = f"the server answered {status}"
        else:
            continue
        f, line, col = ctx.project.locate(offset)
        yield ctx.finding("URL001", f"{url[:70]} does not resolve: {detail}",
                          file=f, line=line, col=col, context=ctx.project.excerpt(offset),
                          data={"url": url, "status": status})
