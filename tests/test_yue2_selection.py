import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

selection = module("yue2.selection")


class TestVaeRepo(unittest.TestCase):
    def test_dropdown_values_map_to_full_hf_repo_ids(self):
        # from_pretrained wants "m-a-p/..." - the bare dropdown name is not a repo
        self.assertEqual(selection.vae_repo("YuE2-Vae"), "m-a-p/YuE2-Vae")
        self.assertEqual(selection.vae_repo("YuE2-Vae-legacy"), "m-a-p/YuE2-Vae-legacy")

    def test_unknown_choice_is_an_error(self):
        with self.assertRaises(ValueError):
            selection.vae_repo("nope")


class TestBackend(unittest.TestCase):
    def test_cuda_graph_backend_only_on_cuda(self):
        self.assertEqual(selection.backend_for("cuda"), "torch")
        for device in ("mps", "cpu"):
            self.assertEqual(selection.backend_for(device), "torch-eager")


class TestGenerateError(unittest.TestCase):
    def test_score_with_cot_off_is_rejected(self):
        self.assertIn("cot=off", selection.generate_error("off", "X:1\nK:C\nCDEF|"))

    def test_valid_combinations(self):
        self.assertIsNone(selection.generate_error("off", ""))
        self.assertIsNone(selection.generate_error("off", "   "))  # blank is dropped, not an error
        self.assertIsNone(selection.generate_error("melody", "X:1\nK:C\nCDEF|"))
        self.assertIsNone(selection.generate_error("full", ""))


class TestBuildGenerateKwargs(unittest.TestCase):
    def test_omits_abc_when_blank_or_whitespace(self):
        for blank in ("", "  \n "):
            kwargs = selection.build_generate_kwargs("style", "lyrics", "full", 42, abc=blank)
            self.assertEqual(kwargs, {"style": "style", "lyrics": "lyrics", "cot": "full", "seed": 42})

    def test_includes_abc_when_present(self):
        kwargs = selection.build_generate_kwargs("style", "lyrics", "melody", 7, abc="X:1\n")
        self.assertEqual(kwargs["abc"], "X:1\n")
        self.assertEqual(kwargs["cot"], "melody")


if __name__ == "__main__":
    unittest.main()
