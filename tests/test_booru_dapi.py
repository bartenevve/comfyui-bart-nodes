import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

dapi = module("booru.sources.dapi")
sources = module("booru.sources")

ORIGIN = "https://safebooru.org/"
DOMAIN = "safebooru.org"
FILE = "https://safebooru.org/images/595/abc123.png"

REFUSED = '<?xml version="1.0" encoding="UTF-8"?>\n  <response success="false" reason="Search error: API limited due to abuse."/>'


def post(post_id, **overrides):
    item = {
        "id": str(post_id),
        "tags": " cat  blue_eyes ",
        "rating": "general",
        "preview_url": "https://safebooru.org/thumbnails/595/thumbnail_abc123.jpg",
        "file_url": FILE,
        "directory": "595",
        "image": "abc123.png",
    }
    item.update(overrides)
    return item


def listing(*posts):
    return json.dumps(list(posts))


class TestParsePosts(unittest.TestCase):
    def test_posts_in_order_with_metadata(self):
        posts = dapi.parse_posts(listing(post(5), post(4, rating="explicit")), ORIGIN, DOMAIN)
        self.assertEqual([p.post_id for p in posts], ["5", "4"])
        self.assertEqual(posts[0].tags, "cat blue_eyes")  # padding collapsed
        self.assertEqual(posts[1].rating, "explicit")
        self.assertEqual(posts[0].page_url, "https://safebooru.org/index.php?page=post&s=view&id=5")

    def test_empty_body_means_no_results(self):
        for body in ("", "  \n", "[]"):
            self.assertEqual(dapi.parse_posts(body, ORIGIN, DOMAIN), [])

    def test_refusal_is_raised_with_the_sites_reason(self):
        with self.assertRaises(LookupError) as caught:
            dapi.parse_posts(REFUSED, ORIGIN, DOMAIN)
        self.assertIn("API limited due to abuse", str(caught.exception))

    def test_other_non_json_bodies_are_errors(self):
        for body in ("<html>Just a moment...</html>", '{"success": false}'):
            with self.subTest(body=body):
                with self.assertRaises(LookupError):
                    dapi.parse_posts(body, ORIGIN, DOMAIN)

    def test_skips_entries_without_a_numeric_id(self):
        posts = dapi.parse_posts(json.dumps([post(1), {"id": "x"}, "junk"]), ORIGIN, DOMAIN)
        self.assertEqual([p.post_id for p in posts], ["1"])

    def test_foreign_thumbnail_host_is_dropped(self):
        posts = dapi.parse_posts(listing(post(1, preview_url="https://evil.example/t.jpg")), ORIGIN, DOMAIN)
        self.assertEqual(posts[0].thumb_url, "")


class TestParseFileUrl(unittest.TestCase):
    def test_file_url_field(self):
        self.assertEqual(dapi.parse_file_url(listing(post(1)), 1, ORIGIN, DOMAIN), FILE)

    def test_rebuilt_from_directory_and_image_when_absent(self):
        self.assertEqual(dapi.parse_file_url(listing(post(1, file_url=None)), 1, ORIGIN, DOMAIN), FILE)

    def test_nothing_to_go_on_is_none_not_the_site_root(self):
        item = post(1, file_url=None, directory="", image="")
        self.assertIsNone(dapi.parse_file_url(listing(item), 1, ORIGIN, DOMAIN))

    def test_only_the_requested_post_counts(self):
        self.assertIsNone(dapi.parse_file_url(listing(post(2)), 1, ORIGIN, DOMAIN))

    def test_foreign_and_hostile_hosts_are_refused(self):
        for bad in (
            "https://evil.example/a.jpg",
            "https://safebooru.org.evil.example/a.jpg",
            "https://evilsafebooru.org/a.jpg",
            "https://safebooru.org@evil.example/a.jpg",
            "http://169.254.169.254/latest/meta-data/",
            "file:///etc/passwd",
        ):
            with self.subTest(url=bad):
                self.assertIsNone(dapi.parse_file_url(listing(post(1, file_url=bad)), 1, ORIGIN, DOMAIN))

    def test_garbage_body(self):
        for body in ("", REFUSED, "{}"):
            self.assertIsNone(dapi.parse_file_url(body, 1, ORIGIN, DOMAIN))


