"""Throttled text fetching for 52prompts.com.

Kept separate from booru/fetch.py on purpose: this side only ever wants text -
one page and one small .js file - so it needs no binary download, no on-disk
cache and no shared throttle with an image board's.
"""

import threading
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

TIMEOUT = 20
MAX_BYTES = 4 * 1024 * 1024

# Both hosts are static-ish (a WordPress page and a Cloudinary raw asset), so a
# gap this small is plenty polite - and the TTL cache below means a workflow
# queued fifty times still only fetches once.
_MIN_INTERVAL = 0.4
_last_request = {}
_throttle_lock = threading.Lock()

CACHE_TTL = 3600.0
_text_cache = {}
_cache_lock = threading.Lock()


class FetchError(RuntimeError):
    pass


def _throttle(host):
    """One request per host at a time, with a minimum gap between them.

    The lock is held across the sleep so a batch of queued executions cannot
    all read the same timestamp and then hit the site simultaneously anyway.
    """
    with _throttle_lock:
        now = time.monotonic()
        previous = _last_request.get(host)
        if previous is not None:
            wait = _MIN_INTERVAL - (now - previous)
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
        _last_request[host] = now


def get_text(url, referer=None):
    """GET `url` and decode it as text. Raises FetchError on any failure."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise FetchError(f"refusing non-http(s) URL: {url}")

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if referer:
        headers["Referer"] = referer

    _throttle(parsed.netloc)
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            data = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise FetchError(f"HTTP {exc.code} for {url}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise FetchError(f"request failed for {url}: {exc}") from exc

    if len(data) > MAX_BYTES:
        raise FetchError(f"response larger than {MAX_BYTES} bytes: {url}")
    return data.decode("utf-8", errors="replace")


def cached_text(url, referer=None, ttl=CACHE_TTL):
    """`get_text` memoized per URL.

    The word lists change a handful of times a year, so re-fetching them on
    every queued execution would be pure noise for the site and latency for the
    user. A failure is not cached - the next run gets to try again.
    """
    now = time.monotonic()
    with _cache_lock:
        cached = _text_cache.get(url)
        if cached is not None and now - cached[0] < ttl:
            return cached[1]

    text = get_text(url, referer=referer)

    with _cache_lock:
        _text_cache[url] = (time.monotonic(), text)
    return text


def clear_cache():
    with _cache_lock:
        _text_cache.clear()
