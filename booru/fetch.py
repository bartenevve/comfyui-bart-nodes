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

# Downloaded originals are kept so a preview and the run that follows it fetch once, but nothing
# else ever deletes them (ComfyUI clears its temp folder only at startup): past this budget the
# least recently used files are removed.
CACHE_LIMIT_BYTES = 512 * 1024 * 1024

# Booru image hosts hand out 302s to the post page for requests without a
# Referer, and the search pages behind Cloudflare-ish setups dislike a bare
# urllib UA - both headers are what a browser would send anyway.
_MIN_INTERVAL = 0.6
_last_request = {}
_throttle_lock = threading.Lock()

_IMAGE_SIGNATURES = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"BM")


class FetchError(RuntimeError):
    """A request failed. `transient` marks failures worth retrying as they are (the network, a
    timeout, a cut-off transfer, HTTP 408/429/5xx) as opposed to ones that will repeat (a 404, a
    refused redirect)."""

    def __init__(self, message, transient=False):
        super().__init__(message)
        self.transient = transient


def on_domain(url, domain):
    """http(s) URL whose host is `domain` or one of its subdomains."""
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme in ("http", "https") and (host == domain or host.endswith("." + domain))


class _StayOnDomain(urllib.request.HTTPRedirectHandler):
    """Follows redirects only while they stay on the site's own domain.

    The file URL a source hands over has been checked against its domain, but
    urllib would follow a 302 from there to any host (re-sending the Cookie and
    Referer too): a redirect off the site is refused.
    """

    def __init__(self, domain):
        self.domain = domain

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not on_domain(urllib.parse.urljoin(req.full_url, newurl), self.domain):
            raise FetchError(f"refusing a redirect away from {self.domain}: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def looks_like_image(data):
    """True when `data` starts like a PNG, JPEG, GIF, WebP or BMP file."""
    head = data[:16]
    return head.startswith(_IMAGE_SIGNATURES) or (head[:4] == b"RIFF" and head[8:12] == b"WEBP")


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


def get(url, referer=None, cookie=None, domain=None):
    """GET `url`, returning raw bytes. Raises FetchError on any failure.

    With `domain`, the URL and every redirect it leads to must stay on that
    domain. A body shorter than the server's Content-Length is an error (the
    transfer was cut off), not a smaller file.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise FetchError(f"refusing non-http(s) URL: {url}")
    if domain and not on_domain(url, domain):
        raise FetchError(f"refusing a URL outside {domain}: {url}")

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
    opener = urllib.request.build_opener(_StayOnDomain(domain)) if domain else urllib.request.build_opener()
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            data = response.read(MAX_BYTES + 1)
            declared = response.headers.get("Content-Length", "")
    except urllib.error.HTTPError as exc:
        exc.close()  # an HTTPError still holds the connection's socket
        transient = exc.code in (408, 429) or exc.code >= 500
        raise FetchError(f"HTTP {exc.code} for {url}", transient=transient) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise FetchError(f"request failed for {url}: {exc}", transient=True) from exc

    if len(data) > MAX_BYTES:
        raise FetchError(f"response larger than {MAX_BYTES} bytes: {url}")
    if declared.isdigit() and len(data) != int(declared):
        raise FetchError(f"incomplete download from {url}: got {len(data)} of {declared} bytes", transient=True)
    return data


def get_text(url, referer=None, cookie=None, domain=None):
    return get(url, referer=referer, cookie=cookie, domain=domain).decode("utf-8", errors="replace")


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


def prune_cache(directory, keep=None, limit=CACHE_LIMIT_BYTES):
    """Delete the least recently used files until the folder fits `limit` bytes (never `keep`)."""
    entries = []
    total = 0
    try:
        names = os.listdir(directory)
    except OSError:
        return
    for name in names:
        path = os.path.join(directory, name)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        total += stat.st_size
        if path != keep and not name.endswith(".part"):  # a .part is a download in progress
            entries.append((stat.st_mtime, stat.st_size, path))
    for _mtime, size, path in sorted(entries):
        if total <= limit:
            break
        try:
            os.remove(path)
            total -= size
        except OSError:
            pass  # in use (Windows) or already gone: the next run tries again


def cached_download(url, referer=None, cookie=None, domain=None):
    """Download `url` once and return the path of the on-disk copy.

    A preview fetch and the execution that follows it ask for the same file
    seconds apart; caching keeps that to a single request to the booru. The
    body must look like an image: hosts that refuse a hotlink answer 200 with
    the post's HTML page, and caching that would break the post for good.
    """
    extension = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
    if len(extension) > 6 or not extension.isascii():
        extension = ""
    name = hashlib.sha256(url.encode("utf-8")).hexdigest() + extension
    directory = cache_dir()
    path = os.path.join(directory, name)

    if os.path.isfile(path) and os.path.getsize(path) > 0:
        try:
            os.utime(path)  # recently used: the last to be pruned
        except OSError:
            pass
        return path

    data = get(url, referer=referer, cookie=cookie, domain=domain)
    if not looks_like_image(data):
        raise FetchError(f"the host did not return an image for {url} (an error page, or hotlink protection?)")
    # write-then-rename so a download interrupted halfway can't leave a
    # truncated file that later runs would happily treat as cached
    temporary = path + f".{os.getpid()}.{threading.get_ident()}.part"
    with open(temporary, "wb") as handle:
        handle.write(data)
    os.replace(temporary, path)
    prune_cache(directory, keep=path)
    return path
