import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

moebooru = module("booru.sources.moebooru")
sources = module("booru.sources")
base = module("booru.sources.base")
picker = module("booru.pick")

ORIGIN = "https://yande.re/"
DOMAIN = "yande.re"

FILE = "https://files.yande.re/image/abc/yande.re%201%20cat.jpg"


def post(post_id, **overrides):
    item = {
        "id": post_id,
        "tags": "cat blue_eyes",
        "rating": "s",
        "preview_url": "https://assets.yande.re/data/preview/ab/c/abc.jpg",
        "file_url": FILE,
    }
    item.update(overrides)
    return item


def listing(*posts):
    return json.dumps(list(posts))


class TestParsePosts(unittest.TestCase):
    def test_posts_in_order_with_metadata(self):
        posts = moebooru.parse_posts(listing(post(5), post(4, rating="e")), ORIGIN, DOMAIN)
        self.assertEqual([p.post_id for p in posts], ["5", "4"])
        self.assertEqual(posts[0].tags, "cat blue_eyes")
        self.assertEqual(posts[0].rating, "safe")
        self.assertEqual(posts[1].rating, "explicit")
        self.assertEqual(posts[0].page_url, "https://yande.re/post/show/5")

    def test_empty_listing(self):
        self.assertEqual(moebooru.parse_posts("[]", ORIGIN, DOMAIN), [])

    def test_skips_entries_without_a_numeric_id(self):
        posts = moebooru.parse_posts(json.dumps([post(1), {"id": "x"}, "junk", {}]), ORIGIN, DOMAIN)
        self.assertEqual([p.post_id for p in posts], ["1"])

    def test_foreign_thumbnail_host_is_dropped(self):
        posts = moebooru.parse_posts(listing(post(1, preview_url="https://evil.example/t.jpg")), ORIGIN, DOMAIN)
        self.assertEqual(posts[0].thumb_url, "")

    def test_non_json_body_is_an_error_not_an_empty_page(self):
        for body in ("<html>Just a moment...</html>", "", '{"success": false}'):
            with self.subTest(body=body):
                with self.assertRaises(LookupError):
                    moebooru.parse_posts(body, ORIGIN, DOMAIN)


class TestParseCount(unittest.TestCase):
    def test_reads_header(self):
        xml = '<?xml version="1.0"?>\n<posts count="6110" offset="0">\n<post id="1"/></posts>'
        self.assertEqual(moebooru.parse_count(xml), 6110)

    def test_zero(self):
        self.assertEqual(moebooru.parse_count('<posts count="0" offset="0"></posts>'), 0)

    def test_missing(self):
        self.assertIsNone(moebooru.parse_count("<html>nope</html>"))


class TestParseFileUrl(unittest.TestCase):
    def test_original_file_url(self):
        self.assertEqual(moebooru.parse_file_url(listing(post(1)), 1, ORIGIN, DOMAIN), FILE)

    def test_only_the_requested_post_counts(self):
        self.assertIsNone(moebooru.parse_file_url(listing(post(2)), 1, ORIGIN, DOMAIN))

    def test_foreign_and_hostile_hosts_are_refused(self):
        for bad in (
            "https://evil.example/a.jpg",
            "https://yande.re.evil.example/a.jpg",
            "https://evilyande.re/a.jpg",
            "https://yande.re@evil.example/a.jpg",
            "http://169.254.169.254/latest/meta-data/",
            "file:///etc/passwd",
            "javascript:alert(1)",
        ):
            with self.subTest(url=bad):
                self.assertIsNone(moebooru.parse_file_url(listing(post(1, file_url=bad)), 1, ORIGIN, DOMAIN))

    def test_missing_file_url(self):
        self.assertIsNone(moebooru.parse_file_url(listing(post(1, file_url=None)), 1, ORIGIN, DOMAIN))

    def test_garbage_body(self):
        self.assertIsNone(moebooru.parse_file_url("<html></html>", 1, ORIGIN, DOMAIN))


