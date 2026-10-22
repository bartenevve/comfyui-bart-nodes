import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

picker = module("booru.pick")
selection = module("booru.selection")
fetch = module("booru.fetch")


class FakeSource:
    """Posts 0..total-1; post ids listed in `videos` resolve to .mp4 files."""

    def __init__(self, total, videos=()):
        self.total = total
        self.videos = set(videos)
        self.downloads = []

    def count(self, tags):
        return self.total

    def get_post(self, tags, index):
        return types.SimpleNamespace(
            post_id=str(index), tags="t", rating="general", page_url=f"p{index}", thumb_url=f"t{index}"
        )

    def resolve_file_url(self, post_id):
        ext = "mp4" if int(post_id) in self.videos else "jpg"
        return f"https://img.gelbooru.com/images/{post_id}.{ext}"

    def download(self, url):
        self.downloads.append(url)
        return "/tmp/" + url.rsplit("/", 1)[-1]


class PickTestCase(unittest.TestCase):
    def setUp(self):
        self.state = {}
        patcher = mock.patch.object(selection, "_INCREMENT_STATE", self.state)
        patcher.start()
        self.addCleanup(patcher.stop)
        picker._FILE_URLS.clear()

    def pick(self, source, **kwargs):
        with mock.patch.object(picker, "get_source", return_value=source):
            return picker.pick("fake", "cat", unique_id="n", **kwargs)


class TestFixedMode(PickTestCase):
    def test_returns_the_requested_position(self):
        result = self.pick(FakeSource(10), random_post=False, index=4)
        self.assertEqual((result["index"], result["post_id"], result["next_index"]), (4, "4", 4))

    def test_video_at_the_requested_position_raises_instead_of_drifting(self):
        with self.assertRaises(picker.UnsupportedPostError):
            self.pick(FakeSource(10, videos={4}), random_post=False, index=4)

    def test_empty_search_raises(self):
        with self.assertRaises(picker.NoPostsError):
            self.pick(FakeSource(0), random_post=False)


class TestIncrementMode(PickTestCase):
    def test_walks_the_list_one_step_per_run(self):
        source, widget, seen = FakeSource(5), 0, []
        for _ in range(6):
            result = self.pick(source, random_post=False, increment_on_queue=True, index=widget)
            seen.append(result["index"])
            widget = result["next_index"]  # what the frontend writes back
        self.assertEqual(seen, [0, 1, 2, 3, 4, 0])

    def test_skips_a_video_and_lands_on_the_next_image(self):
        source = FakeSource(5, videos={1})
        first = self.pick(source, random_post=False, increment_on_queue=True, index=0)
        second = self.pick(source, random_post=False, increment_on_queue=True, index=first["next_index"])
        self.assertEqual(first["index"], 0)
        # position 1 is a video: the run lands on 2 and the next one carries on from 3
        self.assertEqual((second["index"], second["post_id"], second["next_index"]), (2, "2", 3))

    def test_gives_up_with_an_error_after_a_run_of_videos(self):
        source = FakeSource(20, videos=set(range(20)))
        with self.assertRaises(picker.UnsupportedPostError):
            self.pick(source, random_post=False, increment_on_queue=True, index=0)

    def test_queued_batch_with_one_stale_index_still_advances(self):
        source = FakeSource(5)
        seen = [self.pick(source, random_post=False, increment_on_queue=True, index=2)["index"] for _ in range(3)]
        self.assertEqual(seen, [2, 3, 4])


class FlakySource(FakeSource):
    """download() fails for the posts in `fail` with the given error."""

    def __init__(self, total, fail, error):
        super().__init__(total)
        self.fail = set(fail)
        self.error = error

    def download(self, url):
        post_id = int(url.rsplit("/", 1)[-1].split(".")[0])
        if post_id in self.fail:
            raise self.error
        return super().download(url)


