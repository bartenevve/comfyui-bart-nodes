import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

gelbooru = module("booru.sources.gelbooru")
picker = module("booru.pick")


def thumbnail(post_id, title, src="https://img4.gelbooru.com/thumbnails/a6/94/thumbnail_abc.jpg"):
    return (
        '<article class="thumbnail-preview">\n'
        f'<a id="p{post_id}" href="https://gelbooru.com/index.php?page=post&amp;s=view&amp;id={post_id}&tags=cat">\n'
        f'<img src="{src}" title="{title}"  alt="Rule 34 | whatever" class=""/>\n'
        "</a>\n</article>"
    )


LISTING = (
    '<div class="thumbnail-container">'
    + thumbnail("14574759", "atomicstarcat cat fluffy score:0 rating:general")
    + thumbnail("14574758", "1girl cat_ears score:12 rating:explicit")
    + "</div>"
    '<div id="paginator"> <b>1</b> '
    '<a href="?page=post&amp;s=list&amp;tags=cat&amp;pid=42">2</a>'
    '<a href="?page=post&amp;s=list&amp;tags=cat&amp;pid=84" alt="next">&rsaquo;</a>'
    '<a href="?page=post&amp;s=list&amp;tags=cat&amp;pid=126" alt="last page">&raquo;</a></div>'
)

POST_PAGE = (
    '<meta property="og:image" content="https://img4.gelbooru.com//images/a6/94/abc.jpeg" />'
    '<img width="850" height="1110" id="image" class="fit-width" '
    'src="https://img4.gelbooru.com//samples/a6/94/sample_abc.jpg">'
    '<li>Original image: <a href="https://img4.gelbooru.com/images/a6/94/abc.jpeg">here</a></li>'
)


class TestParsing(unittest.TestCase):
    def test_parse_listing_extracts_posts_in_order(self):
        posts = gelbooru.parse_listing(LISTING)
        self.assertEqual([p.post_id for p in posts], ["14574759", "14574758"])
        self.assertEqual(posts[0].tags, "atomicstarcat cat fluffy")
        self.assertEqual(posts[0].rating, "general")
        self.assertEqual(posts[1].rating, "explicit")
        self.assertTrue(posts[0].thumb_url.endswith("thumbnail_abc.jpg"))
        self.assertIn("id=14574759", posts[0].page_url)

    def test_score_and_metadata_tokens_are_not_tags(self):
        posts = gelbooru.parse_listing(thumbnail("1", "cat score:5 rating:safe id:1 md5:deadbeef"))
        self.assertEqual(posts[0].tags, "cat")

    def test_parse_listing_on_no_results(self):
        self.assertEqual(gelbooru.parse_listing("<div>Nobody here but us chickens</div>"), [])

    def test_parse_last_pid(self):
        self.assertEqual(gelbooru.parse_last_pid(LISTING), 126)

    def test_parse_last_pid_absent_without_paginator(self):
        self.assertIsNone(gelbooru.parse_last_pid(thumbnail("1", "cat")))

    def test_parse_file_url_prefers_original_and_fixes_double_slash(self):
        self.assertEqual(
            gelbooru.parse_file_url(POST_PAGE),
            "https://img4.gelbooru.com/images/a6/94/abc.jpeg",
        )

    def test_parse_file_url_falls_back_to_sample(self):
        html = '<img id="image" src="https://img4.gelbooru.com//samples/a6/94/sample_abc.jpg">'
        self.assertEqual(
            gelbooru.parse_file_url(html),
            "https://img4.gelbooru.com/samples/a6/94/sample_abc.jpg",
        )

    def test_parse_file_url_missing(self):
        self.assertIsNone(gelbooru.parse_file_url("<html>nothing here</html>"))

    def test_listing_url_encodes_tags(self):
        url = gelbooru.listing_url("1girl rating:general", 84)
        self.assertIn("tags=1girl+rating%3Ageneral", url)
        self.assertIn("pid=84", url)


class FakeSource(gelbooru.Gelbooru):
    """Gelbooru with the HTTP layer replaced by canned pages."""

    def __init__(self, pages):
        self.pages = pages
        self.requested = []

    def _get_html(self, url):
        self.requested.append(url)
        for pid, html in self.pages.items():
            if f"pid={pid}" in url:
                return html
        return "<html></html>"


class TestCounting(unittest.TestCase):
    def test_single_page_counts_its_own_thumbnails(self):
        source = FakeSource({0: thumbnail("1", "cat") + thumbnail("2", "cat")})
        self.assertEqual(source._count_uncached("cat"), 2)

    def test_no_results_is_zero(self):
        self.assertEqual(FakeSource({0: "<html></html>"})._count_uncached("cat"), 0)

    def test_count_is_last_pid_plus_last_page_length(self):
        source = FakeSource({0: LISTING, 126: thumbnail("9", "cat") + thumbnail("8", "cat")})
        self.assertEqual(source._count_uncached("cat"), 128)

    def test_unreachable_last_page_reports_the_depth_cap(self):
        deep = LISTING.replace('pid=126" alt="last page"', 'pid=999999" alt="last page"')
        source = FakeSource({0: deep})
        self.assertEqual(source._count_uncached("cat"), gelbooru.MAX_POSITIONS)
        # only the first page is fetched - the deep one is known-unreachable
        self.assertEqual(len(source.requested), 1)

    def test_page_beyond_cap_returns_nothing_without_a_request(self):
        source = FakeSource({0: LISTING})
        self.assertEqual(source.page("cat", gelbooru.MAX_PID + gelbooru.PAGE_SIZE), [])
        self.assertEqual(source.requested, [])


class TestGetPost(unittest.TestCase):
    def test_index_maps_to_page_offset(self):
        page = "".join(thumbnail(str(1000 - i), "cat") for i in range(gelbooru.PAGE_SIZE))
        source = FakeSource({42: page})
        post = source.get_post("cat", 45)
        self.assertEqual(post.post_id, "997")
        self.assertIn("pid=42", source.requested[0])

    def test_offset_past_a_short_last_page_clamps(self):
        source = FakeSource({42: thumbnail("5", "cat") + thumbnail("4", "cat")})
        self.assertEqual(source.get_post("cat", 80).post_id, "4")

    def test_empty_page_raises(self):
        with self.assertRaises(LookupError):
            FakeSource({}).get_post("cat", 0)


class TestImageUrlFilter(unittest.TestCase):
    def test_still_images_accepted(self):
        for url in ("https://x/a.png", "https://x/a.JPG", "https://x/a.jpeg", "https://x/a.gif"):
            self.assertTrue(picker.is_image_url(url), url)

    def test_video_and_junk_rejected(self):
        for url in ("https://x/a.mp4", "https://x/a.webm", "https://x/a", "https://x/a.swf"):
            self.assertFalse(picker.is_image_url(url), url)

    def test_query_string_does_not_break_extension_detection(self):
        self.assertTrue(picker.is_image_url("https://x/a.png?v=2"))


if __name__ == "__main__":
    unittest.main()
