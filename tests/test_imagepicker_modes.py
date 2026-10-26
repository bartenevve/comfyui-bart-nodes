"""Image Picker's random / sequential modes: the pool listing, the seeded pick, the pointer, the node."""
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

selection = module("imagepicker.selection")

HAS_DEPS = all(importlib.util.find_spec(name) is not None for name in ("torch", "numpy", "PIL"))


def touch(base, *relative):
    path = os.path.join(base, *relative)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"x")
    return path


class TestListPool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = self.tmp.name
        for name in ("img10.png", "img2.png", "Img1.JPG", "notes.txt", ".hidden.png"):
            touch(self.base, "trip", name)
        touch(self.base, "trip", "deep", "a.webp")
        touch(self.base, "trip", ".cache", "t.png")
        touch(self.base, "top.png")

    def test_one_level_in_natural_order_without_dotfiles_or_other_types(self):
        files, truncated = selection.list_pool(self.base, "trip")
        self.assertEqual(files, ["trip/Img1.JPG", "trip/img2.png", "trip/img10.png"])
        self.assertFalse(truncated)

    def test_recursive_includes_subfolders_but_not_dot_folders(self):
        files, _ = selection.list_pool(self.base, "trip", recursive=True)
        self.assertEqual(files, ["trip/deep/a.webp", "trip/Img1.JPG", "trip/img2.png", "trip/img10.png"])

    def test_the_input_folder_itself(self):
        self.assertEqual(selection.list_pool(self.base, "")[0], ["top.png"])
        self.assertEqual(len(selection.list_pool(self.base, "", recursive=True)[0]), 5)

    def test_paths_are_always_relative_to_the_base_with_forward_slashes(self):
        files, _ = selection.list_pool(self.base, "trip/deep")
        self.assertEqual(files, ["trip/deep/a.webp"])

    def test_the_cap_is_reported_and_keeps_the_first_files(self):
        with mock.patch.object(selection, "MAX_POOL", 2):
            files, truncated = selection.list_pool(self.base, "trip")
        self.assertTrue(truncated)
        self.assertEqual(len(files), 2)

    def test_escaping_the_base_is_refused(self):
        for bad in ("..", "../x", "/etc", "a/../../b"):
            with self.assertRaises(selection.PathError):
                selection.list_pool(self.base, bad)

    def test_missing_folder_gives_nothing_to_list(self):
        self.assertEqual(selection.list_pool(self.base, "nope"), ([], False))

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_a_symlink_loop_does_not_hang(self):
        os.symlink(os.path.join(self.base, "trip"), os.path.join(self.base, "trip", "deep", "loop"))
        files, _ = selection.list_pool(self.base, "trip", recursive=True)
        self.assertEqual(len(files), 4)


class TestSeededPick(unittest.TestCase):
    FILES = [f"f{i}.png" for i in range(10)]

    def test_same_seed_same_file(self):
        self.assertEqual(selection.pick_seeded(self.FILES, 7), selection.pick_seeded(self.FILES, 7))

    def test_every_file_is_reachable_and_the_spread_is_even_enough(self):
        counts = {}
        for seed in range(2000):
            counts[selection.pick_seeded(self.FILES, seed)] = counts.get(selection.pick_seeded(self.FILES, seed), 0) + 1
        self.assertEqual(len(counts), 10)
        self.assertGreater(min(counts.values()), 100)

    def test_consecutive_seeds_do_not_walk_the_list(self):
        picks = [self.FILES.index(selection.pick_seeded(self.FILES, seed)) for seed in range(12)]
        steps = {(b - a) % 10 for a, b in zip(picks, picks[1:])}
        self.assertGreater(len(steps), 3)

    def test_one_file_pool(self):
        self.assertEqual(selection.pick_seeded(["only.png"], 123456), "only.png")


class TestChooseImage(unittest.TestCase):
    FILES = ["a.png", "b.png", "c.png"]

    def run_seq(self, image, state, serial="", key="k"):
        return selection.choose_image(self.FILES, "sequential", image, 0, unique_id="1", pool_key=key, edit_serial=serial, state=state)

    def test_fixed_is_the_image_itself(self):
        self.assertEqual(selection.choose_image(self.FILES, "fixed", "zzz.png", 0), ("zzz.png", None))

    def test_random_ignores_the_image_widget(self):
        chosen, following = selection.choose_image(self.FILES, "random", "", 3)
        self.assertIn(chosen, self.FILES)
        self.assertIsNone(following)

    def test_empty_pool_is_an_error_in_every_mode(self):
        for mode in ("random", "sequential"):
            with self.assertRaises(FileNotFoundError):
                selection.choose_image([], mode, "", 0)

    def test_sequential_loads_the_shown_file_then_advances_and_wraps(self):
        state = {}
        self.assertEqual(self.run_seq("b.png", state), ("b.png", "c.png"))
        self.assertEqual(self.run_seq("c.png", state), ("c.png", "a.png"))
        self.assertEqual(self.run_seq("a.png", state), ("a.png", "b.png"))

    def test_a_batch_queued_with_the_same_snapshot_still_advances(self):
        state = {}
        got = [self.run_seq("a.png", state, serial="s1")[0] for _ in range(4)]
        self.assertEqual(got, ["a.png", "b.png", "c.png", "a.png"])

    def test_a_hand_pick_wins_even_of_the_file_the_previous_run_started_with(self):
        state = {}
        self.run_seq("a.png", state, serial="s1")
        self.run_seq("a.png", state, serial="s1")  # now the pointer is on c
        self.assertEqual(self.run_seq("a.png", state, serial="s2")[0], "a.png")

    def test_an_image_outside_the_pool_starts_from_the_first(self):
        self.assertEqual(self.run_seq("other/x.png", {})[0], "a.png")

    def test_pools_do_not_share_a_pointer(self):
        state = {}
        self.run_seq("a.png", state, serial="s", key="one")
        self.run_seq("a.png", state, serial="s", key="one")
        self.assertEqual(self.run_seq("a.png", state, serial="s", key="two")[0], "a.png")


