import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

selection = module("simple_concat.selection")


class TestSeparator(unittest.TestCase):
    def test_the_default_is_a_line_break(self):
        self.assertEqual(selection.DEFAULT_SEPARATOR, "\\n")  # as typed in the box: backslash, n
        self.assertEqual(selection.unescape(selection.DEFAULT_SEPARATOR), "\n")

    def test_escapes(self):
        self.assertEqual(selection.unescape("\\t"), "\t")
        self.assertEqual(selection.unescape("\\r\\n"), "\r\n")
        self.assertEqual(selection.unescape("\\\\n"), "\\n")  # an escaped backslash, then a plain n
        self.assertEqual(selection.unescape("\\x \\"), "\\x \\")  # other backslashes stay
        self.assertEqual(selection.unescape(", "), ", ")
        self.assertEqual(selection.unescape(""), "")
        self.assertEqual(selection.unescape(None), "")

    def test_a_real_line_break_in_the_separator_works_too(self):
        self.assertEqual(selection.join_texts(["a", "b"], "\n"), "a\nb")


class TestToText(unittest.TestCase):
    def test_what_becomes_text(self):
        cases = (("hi", "hi"), ("", ""), (3, "3"), (-7, "-7"), (0.25, "0.25"), (1.0, "1.0"), (True, "True"), (False, "False"),
                 (b"caf\xc3\xa9", "café"), ({"a": 1, "b": "é"}, '{"a": 1, "b": "é"}'))
        for value, want in cases:
            self.assertEqual(selection.to_text(value), want, value)

    def test_nothing_is_none(self):
        self.assertIsNone(selection.to_text(None))

    def test_a_numpy_scalar(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy is not installed")
        self.assertEqual(selection.to_text(np.int64(5)), "5")
        self.assertEqual(selection.to_text(np.float32(0.5)), "0.5")
        with self.assertRaises(selection.TextError):
            selection.to_text(np.zeros((2, 2)))

    def test_things_that_are_not_text_are_refused_by_name(self):
        for value in (object(), {"samples": object()}, lambda: 1, {1, 2}):
            with self.assertRaises(selection.TextError) as ctx:
                selection.to_text(value, "text3")
            self.assertIn("text3", str(ctx.exception))
            self.assertIn("cannot be turned into text", str(ctx.exception))

    def test_the_kind_of_thing_is_named(self):
        with self.assertRaises(selection.TextError) as ctx:
            selection.to_text(object(), "text0")
        self.assertIn("an object", str(ctx.exception))

    def test_lists_contribute_their_items(self):
        self.assertEqual(selection.texts_of(["a", 2, ["b", None, 1.5]]), ["a", "2", "b", "1.5"])
        self.assertEqual(selection.texts_of(None), [])
        self.assertEqual(selection.texts_of("x"), ["x"])
        self.assertEqual(selection.texts_of(("a", "b")), ["a", "b"])

    def test_absurd_nesting_is_refused(self):
        value = "x"
        for _ in range(50):
            value = [value]
        with self.assertRaises(selection.TextError):
            selection.texts_of(value)


class TestJoin(unittest.TestCase):
    def test_slots_are_joined_in_slot_order_not_alphabetical(self):
        values = {"text10": "k", "text2": "c", "text0": "a", "text1": "b"}
        self.assertEqual(selection.join_texts(values, ", "), "a, b, c, k")

    def test_default_separator_is_a_line_break(self):
        self.assertEqual(selection.join_texts({"text0": "one", "text1": "two"}), "one\ntwo")

    def test_mixed_kinds(self):
        values = {"text0": "steps:", "text1": 20, "text2": 7.5, "text3": True}
        self.assertEqual(selection.join_texts(values, " "), "steps: 20 7.5 True")

    def test_empty_slots_are_skipped_but_empty_text_is_kept(self):
        self.assertEqual(selection.join_texts({"text0": "a", "text1": None, "text2": "", "text3": "b"}, "|"), "a||b")

    def test_nothing_at_all(self):
        self.assertEqual(selection.join_texts({}), "")
        self.assertEqual(selection.join_texts({"text0": None, "text1": None}), "")
        self.assertEqual(selection.join_texts([]), "")

    def test_a_single_text_has_no_separator(self):
        self.assertEqual(selection.join_texts({"text0": "only"}, " / "), "only")

    def test_lists_are_spread_over_the_separator(self):
        self.assertEqual(selection.join_texts({"text0": ["a", "b"], "text1": "c"}, "+"), "a+b+c")

    def test_a_list_of_values_without_names(self):
        self.assertEqual(selection.join_texts(["a", 1, None, "b"], "-"), "a-1-b")

    def test_the_error_names_the_input(self):
        with self.assertRaises(selection.TextError) as ctx:
            selection.join_texts({"text0": "a", "text1": object()})
        self.assertIn("text1", str(ctx.exception))

    def test_unicode_and_long_texts(self):
        self.assertEqual(selection.join_texts({"text0": "猫", "text1": "кот"}, " — "), "猫 — кот")
        big = "x" * 1_000_000
        self.assertEqual(len(selection.join_texts({"text0": big, "text1": big}, "")), 2_000_000)


if __name__ == "__main__":
    unittest.main()
