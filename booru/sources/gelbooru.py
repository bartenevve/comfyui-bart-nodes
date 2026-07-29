import html as html_module
import re
import threading
import time
import urllib.parse

from .. import fetch
from .base import BooruSource, Post

BASE_URL = "https://gelbooru.com/index.php"
ORIGIN = "https://gelbooru.com/"

PAGE_SIZE = 42
# Anonymous deep-pagination cap: pid=19992 still returns a full page,
# pid=20034 returns nothing. 19992 is the last multiple of PAGE_SIZE below it.
MAX_PID = 19992
MAX_POSITIONS = MAX_PID + PAGE_SIZE

# The site's legacy explicit-content opt-in. Anonymous listings already return
# every rating; this is belt-and-braces so a "safe images only" default can
# never silently filter the search out from under the user.
COOKIE = "fringeBenefits=yup"

_COUNT_TTL = 60.0
_count_cache = {}
_count_lock = threading.Lock()

_THUMB_BLOCK = re.compile(r'<article class="thumbnail-preview">(.*?)</article>', re.S)
_POST_ID = re.compile(r'id="p(\d+)"')
_THUMB_SRC = re.compile(r'<img[^>]*?\ssrc="([^"]+)"', re.S)
_THUMB_TITLE = re.compile(r'<img[^>]*?\stitle="([^"]*)"', re.S)
_LAST_PAGE_PID = re.compile(r'pid=(\d+)"[^>]*alt="last page"')
_ORIGINAL_URL = re.compile(r'href="(https?://[^"]*?gelbooru\.com/+images/[^"]+)"')
_OG_IMAGE = re.compile(r'property="og:image"\s+content="([^"]+)"')
_MAIN_IMAGE = re.compile(r'<img[^>]*\sid="image"[^>]*\ssrc="([^"]+)"')

_METADATA_TOKEN = re.compile(r"^(score|rating|id|user|source|md5|width|height):")


def listing_url(tags, pid):
    query = urllib.parse.urlencode({"page": "post", "s": "list", "tags": tags, "pid": pid})
    return f"{BASE_URL}?{query}"


def post_url(post_id):
    query = urllib.parse.urlencode({"page": "post", "s": "view", "id": post_id})
    return f"{BASE_URL}?{query}"


def _split_title(title):
    """Gelbooru packs a thumbnail's tags plus `score:`/`rating:` into `title`."""
    tags = []
    rating = ""
    for token in html_module.unescape(title).split():
        if token.startswith("rating:"):
            rating = token.split(":", 1)[1]
        elif _METADATA_TOKEN.match(token):
            continue
        else:
            tags.append(token)
    return " ".join(tags), rating


def parse_listing(html):
    """Posts of one search-results page, in the order the site shows them."""
    posts = []
    for block in _THUMB_BLOCK.findall(html):
        id_match = _POST_ID.search(block)
        if not id_match:
            continue
        src_match = _THUMB_SRC.search(block)
        title_match = _THUMB_TITLE.search(block)
        tags, rating = _split_title(title_match.group(1) if title_match else "")
        posts.append(
            Post(
                post_id=id_match.group(1),
                page_url=post_url(id_match.group(1)),
                thumb_url=html_module.unescape(src_match.group(1)) if src_match else "",
                tags=tags,
                rating=rating,
            )
        )
    return posts


def parse_last_pid(html):
    """The `pid` of the paginator's "last page" link, if the paginator has one."""
    match = _LAST_PAGE_PID.search(html)
    return int(match.group(1)) if match else None


def parse_file_url(html):
    """Original file URL from a post page, falling back to the sample image."""
    for pattern in (_ORIGINAL_URL, _OG_IMAGE, _MAIN_IMAGE):
        match = pattern.search(html)
        if match:
            url = html_module.unescape(match.group(1))
            # og:image and friends are served with a doubled slash
            # (".../gelbooru.com//images/...") which some CDN edges 404 on
            return re.sub(r"(?<!:)//+", "/", url)
    return None


class Gelbooru(BooruSource):
    name = "gelbooru"
    page_size = PAGE_SIZE
    max_positions = MAX_POSITIONS

    def _get_html(self, url):
        return fetch.get_text(url, referer=ORIGIN, cookie=COOKIE)

    def count(self, tags):
        key = (self.name, tags)
        now = time.monotonic()
        with _count_lock:
            cached = _count_cache.get(key)
            if cached and now - cached[0] < _COUNT_TTL:
                return cached[1]

        total = self._count_uncached(tags)

        with _count_lock:
            _count_cache[key] = (time.monotonic(), total)
        return total

    def _count_uncached(self, tags):
        html = self._get_html(listing_url(tags, 0))
        first_page = parse_listing(html)
        if not first_page:
            return 0

        last_pid = parse_last_pid(html)
        if last_pid is None:
            # single page of results, no paginator - the page IS the count
            return len(first_page)

        if last_pid > MAX_PID:
            # unreachable for anonymous clients; report the cap instead of a
            # number we can never actually page to
            return MAX_POSITIONS

        last_page = parse_listing(self._get_html(listing_url(tags, last_pid)))
        if not last_page:
            # paginator promised a page that isn't there - fall back to the
            # upper bound rather than reporting zero
            return min(last_pid + PAGE_SIZE, MAX_POSITIONS)
        return min(last_pid + len(last_page), MAX_POSITIONS)

    def page(self, tags, pid):
        if pid > MAX_PID:
            return []
        return parse_listing(self._get_html(listing_url(tags, pid)))

    def resolve_file_url(self, post_id):
        url = parse_file_url(self._get_html(post_url(post_id)))
        if not url:
            raise LookupError(f"could not find a file URL on post page {post_id}")
        return url

    def download(self, url):
        # image hosts 302 to the post page without a same-site Referer
        return fetch.cached_download(url, referer=ORIGIN, cookie=COOKIE)