class TestIncrementRollback(PickTestCase):
    def step(self, source, widget):
        return self.pick(source, random_post=False, increment_on_queue=True, index=widget)

    def test_a_transient_failure_does_not_use_up_the_position(self):
        source = FlakySource(5, {2}, fetch.FetchError("HTTP 503", transient=True))
        widget = 0
        for expected in (0, 1):
            result = self.step(source, widget)
            self.assertEqual(result["index"], expected)
            widget = result["next_index"]
        for _ in range(3):  # the board keeps failing: every run still asks for position 2
            with self.assertRaises(fetch.FetchError):
                self.step(source, widget)
        source.fail.clear()  # it recovers
        result = self.step(source, widget)
        self.assertEqual(result["index"], 2)  # position 2 was not skipped

    def test_a_failure_on_the_very_first_run_leaves_no_pointer_behind(self):
        source = FlakySource(5, {0}, fetch.FetchError("timed out", transient=True))
        with self.assertRaises(fetch.FetchError):
            self.step(source, 0)
        self.assertEqual(self.state, {})

    def test_a_permanent_failure_still_moves_on(self):
        # a post whose file is gone (HTTP 404) must not trap the run on that position forever
        source = FlakySource(5, {1}, fetch.FetchError("HTTP 404", transient=False))
        first = self.step(source, 0)
        with self.assertRaises(fetch.FetchError):
            self.step(source, first["next_index"])
        after = self.step(source, first["next_index"])
        self.assertEqual(after["index"], 2)

    def test_fixed_mode_has_no_pointer_to_restore(self):
        source = FlakySource(5, {3}, fetch.FetchError("HTTP 503", transient=True))
        with self.assertRaises(fetch.FetchError):
            self.pick(source, random_post=False, index=3)
        self.assertEqual(self.state, {})


class TestFetchPostFile(PickTestCase):
    def test_a_picked_post_is_served_without_asking_the_board_again(self):
        source = FakeSource(3)
        with mock.patch.object(picker, "get_source", return_value=source):
            picked = picker.pick("fake", "cat", random_post=False, index=1)
            with mock.patch.object(source, "resolve_file_url", side_effect=AssertionError("must not be asked")):
                path = picker.fetch_post_file("fake", picked["post_id"])
        self.assertEqual(path, picked["path"])

    def test_an_unknown_post_is_resolved_and_remembered(self):
        source = FakeSource(3)
        with mock.patch.object(picker, "get_source", return_value=source):
            picker.fetch_post_file("fake", "2")
            self.assertEqual(picker.known_file_url("fake", "2"), "https://img.gelbooru.com/images/2.jpg")

    def test_a_stale_link_is_resolved_again(self):
        source = FakeSource(3)
        picker.remember_file_url("fake", "1", "https://img.gelbooru.com/images/old.jpg")
        calls = []

        def download(url):
            calls.append(url)
            if url.endswith("old.jpg"):
                raise fetch.FetchError("HTTP 404")
            return "/tmp/" + url.rsplit("/", 1)[-1]

        source.download = download
        with mock.patch.object(picker, "get_source", return_value=source):
            path = picker.fetch_post_file("fake", "1")
        self.assertEqual(path, "/tmp/1.jpg")
        self.assertEqual(calls, ["https://img.gelbooru.com/images/old.jpg", "https://img.gelbooru.com/images/1.jpg"])

    def test_the_url_memory_is_bounded(self):
        for number in range(picker._FILE_URLS_MAX + 50):
            picker.remember_file_url("fake", str(number), f"https://x/{number}.jpg")
        self.assertEqual(len(picker._FILE_URLS), picker._FILE_URLS_MAX)
        self.assertIsNone(picker.known_file_url("fake", "0"))  # the oldest went first
        self.assertIsNotNone(picker.known_file_url("fake", str(picker._FILE_URLS_MAX + 49)))


class TestRandomMode(PickTestCase):
    def test_retries_past_videos(self):
        source = FakeSource(3, videos={0, 1})  # only position 2 is an image
        with mock.patch.object(selection.random, "randrange", side_effect=[0, 1, 2]) as draw:
            result = self.pick(source, random_post=True)
        self.assertEqual(result["post_id"], "2")
        self.assertEqual(draw.call_count, 3)

    def test_gives_up_after_the_retry_limit(self):
        source = FakeSource(3, videos={0, 1, 2})
        with mock.patch.object(selection.random, "randrange", return_value=0) as draw:
            with self.assertRaises(picker.UnsupportedPostError):
                self.pick(source, random_post=True)
        self.assertEqual(draw.call_count, picker.RANDOM_RETRIES)

    def test_download_is_skipped_when_not_asked_for(self):
        source = FakeSource(3)
        result = self.pick(source, random_post=False, index=1, download=False)
        self.assertIsNone(result["path"])
        self.assertEqual(source.downloads, [])


if __name__ == "__main__":
    unittest.main()
