import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

selection = module("imagepicker.selection")


def touch(path, size=1):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"x" * size)


class TestCleanSubfolder(unittest.TestCase):
    def test_normalises(self):
        for raw, expected in (("", ""), (None, ""), ("a", "a"), ("a/b", "a/b"), ("./a//b/", "a/b"),
                              ("a\\b", "a/b"), ("  a  ", "a"), (".", "")):
            with self.subTest(raw=raw):
                self.assertEqual(selection.clean_subfolder(raw), expected)

    def test_rejects_anything_that_could_leave_the_folder(self):
        for bad in ("..", "../x", "a/../../x", "a/..", "/etc", "C:/Windows", "C:\\Windows", "a\x00b", "..\\x"):
            with self.subTest(raw=bad):
                with self.assertRaises(selection.PathError):
                    selection.clean_subfolder(bad)


class TestCleanFilename(unittest.TestCase):
    def test_plain_names_pass(self):
        self.assertEqual(selection.clean_filename(" cat (1).png "), "cat (1).png")

    def test_separators_and_dots_are_refused(self):
        for bad in ("", " ", ".", "..", "a/b.png", "a\\b.png", "x\x00.png", None):
            with self.subTest(raw=bad):
                with self.assertRaises(selection.PathError):
                    selection.clean_filename(bad)


class TestSplitImagePath(unittest.TestCase):
    def test_split(self):
        self.assertEqual(selection.split_image_path("cat.png"), ("", "cat.png"))
        self.assertEqual(selection.split_image_path("a/b/cat.png"), ("a/b", "cat.png"))
        self.assertEqual(selection.split_image_path("a\\cat.png"), ("a", "cat.png"))

    def test_bad_values(self):
        # "/cat.png" stays inside (it is just "cat.png"); "/etc/cat.png" would not
        self.assertEqual(selection.split_image_path("/cat.png"), ("", "cat.png"))
        for bad in ("", "a/", "../cat.png", "/etc/cat.png", "a/../../cat.png"):
            with self.subTest(raw=bad):
                with self.assertRaises(selection.PathError):
                    selection.split_image_path(bad)


class TestJoinInside(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = os.path.realpath(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_paths_inside(self):
        self.assertEqual(selection.join_inside(self.base, ""), self.base)
        self.assertEqual(selection.join_inside(self.base, "a/b", "c.png"), os.path.join(self.base, "a", "b", "c.png"))

    def test_escapes_are_refused(self):
        for subfolder, filename in (("..", ""), ("a/../..", "x.png"), ("", "../x.png"), ("/etc", "passwd")):
            with self.subTest(subfolder=subfolder, filename=filename):
                with self.assertRaises(selection.PathError):
                    selection.join_inside(self.base, subfolder, filename)

    def test_a_sibling_with_the_same_prefix_is_not_inside(self):
        sibling = self.base + "_other"
        with self.assertRaises(selection.PathError):
            # even if some caller smuggled an absolute-looking name past the cleaners
            selection.join_inside(self.base, "", os.path.relpath(sibling, self.base))

    def test_a_symlinked_collection_inside_the_folder_is_allowed(self):
        with tempfile.TemporaryDirectory() as outside:
            touch(os.path.join(outside, "pic.png"))
            os.symlink(outside, os.path.join(self.base, "linked"))
            path = selection.join_inside(self.base, "linked", "pic.png")
            self.assertTrue(os.path.isfile(path))


class TestListDirectory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = self.tmp.name
        touch(os.path.join(self.base, "b.png"), 10)
        touch(os.path.join(self.base, "A.JPG"), 20)
        touch(os.path.join(self.base, "notes.txt"))
        touch(os.path.join(self.base, ".hidden.png"))
        touch(os.path.join(self.base, "sub", "inner.webp"))
        touch(os.path.join(self.base, "Zoo", "x.png"))
        os.makedirs(os.path.join(self.base, ".git"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_root_listing(self):
        result = selection.list_directory(self.base, "")
        self.assertEqual([f["name"] for f in result["files"]], ["A.JPG", "b.png"])  # case-insensitive, images only
        self.assertEqual(result["folders"], ["sub", "Zoo"])  # no dot-folders
        self.assertEqual(result["files"][1]["size"], 10)
        self.assertGreater(result["files"][0]["mtime"], 0)
        self.assertFalse(result["truncated"])

    def test_subfolder_listing(self):
        result = selection.list_directory(self.base, "sub")
        self.assertEqual([f["name"] for f in result["files"]], ["inner.webp"])
        self.assertEqual(result["subfolder"], "sub")

    def test_missing_folder_and_escape(self):
        with self.assertRaises(FileNotFoundError):
            selection.list_directory(self.base, "nope")
        with self.assertRaises(selection.PathError):
            selection.list_directory(self.base, "..")

    def test_cap_marks_truncated(self):
        small = selection.MAX_ENTRIES
        selection.MAX_ENTRIES = 3
        try:
            for index in range(6):
                touch(os.path.join(self.base, "many", f"{index}.png"))
            result = selection.list_directory(self.base, "many")
        finally:
            selection.MAX_ENTRIES = small
        self.assertEqual(len(result["files"]), 3)
        self.assertTrue(result["truncated"])

    def test_broken_symlink_is_skipped(self):
        os.symlink(os.path.join(self.base, "gone.png"), os.path.join(self.base, "dangling.png"))
        names = [f["name"] for f in selection.list_directory(self.base, "")["files"]]
        self.assertNotIn("dangling.png", names)


class TestThumbs(unittest.TestCase):
    def test_bucket_is_the_smallest_that_is_large_enough(self):
        self.assertEqual(selection.thumb_size(100), 128)
        self.assertEqual(selection.thumb_size(128), 128)
        self.assertEqual(selection.thumb_size(129), 192)
        self.assertEqual(selection.thumb_size("300"), 384)
        self.assertEqual(selection.thumb_size(5000), 512)

    def test_bad_values_fall_back_to_a_middle_bucket(self):
        for bad in (None, "", "big"):
            self.assertEqual(selection.thumb_size(bad), 256)

    def test_cache_name_changes_with_the_file_and_the_size(self):
        base = selection.thumb_cache_name("a/b.png", 1, 100, 256)
        self.assertTrue(base.endswith("_256.webp"))
        self.assertNotEqual(base, selection.thumb_cache_name("a/b.png", 2, 100, 256))  # edited
        self.assertNotEqual(base, selection.thumb_cache_name("a/b.png", 1, 101, 256))
        self.assertNotEqual(base, selection.thumb_cache_name("a/c.png", 1, 100, 256))
        self.assertNotEqual(base, selection.thumb_cache_name("a/b.png", 1, 100, 128))
        self.assertEqual(base, selection.thumb_cache_name("a/b.png", 1, 100, 256))

    def test_image_name(self):
        self.assertTrue(selection.is_image_name("x.PNG"))
        self.assertFalse(selection.is_image_name("x.txt"))
        self.assertFalse(selection.is_image_name("png"))


if __name__ == "__main__":
    unittest.main()
