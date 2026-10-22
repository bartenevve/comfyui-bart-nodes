import http.server
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

fetch = module("booru.fetch")

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class Handler(http.server.BaseHTTPRequestHandler):
    """Routes: /image, /html (200 page), /short (cut off), /missing, /busy, /hop (302 -> Location header), /same (302 -> /image)."""

    location = ""

    def log_message(self, *args):
        pass

    def reply(self, status, body, content_type="image/png", declared=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body) if declared is None else declared))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/image", "/image.png"):
            self.reply(200, PNG)
        elif path == "/html":
            self.reply(200, b"<html>the post page</html>", "text/html")
        elif path == "/short":
            self.reply(200, PNG, declared=len(PNG) + 500)  # promises more than it sends
            self.close_connection = True
        elif path == "/busy":
            self.reply(503, b"busy")
        elif path == "/missing":
            self.reply(404, b"gone")
        elif path == "/hop":
            self.send_response(302)
            self.send_header("Location", Handler.location)
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path == "/same":
            self.send_response(302)
            self.send_header("Location", "/image")
            self.send_header("Content-Length", "0")
            self.end_headers()
        elif path == "/headers":
            body = f"cookie={self.headers.get('Cookie')};referer={self.headers.get('Referer')}".encode()
            self.reply(200, body, "text/plain")
        else:
            self.reply(404, b"")


def serve():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class FetchTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.home = serve()
        cls.other = serve()
        cls.base = f"http://127.0.0.1:{cls.home.server_port}"
        # "localhost" is a different host name for the same machine: a stand-in for another site
        cls.elsewhere = f"http://localhost:{cls.other.server_port}"

    @classmethod
    def tearDownClass(cls):
        for server in (cls.home, cls.other):
            server.shutdown()
            server.server_close()

    def setUp(self):
        patcher = mock.patch.object(fetch, "_MIN_INTERVAL", 0)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        cache = mock.patch.object(fetch, "cache_dir", return_value=self.tmp.name)
        cache.start()
        self.addCleanup(cache.stop)


class TestGet(FetchTestCase):
    def test_a_normal_download(self):
        self.assertEqual(fetch.get(self.base + "/image"), PNG)

    def test_a_cut_off_transfer_is_an_error_not_a_smaller_file(self):
        with self.assertRaises(fetch.FetchError) as caught:
            fetch.get(self.base + "/short")
        self.assertTrue(caught.exception.transient)
        self.assertIn("incomplete", str(caught.exception))

    def test_http_errors_say_whether_they_are_worth_retrying(self):
        with self.assertRaises(fetch.FetchError) as busy:
            fetch.get(self.base + "/busy")
        self.assertTrue(busy.exception.transient)
        with self.assertRaises(fetch.FetchError) as missing:
            fetch.get(self.base + "/missing")
        self.assertFalse(missing.exception.transient)

    def test_an_unreachable_host_is_transient(self):
        with self.assertRaises(fetch.FetchError) as caught:
            fetch.get("http://127.0.0.1:9/")
        self.assertTrue(caught.exception.transient)

    def test_only_http_urls(self):
        for bad in ("file:///etc/passwd", "ftp://host/x", "gopher://x"):
            with self.assertRaises(fetch.FetchError):
                fetch.get(bad)

    def test_headers_reach_the_site(self):
        body = fetch.get_text(self.base + "/headers", referer="https://site/", cookie="a=b")
        self.assertEqual(body, "cookie=a=b;referer=https://site/")


class TestDomainPinning(FetchTestCase):
    def test_a_redirect_inside_the_domain_is_followed(self):
        self.assertEqual(fetch.get(self.base + "/same", domain="127.0.0.1"), PNG)

    def test_a_redirect_off_the_domain_is_refused_and_nothing_is_sent_there(self):
        Handler.location = self.elsewhere + "/headers"
        with self.assertRaises(fetch.FetchError) as caught:
            fetch.get(self.base + "/hop", domain="127.0.0.1", cookie="secret=1", referer="https://site/")
        self.assertIn("refusing a redirect", str(caught.exception))

    def test_without_a_domain_redirects_are_unrestricted(self):
        Handler.location = self.elsewhere + "/image"
        self.assertEqual(fetch.get(self.base + "/hop"), PNG)

    def test_the_first_url_must_be_on_the_domain_too(self):
        with self.assertRaises(fetch.FetchError):
            fetch.get(self.elsewhere + "/image", domain="127.0.0.1")

    def test_on_domain_rejects_lookalikes(self):
        self.assertTrue(fetch.on_domain("https://img3.gelbooru.com/a.jpg", "gelbooru.com"))
        self.assertTrue(fetch.on_domain("https://gelbooru.com/a.jpg", "gelbooru.com"))
        for bad in ("https://evilgelbooru.com/a", "https://gelbooru.com.evil.example/a", "https://gelbooru.com@evil.example/a",
                    "file:///x", "//gelbooru.com/a"):
            self.assertFalse(fetch.on_domain(bad, "gelbooru.com"), bad)