class FakeSafebooru(dapi.Safebooru):
    """Safebooru with the HTTP layer replaced by canned responses."""

    def __init__(self, count_xml="", pages=None, by_id="[]"):
        self.count_xml = count_xml
        self.pages = pages or {}
        self.by_id = by_id
        self.requested = []

    def _get_text(self, **query):
        self.requested.append(query)
        if "id" in query:
            return self.by_id
        if query.get("limit") == 1:
            return self.count_xml
        return self.pages.get(query.get("pid"), "")


class TestSource(unittest.TestCase):
    def setUp(self):
        dapi._count_cache.clear()

    def test_count_reads_header_and_is_capped(self):
        self.assertEqual(FakeSafebooru(count_xml='<posts count="90168" offset="0">').count("cat"), 90168)
        self.assertEqual(FakeSafebooru(count_xml='<posts count="6984187" offset="0">').count(""), dapi.MAX_POSITIONS)

    def test_count_zero(self):
        self.assertEqual(FakeSafebooru(count_xml='<posts count="0" offset="0">').count("zzz"), 0)

    def test_count_surfaces_a_refusal(self):
        with self.assertRaises(LookupError) as caught:
            FakeSafebooru(count_xml=REFUSED).count("cat")
        self.assertIn("API limited", str(caught.exception))

    def test_count_errors_on_unexpected_body(self):
        with self.assertRaises(LookupError):
            FakeSafebooru(count_xml="<html></html>").count("cat")

    def test_count_is_cached(self):
        source = FakeSafebooru(count_xml='<posts count="5" offset="0">')
        source.count("cat")
        source.count("cat")
        self.assertEqual(len(source.requested), 1)

    def test_positions_map_to_zero_based_api_pages(self):
        source = FakeSafebooru(pages={0: listing(post(1)), 1: listing(post(2)), 2: listing(post(3))})
        self.assertEqual(source.get_post("cat", 0).post_id, "1")
        self.assertEqual(source.get_post("cat", 100).post_id, "2")
        self.assertEqual(source.get_post("cat", 250).post_id, "3")
        self.assertEqual([q["pid"] for q in source.requested], [0, 1, 2])
        self.assertTrue(all(q["limit"] == 100 and q["json"] == 1 for q in source.requested))

    def test_depth_cap_is_not_requested(self):
        source = FakeSafebooru()
        self.assertEqual(source.page("cat", dapi.MAX_OFFSET + dapi.PAGE_SIZE), [])
        self.assertEqual(source.requested, [])

    def test_deepest_reachable_page_is_requested(self):
        source = FakeSafebooru(pages={2000: listing(post(9))})
        self.assertEqual(source.page("", dapi.MAX_OFFSET)[0].post_id, "9")

    def test_resolve_file_url_asks_for_that_post_only(self):
        source = FakeSafebooru(by_id=listing(post(7)))
        self.assertEqual(source.resolve_file_url("7"), FILE)
        self.assertEqual(source.requested[0]["id"], "7")

    def test_resolve_file_url_missing(self):
        with self.assertRaises(LookupError):
            FakeSafebooru(by_id="").resolve_file_url("7")

    def test_download_refuses_foreign_hosts(self):
        for source in (dapi.Safebooru(), dapi.Xbooru()):
            with self.subTest(source=source.name):
                with self.assertRaises(LookupError):
                    source.download("https://evil.example/a.jpg")

    def test_xbooru_accepts_its_image_subdomain(self):
        self.assertTrue(dapi.url_on_domain("https://img.xbooru.com/images/253/a.jpeg", dapi.Xbooru.domain))


class TestRegistry(unittest.TestCase):
    def test_all_sources_registered_and_gelbooru_stays_default(self):
        self.assertEqual(
            sources.SOURCE_NAMES,
            ["gelbooru", "yandere", "konachan", "konachan_net", "safebooru", "xbooru"],
        )
        self.assertEqual(sources.DEFAULT_SOURCE, "gelbooru")

    def test_every_source_pins_its_own_domain(self):
        for name in sources.SOURCE_NAMES:
            source = sources.get_source(name)
            if hasattr(source, "domain"):
                with self.subTest(source=name):
                    self.assertTrue(source.origin.startswith(f"https://{source.domain}/"))


if __name__ == "__main__":
    unittest.main()
