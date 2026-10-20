import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

selection = module("minimaxh3prompt.selection")

VALID = {"ollama_url": "http://localhost:11434", "model": "qwen3.6:35b-a3b", "request": "a cat"}


class TestNormalizeUrl(unittest.TestCase):
    def test_strips_trailing_slash(self):
        self.assertEqual(selection.normalize_url(" http://host:11434/ "), "http://host:11434")

    def test_rejects_other_schemes_and_garbage(self):
        for bad in ("", None, "host:11434", "file:///etc/passwd", "ftp://host", "http://", "javascript:alert(1)"):
            with self.subTest(url=bad):
                with self.assertRaises(selection.InputError):
                    selection.normalize_url(bad)


class TestCoerceOptions(unittest.TestCase):
    def test_defaults_fill_in(self):
        options = selection.coerce_options(VALID)
        self.assertEqual(options["duration"], 8)
        self.assertEqual(options["retries"], 2)
        self.assertEqual(options["aspect"], "16:9")
        self.assertEqual(options["variant"], "auto")
        self.assertEqual(options["temperature"], 0.3)
        self.assertFalse(options["think"])
        self.assertEqual(options["refs"], "")

    def test_json_strings_are_coerced(self):
        options = selection.coerce_options({**VALID, "duration": "10", "seed": "42", "temperature": "0.5"})
        self.assertEqual((options["duration"], options["seed"], options["temperature"]), (10, 42, 0.5))

    def test_out_of_range_names_the_field(self):
        for field, value in (("duration", 3), ("duration", 121), ("seed", -1), ("seed", selection.MAX_SEED + 1),
                             ("retries", 6), ("shots", 4), ("num_ctx", 10), ("timeout", 5), ("temperature", 3)):
            with self.subTest(field=field, value=value):
                with self.assertRaises(selection.InputError) as caught:
                    selection.coerce_options({**VALID, field: value})
                self.assertIn(field, str(caught.exception))

    def test_non_numbers_and_booleans(self):
        with self.assertRaises(selection.InputError):
            selection.coerce_options({**VALID, "duration": "ten"})
        # a JSON true must not become duration 1 / fall through as an int
        self.assertEqual(selection.coerce_options({**VALID, "duration": True})["duration"], 8)

    def test_unknown_choice_values_are_rejected(self):
        for field, value in (("aspect", "5:4"), ("mode", "V2V"), ("variant", "nope")):
            with self.subTest(field=field):
                with self.assertRaises(selection.InputError):
                    selection.coerce_options({**VALID, field: value})

    def test_blank_model_and_bad_url(self):
        with self.assertRaises(selection.InputError):
            selection.coerce_options({**VALID, "model": "  "})
        with self.assertRaises(selection.InputError):
            selection.coerce_options({**VALID, "ollama_url": "file:///x"})


class TestClips(unittest.TestCase):
    def test_single_clip_is_stored_bare(self):
        self.assertEqual(selection.join_clips(["one"]), "one")
        self.assertEqual(selection.split_clips("one"), ["one"])

    def test_round_trip_with_markers(self):
        text = selection.join_clips(["first\nline", "second"], [10, 10])
        self.assertIn("=== CLIP 1 (10 s) ===", text)
        self.assertEqual(selection.split_clips(text), ["first\nline", "second"])

    def test_markers_without_durations(self):
        text = selection.join_clips(["a", "b", "c"])
        self.assertEqual(selection.split_clips(text), ["a", "b", "c"])

    def test_hand_edited_text_is_forgiven(self):
        text = "intro line\n=== CLIP 1 ===\nbody\n\n\n=== CLIP 2 (5 s) ===\n\n=== CLIP 3 ===\nlast  "
        self.assertEqual(selection.split_clips(text), ["intro line", "body", "last"])

    def test_empty_text_has_no_clips(self):
        for blank in ("", "  \n\t"):
            self.assertEqual(selection.split_clips(blank), [])

    def test_a_marker_lookalike_inside_a_line_is_not_a_marker(self):
        self.assertEqual(selection.split_clips("see === CLIP 2 === above"), ["see === CLIP 2 === above"])


class TestFrameSize(unittest.TestCase):
    def test_common_aspects_at_768(self):
        for aspect, expected in (("16:9", (1344, 768)), ("9:16", (768, 1344)), ("1:1", (768, 768)),
                                 ("4:3", (1024, 768)), ("3:4", (768, 1024)), ("21:9", (1792, 768))):
            with self.subTest(aspect=aspect):
                self.assertEqual(selection.frame_size(aspect, 768), expected)

    def test_sides_are_multiples_of_32_and_never_exceed_the_budget(self):
        for aspect in selection.ASPECTS:
            for short in (256, 480, 500, 720, 1000):
                with self.subTest(aspect=aspect, short=short):
                    width, height = selection.frame_size(aspect, short)
                    self.assertEqual((width % 32, height % 32), (0, 0))
                    self.assertLessEqual(min(width, height), short)

    def test_orientation_follows_the_aspect(self):
        width, height = selection.frame_size("9:16", 480)
        self.assertLess(width, height)


class TestTimedClips(unittest.TestCase):
    def test_durations_come_from_the_markers(self):
        text = selection.join_clips(["a", "b"], [10, 5])
        self.assertEqual(selection.split_timed_clips(text), [("a", 10), ("b", 5)])

    def test_bare_text_has_no_duration(self):
        self.assertEqual(selection.split_timed_clips("one"), [("one", None)])
        self.assertEqual(selection.split_timed_clips(""), [])

    def test_clip_durations_fallbacks(self):
        self.assertEqual(selection.clip_durations([("a", None)], 8), [8])
        self.assertEqual(selection.clip_durations([("a", None), ("b", None)], 20), [10, 10])
        self.assertEqual(selection.clip_durations([("a", 10), ("b", None)], 20), [10, 10])
        self.assertEqual(selection.clip_durations([("a", 4), ("b", 6)], 99), [4, 6])


class TestShortSideRange(unittest.TestCase):
    def test_bounds(self):
        selection.coerce_options({**VALID, "short_side": 256})
        selection.coerce_options({**VALID, "short_side": 4096})
        for bad in (255, 4097):
            with self.assertRaises(selection.InputError):
                selection.coerce_options({**VALID, "short_side": bad})


class TestReport(unittest.TestCase):
    def test_ok(self):
        report = selection.format_report("t2va", 1, [], [])
        self.assertIn("variant: t2va", report)
        self.assertIn("validator: OK", report)

    def test_errors_and_warnings(self):
        report = selection.format_report("ref", 1, ["no <Subject 1>"], ["max 9 images"])
        self.assertIn("warnings: max 9 images", report)
        self.assertIn("- no <Subject 1>", report)
        self.assertNotIn("validator: OK", report)


if __name__ == "__main__":
    unittest.main()