class TestCachedDownload(FetchTestCase):
    def test_an_image_is_cached_and_reused(self):
        first = fetch.cached_download(self.base + "/image.png")
        with open(first, "rb") as handle:
            self.assertEqual(handle.read(), PNG)
        with mock.patch.object(fetch, "get", side_effect=AssertionError("must come from the cache")):
            self.assertEqual(fetch.cached_download(self.base + "/image.png"), first)

    def test_an_html_page_for_an_image_is_refused_and_not_cached(self):
        with self.assertRaises(fetch.FetchError) as caught:
            fetch.cached_download(self.base + "/html")
        self.assertIn("did not return an image", str(caught.exception))
        self.assertEqual(os.listdir(self.tmp.name), [])

    def test_a_cut_off_image_is_not_cached(self):
        with self.assertRaises(fetch.FetchError):
            fetch.cached_download(self.base + "/short")
        self.assertEqual(os.listdir(self.tmp.name), [])

    def test_a_download_that_failed_leaves_the_next_attempt_a_clean_slate(self):
        with self.assertRaises(fetch.FetchError):
            fetch.cached_download(self.base + "/html")
        self.assertTrue(os.path.isfile(fetch.cached_download(self.base + "/image.png")))


class TestSignatures(unittest.TestCase):
    def test_known_image_types(self):
        samples = {
            "png": PNG,
            "jpeg": b"\xff\xd8\xff\xe0" + b"\x00" * 20,
            "gif89": b"GIF89a" + b"\x00" * 20,
            "gif87": b"GIF87a" + b"\x00" * 20,
            "webp": b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 20,
            "bmp": b"BM" + b"\x00" * 20,
        }
        for name, data in samples.items():
            self.assertTrue(fetch.looks_like_image(data), name)

    def test_other_things_are_not_images(self):
        for data in (b"", b"<html>", b"<!DOCTYPE html>", b"RIFF\x00\x00\x00\x00WAVEfmt ", b"\x00" * 32, b"{\"error\": 1}"):
            self.assertFalse(fetch.looks_like_image(data), data[:12])


class TestPruneCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def make(self, name, size, age):
        path = os.path.join(self.tmp.name, name)
        with open(path, "wb") as handle:
            handle.write(b"x" * size)
        stamp = 1_000_000 - age
        os.utime(path, (stamp, stamp))
        return path

    def test_the_least_recently_used_files_go_first(self):
        for name, age in (("old", 300), ("mid", 200), ("new", 100)):
            self.make(name, 100, age)
        fetch.prune_cache(self.tmp.name, limit=250)
        self.assertEqual(sorted(os.listdir(self.tmp.name)), ["mid", "new"])

    def test_the_file_just_written_is_never_removed(self):
        keep = self.make("keep", 500, 999)  # oldest, and bigger than the whole budget
        self.make("other", 100, 1)
        fetch.prune_cache(self.tmp.name, keep=keep, limit=50)
        self.assertEqual(os.listdir(self.tmp.name), ["keep"])

    def test_downloads_in_progress_are_left_alone(self):
        self.make("busy.png.1.2.part", 100, 5000)
        self.make("done", 100, 100)
        fetch.prune_cache(self.tmp.name, limit=10)
        self.assertEqual(os.listdir(self.tmp.name), ["busy.png.1.2.part"])

    def test_under_budget_nothing_is_removed(self):
        self.make("a", 10, 1)
        self.make("b", 10, 2)
        fetch.prune_cache(self.tmp.name, limit=1000)
        self.assertEqual(len(os.listdir(self.tmp.name)), 2)

    def test_a_missing_folder_is_not_an_error(self):
        fetch.prune_cache(os.path.join(self.tmp.name, "nope"))


if __name__ == "__main__":
    unittest.main()
