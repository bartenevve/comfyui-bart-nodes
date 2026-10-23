import importlib.util
import json
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

HAS_DEPS = all(importlib.util.find_spec(name) is not None for name in ("torch", "numpy", "PIL"))


def answer(found, key="extra_limbs", confidence=0.9):
    return json.dumps({"checks": {key: {"found": found, "confidence": confidence, "note": "n"}}})


@unittest.skipUnless(HAS_DEPS, "torch, numpy and Pillow are needed")
class TestAnatomyNode(unittest.TestCase):
    def setUp(self):
        import torch

        self.torch = torch
        self.nodes = module("anatomy.nodes")
        self.node = self.nodes.AnatomyDefectFilter()
        self.options = dict(
            ollama_url="http://localhost:11434",
            model="m",
            custom_criterion="",
            confidence_threshold=0.6,
            max_side=64,
            timeout=5,
            num_ctx=2048,
            append_no_think=True,
            seed=10,
            empty_branch="placeholder",
            extra_limbs=True,
        )

    def batch(self, count, height=20, width=30):
        # each image has its own brightness so a split is easy to read back
        return self.torch.stack([self.torch.full((height, width, 3), (i + 1) / (count + 1)) for i in range(count)])

    def run_filter(self, images, answers, **overrides):
        chat = mock.Mock(side_effect=answers)
        with mock.patch.object(self.nodes.ollama, "chat", chat):
            return self.node.filter(images, **{**self.options, **overrides}), chat

    def test_the_batch_is_split_in_order_and_reported(self):
        (passed, failed, report, report_json, passed_idx, failed_idx), chat = self.run_filter(
            self.batch(4), [answer(False), answer(True), answer(False), answer(True)]
        )
        self.assertEqual((passed_idx, failed_idx), ("0,2", "1,3"))
        self.assertEqual(passed.shape[0], 2)
        self.assertEqual(failed.shape[0], 2)
        self.assertAlmostEqual(float(passed[0, 0, 0, 0]), 1 / 5, places=5)  # image 0 first
        self.assertAlmostEqual(float(passed[1, 0, 0, 0]), 3 / 5, places=5)
        self.assertAlmostEqual(float(failed[0, 0, 0, 0]), 2 / 5, places=5)
        self.assertIn("#1 FAIL extra_limbs", report)
        self.assertEqual(len(json.loads(report_json)), 4)
        self.assertEqual(chat.call_count, 4)

    def test_the_prompt_asks_about_the_chosen_checks_and_ends_with_no_think(self):
        _, chat = self.run_filter(self.batch(1), [answer(False)])
        prompt = chat.call_args.args[2]
        self.assertIn("extra_limbs", prompt)
        self.assertNotIn("bad_fingers", prompt)
        self.assertTrue(prompt.endswith("/no_think"))

    def test_no_think_can_be_switched_off(self):
        _, chat = self.run_filter(self.batch(1), [answer(False)], append_no_think=False)
        self.assertFalse(chat.call_args.args[2].endswith("/no_think"))

    def test_a_found_defect_below_the_threshold_still_passes(self):
        (_, _, _, _, passed_idx, failed_idx), _ = self.run_filter(self.batch(1), [answer(True, confidence=0.3)])
        self.assertEqual((passed_idx, failed_idx), ("0", ""))

    def test_an_empty_failed_branch_is_a_black_placeholder_of_the_input_size(self):
        (passed, failed, *_), _ = self.run_filter(self.batch(2, height=20, width=30), [answer(False), answer(False)])
        self.assertEqual(passed.shape, (2, 20, 30, 3))
        self.assertEqual(tuple(failed.shape), (1, 20, 30, 3))
        self.assertEqual(float(failed.sum()), 0.0)

    def test_an_empty_branch_can_be_an_execution_blocker(self):
        class ExecutionBlocker:
            def __init__(self, message):
                self.message = message

        fake = types.ModuleType("comfy_execution.graph")
        fake.ExecutionBlocker = ExecutionBlocker
        with mock.patch.dict(sys.modules, {"comfy_execution": types.ModuleType("comfy_execution"), "comfy_execution.graph": fake}):
            (_, failed, *_), _ = self.run_filter(self.batch(1), [answer(False)], empty_branch="blocker")
        self.assertIsInstance(failed, ExecutionBlocker)

    def test_an_unparsable_answer_is_retried_once_with_another_seed_then_fails(self):
        with self.assertRaises(RuntimeError) as caught:
            self.run_filter(self.batch(1), ["not json", "still not json"])
        self.assertIn("did not return a usable verdict", str(caught.exception))
        seeds = []

        def chat(url, model, prompt, image, timeout=0, seed=0, num_ctx=0):
            seeds.append(seed)
            return "garbage"

        with mock.patch.object(self.nodes.ollama, "chat", chat):
            with self.assertRaises(RuntimeError):
                self.node.filter(self.batch(1), **self.options)
        self.assertEqual(seeds, [10, 11])

    def test_the_retry_can_save_the_image(self):
        (_, _, _, _, passed_idx, _), chat = self.run_filter(self.batch(1), ["garbage", answer(False)])
        self.assertEqual(passed_idx, "0")
        self.assertEqual(chat.call_count, 2)

    def test_rgba_images_are_sent_as_rgb(self):
        rgba = self.torch.rand(1, 16, 16, 4)
        _, chat = self.run_filter(rgba, [answer(False)])
        self.assertIsInstance(chat.call_args.args[3], str)  # a base64 JPEG was produced without error

    def test_large_images_are_downscaled_before_sending(self):
        import base64
        import io

        from PIL import Image

        _, chat = self.run_filter(self.batch(1, height=400, width=800), [answer(False)], max_side=100)
        sent = Image.open(io.BytesIO(base64.b64decode(chat.call_args.args[3])))
        self.assertEqual(max(sent.size), 100)

    def test_validate_inputs_checks_what_it_can_and_skips_linked_values(self):
        validate = self.nodes.AnatomyDefectFilter.VALIDATE_INPUTS
        self.assertIs(validate(), True)
        self.assertIn("http", validate(ollama_url="file:///etc/passwd"))
        self.assertEqual(validate(model="  "), "model is empty")
        none_on = dict(extra_limbs=False, missing_limbs=False, bad_fingers=False, smeared_limbs=False,
                       impossible_pose=False, face_deformation=False, merged_bodies=False)
        self.assertIn("at least one", validate(custom_criterion="", **none_on))
        self.assertIs(validate(custom_criterion="a thumb is missing", **none_on), True)


if __name__ == "__main__":
    unittest.main()
