import importlib.util
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

selection = module("latenttrim.selection")
HAS_TORCH = importlib.util.find_spec("torch") is not None


class TestFrameMath(unittest.TestCase):
    def test_pixel_frames_of_a_latent(self):
        # the table from WAN's own VAE: T latent frames decode to 4T - 3 pixel frames
        for latent, pixels in ((1, 1), (13, 49), (16, 61), (21, 81), (41, 161)):
            with self.subTest(latent=latent):
                self.assertEqual(selection.pixel_frames(latent), pixels)

    def test_multiples_of_four_are_exact(self):
        for pixels in (0, 4, 8, 40, 400):
            self.assertEqual(selection.latent_frames_to_trim(pixels), pixels // 4)

    def test_other_counts_snap_to_the_nearest_latent_frame(self):
        expected = {1: 0, 2: 1, 3: 1, 4: 1, 5: 1, 6: 2, 7: 2, 9: 2, 10: 3}
        for pixels, latent in expected.items():
            with self.subTest(pixels=pixels):
                self.assertEqual(selection.latent_frames_to_trim(pixels), latent)

    def test_negative_counts_trim_nothing(self):
        self.assertEqual(selection.latent_frames_to_trim(-5), 0)


class TestPlanTrim(unittest.TestCase):
    def test_removing_latent_frames_removes_exactly_four_pixel_frames_each(self):
        for total in (13, 21, 33):
            for cut in range(0, total):
                with self.subTest(total=total, cut=cut):
                    before = selection.pixel_frames(total)
                    _, removed, left = selection.plan_trim(cut * 4, total)
                    self.assertEqual(removed, cut * 4)
                    self.assertEqual(left, before - cut * 4)
                    self.assertEqual(left, selection.pixel_frames(total - cut))

    def test_report_for_a_snapped_request(self):
        # 10 px frames asked, 3 latent frames = 12 really go
        self.assertEqual(selection.plan_trim(10, 21), (3, 12, 69))

    def test_no_trim(self):
        self.assertEqual(selection.plan_trim(0, 21), (0, 0, 81))
        self.assertEqual(selection.plan_trim(1, 21), (0, 0, 81))  # rounds down to nothing

    def test_asking_for_everything_or_more_is_an_error(self):
        for pixels in (84, 100, 5000):
            with self.subTest(pixels=pixels):
                with self.assertRaises(ValueError) as caught:
                    selection.plan_trim(pixels, 21)
                self.assertIn("nothing would remain", str(caught.exception))

    def test_the_largest_valid_request_leaves_one_latent_frame(self):
        self.assertEqual(selection.plan_trim(80, 21), (20, 80, 1))


@unittest.skipUnless(HAS_TORCH, "torch is not installed")
class TestNode(unittest.TestCase):
    def setUp(self):
        import torch

        self.torch = torch
        self.node = module("latenttrim.nodes").WanLatentTrim()

    def latent(self, frames=21, **extra):
        # each latent frame carries its own index so a cut is easy to read back
        samples = self.torch.arange(frames, dtype=self.torch.float32).view(1, 1, frames, 1, 1).expand(2, 16, frames, 4, 4).clone()
        return {"samples": samples, **extra}

    def test_removes_the_requested_frames_from_the_start(self):
        out, removed, left = self.node.trim(self.latent(), 8)
        self.assertEqual(out["samples"].shape, (2, 16, 19, 4, 4))
        self.assertEqual(out["samples"][0, 0, 0, 0, 0].item(), 2.0)  # frames 0 and 1 are gone
        self.assertEqual((removed, left), (8, 73))

    def test_does_not_touch_the_input_latent(self):
        original = self.latent()
        self.node.trim(original, 8)
        self.assertEqual(original["samples"].shape[2], 21)

    def test_zero_is_a_passthrough(self):
        original = self.latent()
        out, removed, left = self.node.trim(original, 0)
        self.assertTrue(self.torch.equal(out["samples"], original["samples"]))
        self.assertEqual((removed, left), (0, 81))

    def test_snapped_request_reports_what_really_went(self):
        _, removed, left = self.node.trim(self.latent(), 10)
        self.assertEqual((removed, left), (12, 69))

    def test_a_temporal_mask_is_trimmed_with_the_samples(self):
        mask = self.torch.arange(21, dtype=self.torch.float32).view(1, 1, 21, 1, 1).expand(1, 1, 21, 4, 4).clone()
        out, _, _ = self.node.trim(self.latent(noise_mask=mask), 12)
        self.assertEqual(out["noise_mask"].shape[2], 18)
        self.assertEqual(out["noise_mask"][0, 0, 0, 0, 0].item(), 3.0)

    def test_masks_that_are_not_per_frame_are_left_alone(self):
        flat = self.torch.ones(1, 1, 4, 4)
        broadcast = self.torch.ones(1, 1, 1, 4, 4)
        for mask in (flat, broadcast):
            out, _, _ = self.node.trim(self.latent(noise_mask=mask), 12)
            self.assertIs(out["noise_mask"], mask)

    def test_other_latent_keys_survive(self):
        out, _, _ = self.node.trim(self.latent(batch_index=[0, 1], downscale_ratio_spacial=8), 4)
        self.assertEqual(out["batch_index"], [0, 1])
        self.assertEqual(out["downscale_ratio_spacial"], 8)

    def test_image_latents_are_refused_with_a_clear_message(self):
        with self.assertRaises(ValueError) as caught:
            self.node.trim({"samples": self.torch.zeros(1, 4, 8, 8)}, 4)
        self.assertIn("5D video latent", str(caught.exception))

    def test_trimming_everything_is_refused(self):
        with self.assertRaises(ValueError):
            self.node.trim(self.latent(frames=5), 20)

    def test_output_order_keeps_the_latent_in_slot_zero(self):
        node = module("latenttrim.nodes").WanLatentTrim
        self.assertEqual(node.RETURN_TYPES[0], "LATENT")
        self.assertEqual(node.RETURN_NAMES, ("samples", "removed_frames", "frames_left"))


if __name__ == "__main__":
    unittest.main()
