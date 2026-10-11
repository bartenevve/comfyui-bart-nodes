import json
import re
import threading
import time
import urllib.parse

from .. import fetch
from .base import BooruSource, Post, parse_count, url_on_domain

_COUNT_TTL = 60.0
_count_cache = {}
_count_lock = threading.Lock()

_REASON = re.compile(r'<response[^>]*\sreason="([^"]*)"')

PAGE_SIZE = 100
# Anonymous deep-pagination cap, measured on safebooru.org and xbooru.com:
# pid * limit = 200000 still answers (limit=100 pid=2000, limit=1000 pid=200),
# one step further returns "API limited due to abuse". The cap is on the
# offset, so it holds for any page size.
MAX_OFFSET = 200_000
MAX_POSITIONS = MAX_OFFSET + PAGE_SIZE


def response_error(text):
    """The site's own message from a `<response success="false" reason="...">` body, else None."""
    match = _REASON.search(text)
    return match.group(1) if match else None


def parse_posts(text, origin, domain):
    """Posts of one `dapi` JSON page, in the order the site returns them.

    An empty body is how the API says "no results". A `<response success=false>`
    body is the API refusing (rate / depth limit) and is raised with its reason,
    as is anything else that isn't the JSON list the API promises.
    """
    if not text.strip():
        return []
    try:
        items = json.loads(text)
    except ValueError:
        reason = response_error(text)
        raise LookupError(f"the booru refused the request: {reason}" if reason else "unexpected response from the booru (not JSON)") from None
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
                page_url=f"{origin}index.php?page=post&s=view&id={post_id}",
                thumb_url=thumb if url_on_domain(thumb, domain) else "",
                tags=" ".join(str(item.get("tags") or "").split()),
                rating=str(item.get("rating") or ""),
            )
        )
    return posts


def parse_file_url(text, post_id, origin, domain):
    """Original file URL of `post_id` out of a `dapi` JSON body (`&id=<id>`).

    Read from third-party JSON and later fetched and served back through
    ComfyUI, so a URL off the site's own domain is refused. When the post has
    no `file_url` field the path is rebuilt from `directory` + `image`.
    """
    try:
        items = json.loads(text)
    except ValueError:
        return None
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict) or str(item.get("id")) != str(post_id):
            continue
        file_url = item.get("file_url")
        if not file_url and item.get("directory") and item.get("image"):
            file_url = f"images/{item['directory']}/{item['image']}"
        if not file_url:
            continue  # joining "" would yield the site root
        url = urllib.parse.urljoin(origin, file_url)
        if url_on_domain(url, domain):
            return url
    return None


class DapiSource(BooruSource):
    """Sites running Gelbooru 0.2's `dapi` (Safebooru.org, Xbooru).

    Unlike gelbooru.com itself these answer the API anonymously: JSON for a
    page (`json=1`), and the XML form's `<posts count>` header for the total.
    Subclasses only name the site.
    """

    origin = ""  # "https://safebooru.org/"
    domain = ""  # "safebooru.org"
    page_size = PAGE_SIZE
    max_positions = MAX_POSITIONS

    def _get_text(self, **query):
        params = {"page": "dapi", "s": "post", "q": "index", **query}
        url = f"{self.origin}index.php?{urllib.parse.urlencode(params)}"
        return fetch.get_text(url, referer=self.origin)

    def count(self, tags):
        key = (self.name, tags)
        now = time.monotonic()
        with _count_lock:
            cached = _count_cache.get(key)
            if cached and now - cached[0] < _COUNT_TTL:
                return cached[1]

        text = self._get_text(tags=tags, limit=1)
        total = parse_count(text)
        if total is None:
            reason = response_error(text)
            raise LookupError(f"the booru refused the request: {reason}" if reason else "unexpected response from the booru (no post count)")
        total = min(total, self.max_positions)

        with _count_lock:
            _count_cache[key] = (time.monotonic(), total)
        return total

    def page(self, tags, pid):
        if pid > MAX_OFFSET:
            return []
        # our `pid` is a post offset (a multiple of the page size); the API's
        # own `pid` is the page number
        text = self._get_text(tags=tags, limit=self.page_size, pid=pid // self.page_size, json=1)
        return parse_posts(text, self.origin, self.domain)

    def resolve_file_url(self, post_id):
        text = self._get_text(id=post_id, json=1)
        url = parse_file_url(text, post_id, self.origin, self.domain)
        if not url:
            raise LookupError(f"could not find a file URL for post {post_id}")
        return url

    def download(self, url):
        if not url_on_domain(url, self.domain):
            raise LookupError(f"refusing to download from a non-{self.domain} host: {url}")
        return fetch.cached_download(url, referer=self.origin)


class Safebooru(DapiSource):
    name = "safebooru"
    origin = "https://safebooru.org/"
    domain = "safebooru.org"


class Xbooru(DapiSource):
    name = "xbooru"
    origin = "https://xbooru.com/"
    domain = "xbooru.com"
