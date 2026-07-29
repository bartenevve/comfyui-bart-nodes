import hashlib
import os
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

TIMEOUT = 30
MAX_BYTES = 64 * 1024 * 1024

# Booru image hosts hand out 302s to the post page for requests without a
# Referer, and the search pages behind Cloudflare-ish setups dislike a bare
# urllib UA - both headers are what a browser would send anyway.
_MIN_INTERVAL = 0.6
_last_request = {}
_throttle_lock = threading.Lock()


class FetchError(RuntimeError):
    pass


def _throttle(host):
    """Serialize requests per host with a minimum gap between them.

    Held across the sleep on purpose: a batch queue firing several executions
    at once would otherwise all read the same timestamp, sleep the same amount
    and hit the site simultaneously anyway.
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


def get(url, referer=None, cookie=None):
    """GET `url`, returning raw bytes. Raises FetchError on any failure."""
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
    if cookie:
        headers["Cookie"] = cookie

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
    return data


def get_text(url, referer=None, cookie=None):
    return get(url, referer=referer, cookie=cookie).decode("utf-8", errors="replace")


def cache_dir():
    """Where downloaded originals live. ComfyUI's temp dir when available."""
    try:
        import folder_paths

        base = folder_paths.get_temp_directory()
    except Exception:
        base = tempfile.gettempdir()
    path = os.path.join(base, "random_booru")
    os.makedirs(path, exist_ok=True)
    return path


def cached_download(url, referer=None, cookie=None):
    """Download `url` once and return the path of the on-disk copy.

    A preview fetch and the execution that follows it ask for the same file
    seconds apart; caching keeps that to a single request to the booru.
    """
    extension = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
    if len(extension) > 6 or not extension.isascii():
        extension = ""
    name = hashlib.sha256(url.encode("utf-8")).hexdigest() + extension
    path = os.path.join(cache_dir(), name)

    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return path

    data = get(url, referer=referer, cookie=cookie)
    # write-then-rename so a download interrupted halfway can't leave a
    # truncated file that later runs would happily treat as cached
    temporary = path + f".{os.getpid()}.{threading.get_ident()}.part"
    with open(temporary, "wb") as handle:
        handle.write(data)
    os.replace(temporary, path)
    return path
