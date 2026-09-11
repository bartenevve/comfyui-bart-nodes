import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

selection = module("yue2.selection")
read_first_file = selection.read_first_file
build_generate_kwargs = selection.build_generate_kwargs


class TestReadFirstFile(unittest.TestCase):
    def test_reads_the_only_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "score.abc")
            with open(path, "w", encoding="utf-8") as f:
                f.write("X:1\nT:Test\n")
            self.assertEqual(read_first_file(tmp, "*.abc"), "X:1\nT:Test\n")

    def test_picks_first_match_alphabetically_when_several_exist(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, content in (("b.abc", "second"), ("a.abc", "first")):
                with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
                    f.write(content)
            self.assertEqual(read_first_file(tmp, "*.abc"), "first")

    def test_raises_file_not_found_when_no_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                read_first_file(tmp, "*.abc")

    def test_ignores_non_matching_extensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "notes.txt"), "w", encoding="utf-8") as f:
                f.write("not a score")
            with self.assertRaises(FileNotFoundError):
                read_first_file(tmp, "*.abc")


class TestBuildGenerateKwargs(unittest.TestCase):
    def test_omits_abc_when_blank(self):
        kwargs = build_generate_kwargs("style", "lyrics", "full", 42, abc="")
        self.assertNotIn("abc", kwargs)
        self.assertEqual(kwargs, {"style": "style", "lyrics": "lyrics", "cot": "full", "seed": 42})

    def test_includes_abc_when_present(self):
        kwargs = build_generate_kwargs("style", "lyrics", "melody", 7, abc="X:1\n")
        self.assertEqual(kwargs["abc"], "X:1\n")
        self.assertEqual(kwargs["cot"], "melody")


if __name__ == "__main__":
    unittest.main()
