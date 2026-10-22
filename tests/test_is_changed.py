import importlib.util
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

HAS_TORCH = importlib.util.find_spec("torch") is not None


def same(value, other):
    """NaN never equals itself, which is exactly how ComfyUI treats it (always run)."""
    return (value != value and other != other) or value == other


class TestPrompts52IsChanged(unittest.TestCase):
    def setUp(self):
        self.node = module("prompts52.nodes").LoadRandom52Prompt

    def test_a_call_without_arguments_does_not_raise(self):
        # ComfyUI leaves linked inputs out of the call; a TypeError here only produces a warning and a re-run
        self.assertIsInstance(self.node.IS_CHANGED(), str)

    def test_fixed_seed_is_stable_and_follows_its_inputs(self):
        first = self.node.IS_CHANGED(generator="Prompts", randomize=False, seed=1)
        self.assertEqual(first, self.node.IS_CHANGED(generator="Prompts", randomize=False, seed=1))
        self.assertNotEqual(first, self.node.IS_CHANGED(generator="Prompts", randomize=False, seed=2))

    def test_randomize_always_runs(self):
        value = self.node.IS_CHANGED(generator="Prompts", randomize=True, seed=1)
        self.assertNotEqual(value, value)  # NaN


class TestMiniMaxIsChanged(unittest.TestCase):
    def setUp(self):
        self.node = module("minimaxh3prompt.nodes").MiniMaxH3Prompt

    def test_no_arguments_and_none_do_not_raise(self):
        self.assertIsInstance(self.node.IS_CHANGED(), str)
        self.assertIsInstance(self.node.IS_CHANGED(generated=None), str)


@unittest.skipUnless(HAS_TORCH, "torch is not installed")
class TestTorchNodesIsChanged(unittest.TestCase):
    def test_random_image_without_arguments(self):
        node = module("nodes").LoadRandomImage
        self.assertIsInstance(node.IS_CHANGED(), str)
        self.assertIsInstance(node.IS_CHANGED(directory=None, filename=None), str)
        value = node.IS_CHANGED(directory="/x", randomize_on_queue=True)
        self.assertNotEqual(value, value)

    def test_random_image_depends_on_directory_and_file(self):
        node = module("nodes").LoadRandomImage
        self.assertEqual(node.IS_CHANGED(directory="/a", filename="x.png"), node.IS_CHANGED(directory="/a", filename="x.png"))
        self.assertNotEqual(node.IS_CHANGED(directory="/a", filename="x.png"), node.IS_CHANGED(directory="/b", filename="x.png"))
        # the length prefix keeps ("a|b", "c") apart from ("a", "b|c")
        self.assertNotEqual(node.IS_CHANGED(directory="a|b", filename="c"), node.IS_CHANGED(directory="a", filename="b|c"))

    def test_booru_without_arguments(self):
        node = module("booru.nodes").LoadRandomBooruImage
        self.assertIsInstance(node.IS_CHANGED(), str)
        self.assertIsInstance(node.IS_CHANGED(source=None, tags=None), str)

    def test_booru_fixed_position_is_stable_and_random_modes_always_run(self):
        node = module("booru.nodes").LoadRandomBooruImage
        fixed = node.IS_CHANGED(source="gelbooru", tags="cat", index=3)
        self.assertEqual(fixed, node.IS_CHANGED(source="gelbooru", tags="cat", index=3))
        self.assertNotEqual(fixed, node.IS_CHANGED(source="gelbooru", tags="cat", index=4))
        for kwargs in ({"random_post": True}, {"increment_on_queue": True}):
            value = node.IS_CHANGED(source="gelbooru", tags="cat", index=3, **kwargs)
            self.assertNotEqual(value, value)


if __name__ == "__main__":
    unittest.main()