class FakeYandeRe(moebooru.YandeRe):
    """YandeRe with the HTTP layer replaced by canned responses."""

    def __init__(self, count_xml="", pages=None, post_json="[]"):
        self.count_xml = count_xml
        self.pages = pages or {}
        self.post_json = post_json
        self.requested = []

    def _get_text(self, path, **query):
        self.requested.append((path, query))
        if path == "post.xml":
            return self.count_xml
        if str(query.get("tags", "")).startswith("id:"):
            return self.post_json
        return self.pages.get(query.get("page"), "[]")


class TestSource(unittest.TestCase):
    def setUp(self):
        moebooru._count_cache.clear()

    def test_count_is_capped(self):
        source = FakeYandeRe(count_xml='<posts count="99999999" offset="0">')
        self.assertEqual(source.count("cat"), source.max_positions)

    def test_count_zero(self):
        self.assertEqual(FakeYandeRe(count_xml='<posts count="0" offset="0">').count("cat"), 0)

    def test_count_error_on_unexpected_body(self):
        with self.assertRaises(LookupError):
            FakeYandeRe(count_xml="<html>challenge</html>").count("cat")

    def test_count_is_cached(self):
        source = FakeYandeRe(count_xml='<posts count="5" offset="0">')
        source.count("cat")
        source.count("cat")
        self.assertEqual(len(source.requested), 1)

    def test_positions_map_to_one_based_pages(self):
        source = FakeYandeRe(pages={1: listing(post(1)), 2: listing(post(2)), 3: listing(post(3))})
        self.assertEqual(source.get_post("cat", 0).post_id, "1")
        self.assertEqual(source.get_post("cat", 99).post_id, "1")  # last of page 1, clamped to what's there
        self.assertEqual(source.get_post("cat", 100).post_id, "2")
        self.assertEqual(source.get_post("cat", 250).post_id, "3")
        pages = [query["page"] for path, query in source.requested if path == "post.json"]
        self.assertEqual(pages, [1, 1, 2, 3])

    def test_past_the_end_is_an_error(self):
        with self.assertRaises(LookupError):
            FakeYandeRe(pages={}).get_post("cat", 5)

    def test_resolve_file_url_asks_for_that_post_only(self):
        source = FakeYandeRe(post_json=listing(post(7)))
        self.assertEqual(source.resolve_file_url("7"), FILE)
        self.assertEqual(source.requested[0][1]["tags"], "id:7")

    def test_resolve_file_url_missing(self):
        with self.assertRaises(LookupError):
            FakeYandeRe(post_json="[]").resolve_file_url("7")

    def test_download_refuses_foreign_hosts(self):
        with self.assertRaises(LookupError):
            moebooru.YandeRe().download("https://evil.example/a.jpg")


class TestRegistry(unittest.TestCase):
    def test_both_sources_registered_and_gelbooru_stays_default(self):
        self.assertEqual(sources.SOURCE_NAMES, ["gelbooru", "yandere"])
        self.assertEqual(sources.DEFAULT_SOURCE, "gelbooru")

    def test_index_ceiling_covers_the_deepest_source(self):
        self.assertEqual(sources.max_positions(), moebooru.YandeRe.max_positions)

    def test_extension_check_sees_percent_encoded_file_names(self):
        self.assertTrue(picker.is_image_url(FILE))
        self.assertFalse(picker.is_image_url("https://files.yande.re/image/abc/yande.re%201%20clip.mp4"))


class TestUrlOnDomain(unittest.TestCase):
    def test_subdomains_and_apex(self):
        self.assertTrue(base.url_on_domain("https://yande.re/a", "yande.re"))
        self.assertTrue(base.url_on_domain("http://files.yande.re/a", "yande.re"))
        self.assertFalse(base.url_on_domain("https://notyande.re/a", "yande.re"))


if __name__ == "__main__":
    unittest.main()
