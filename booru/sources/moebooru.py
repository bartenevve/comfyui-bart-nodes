import json
import threading
import time
import urllib.parse

from .. import fetch
from .base import BooruSource, Post, parse_count, url_on_domain

_COUNT_TTL = 60.0
_count_cache = {}
_count_lock = threading.Lock()

_RATINGS = {"s": "safe", "q": "questionable", "e": "explicit"}


def parse_posts(text, origin, domain):
    """Posts of one `post.json` page, in the order the site returns them.

    Raises LookupError when the body is not the JSON list the API promises
    (an error page, a challenge page) so the user sees why instead of "no posts".
    """
    try:
        items = json.loads(text)
    except ValueError:
        raise LookupError("unexpected response from the booru (not JSON)") from None
    if not isinstance(items, list):
        raise LookupError("unexpected response from the booru (not a post list)")

    posts = []
    for item in items:
        if not isinstance(item, dict) or not str(item.get("id", "")).isdigit():
            continue
        post_id = str(item["id"])
        thumb = item.get("preview_url") or ""
        posts.append(
            Post(
                post_id=post_id,
                page_url=f"{origin}post/show/{post_id}",
                thumb_url=thumb if url_on_domain(thumb, domain) else "",
                tags=str(item.get("tags") or ""),
                rating=_RATINGS.get(item.get("rating"), str(item.get("rating") or "")),
            )
        )
    return posts


def parse_file_url(text, post_id, origin, domain):
    """Original file URL of `post_id` out of a `post.json?tags=id:<id>` body.

    The URL is read from third-party JSON and later fetched and served back
    through ComfyUI, so one off the site's own domain is refused.
    """
    for post in _raw_items(text):
        if str(post.get("id")) != str(post_id):
            continue
        file_url = post.get("file_url")
        if not file_url:
            continue  # deleted/hidden posts carry no file; joining "" would yield the site root
        url = urllib.parse.urljoin(origin, file_url)
        if url_on_domain(url, domain):
            return url
    return None


def _raw_items(text):
    try:
        items = json.loads(text)
    except ValueError:
        return []
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


class MoebooruSource(BooruSource):
    """Sites running the Moebooru engine (yande.re, konachan, ...).

    One engine, one JSON API: `post.json` lists a page, `post.xml?limit=1`
    carries the match count in its header. Subclasses only name the site.
    """

    origin = ""  # "https://yande.re/"
    domain = ""  # "yande.re"
    page_size = 100  # the API's `limit` ceiling is 1000; 100 keeps pages small
    max_positions = 1_000_000

    def _get_text(self, path, **query):
        url = f"{self.origin}{path}?{urllib.parse.urlencode(query)}"
        return fetch.get_text(url, referer=self.origin, domain=self.domain)

    def count(self, tags):
        key = (self.name, tags)
        now = time.monotonic()
        with _count_lock:
            cached = _count_cache.get(key)
            if cached and now - cached[0] < _COUNT_TTL:
                return cached[1]

        total = parse_count(self._get_text("post.xml", tags=tags, limit=1))
        if total is None:
            raise LookupError("unexpected response from the booru (no post count)")
        total = min(total, self.max_positions)

        with _count_lock:
            _count_cache[key] = (time.monotonic(), total)
        return total

    def page(self, tags, pid):
        page_number = pid // self.page_size + 1
        text = self._get_text("post.json", tags=tags, limit=self.page_size, page=page_number)
        return parse_posts(text, self.origin, self.domain)

    def resolve_file_url(self, post_id):
        text = self._get_text("post.json", tags=f"id:{post_id}", limit=1)
        url = parse_file_url(text, post_id, self.origin, self.domain)
        if not url:
            raise LookupError(f"could not find a file URL for post {post_id}")
        return url

    def download(self, url):
        if not url_on_domain(url, self.domain):
            raise LookupError(f"refusing to download from a non-{self.domain} host: {url}")
        return fetch.cached_download(url, referer=self.origin, domain=self.domain)


class YandeRe(MoebooruSource):
    name = "yandere"
    origin = "https://yande.re/"
    domain = "yande.re"


class KonachanCom(MoebooruSource):
    name = "konachan"
    origin = "https://konachan.com/"
    domain = "konachan.com"


class KonachanNet(MoebooruSource):
    """The safe-for-work mirror of Konachan.com (same posts, no explicit ratings)."""

    name = "konachan_net"
    origin = "https://konachan.net/"
    domain = "konachan.net"