@unittest.skipUnless(HAS_DEPS, "torch, numpy and Pillow are needed")
class TestNode(unittest.TestCase):
    def setUp(self):
        from PIL import Image

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        fake = types.ModuleType("folder_paths")
        fake.get_input_directory = lambda: self.tmp.name
        # not mock.patch.dict(sys.modules): restoring that snapshot would unload torch, and importing it twice crashes
        sys.modules["folder_paths"] = fake
        self.addCleanup(sys.modules.pop, "folder_paths", None)
        sys.modules.pop("random_image_pack_under_test.imagepicker.nodes", None)
        self.nodes = module("imagepicker.nodes")
        self.node = self.nodes.ImagePicker()
        for name, colour in (("one/a.png", (255, 0, 0)), ("one/b.png", (0, 255, 0)), ("one/two/c.png", (0, 0, 255))):
            path = os.path.join(self.tmp.name, *name.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            Image.new("RGB", (4, 3), colour).save(path)

    def test_fixed_mode_is_unchanged_and_the_new_outputs_are_appended(self):
        out = self.node.load_image("one/a.png")
        self.assertEqual(self.nodes.ImagePicker.RETURN_NAMES[:5], ("IMAGE", "MASK", "filename", "width", "height"))
        self.assertEqual(self.nodes.ImagePicker.RETURN_NAMES[5], "folder")
        self.assertEqual(out["result"][2:], ("one/a.png", 4, 3, "one"))
        self.assertEqual(out["ui"]["loaded"], ["one/a.png"])
        self.assertNotIn("next", out["ui"])

    def test_random_mode_loads_what_the_seed_selects(self):
        pool = ["one/a.png", "one/b.png"]
        want = selection.pick_seeded(pool, 11)
        out = self.node.load_image("", mode="random", folder="one", seed=11)
        self.assertEqual(out["result"][2], want)

    def test_random_mode_can_include_subfolders(self):
        seen = {self.node.load_image("", mode="random", folder="one", include_subfolders=True, seed=s)["result"][2] for s in range(60)}
        self.assertEqual(seen, {"one/a.png", "one/b.png", "one/two/c.png"})

    def test_sequential_returns_the_next_file_for_the_widget(self):
        out = self.node.load_image("one/a.png", mode="sequential", folder="one", unique_id="77")
        self.assertEqual(out["result"][2], "one/a.png")
        self.assertEqual(out["ui"]["next"], ["one/b.png"])

    def test_an_empty_or_missing_folder_is_a_clear_error(self):
        os.makedirs(os.path.join(self.tmp.name, "empty"))
        for folder in ("empty", "nope"):
            with self.assertRaises(FileNotFoundError):
                self.node.load_image("", mode="random", folder=folder, seed=1)

    def test_a_folder_outside_the_input_folder_is_refused(self):
        with self.assertRaises(selection.PathError):
            self.node.load_image("", mode="random", folder="../..", seed=1)

    def test_an_unknown_mode_falls_back_to_fixed(self):
        self.assertEqual(self.node.load_image("one/b.png", mode="bogus")["result"][2], "one/b.png")

    def test_is_changed_is_stable_for_a_fixed_seed_and_not_for_sequential(self):
        cls = self.nodes.ImagePicker
        first = cls.IS_CHANGED("", mode="random", folder="one", seed=5)
        self.assertEqual(first, cls.IS_CHANGED("", mode="random", folder="one", seed=5))
        self.assertIsInstance(first, str)
        seeds = {cls.IS_CHANGED("", mode="random", folder="one", seed=s) for s in range(30)}
        self.assertGreater(len(seeds), 1)
        value = cls.IS_CHANGED("one/a.png", mode="sequential", folder="one")
        self.assertNotEqual(value, value)  # nan

    def test_is_changed_tolerates_missing_inputs(self):
        cls = self.nodes.ImagePicker
        self.assertNotEqual(cls.IS_CHANGED(), cls.IS_CHANGED())  # nan: nothing to hash
        self.assertNotEqual(cls.IS_CHANGED("", mode="random", folder="missing"), "")

    def test_input_types_keep_image_first_and_append_the_new_widgets(self):
        spec = self.nodes.ImagePicker.INPUT_TYPES()
        self.assertEqual(list(spec["required"]), ["image"])
        self.assertEqual(list(spec["optional"]), ["mode", "folder", "include_subfolders", "seed", "edit_serial"])
        self.assertTrue(spec["optional"]["seed"][1]["control_after_generate"])


if __name__ == "__main__":
    unittest.main()
