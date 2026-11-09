import importlib.util
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

selection = module("format_detector.selection")
HAS_TORCH = importlib.util.find_spec("torch") is not None


class TestFormats(unittest.TestCase):
    def test_the_list_has_the_common_video_formats_and_the_ones_of_the_h3_prompt_node(self):
        for name in ("16:9", "9:16", "4:3", "3:4", "1:1", "21:9", "9:21", "3:2", "2:3", "5:4", "4:5", "2:1", "1:2"):
            self.assertIn(name, selection.FORMATS)
        h3_prompt = module("minimaxh3prompt.selection").ASPECTS
        self.assertTrue(set(h3_prompt) <= set(selection.FORMATS))
        self.assertEqual(selection.CHOICES[0], "auto")
        self.assertEqual(selection.CHOICES[-1], "custom")

    def test_every_format_is_written_the_way_it_is_keyed(self):
        for name, (w, h) in selection.FORMATS.items():
            self.assertEqual(name, f"{w}:{h}")


class TestClosest(unittest.TestCase):
    def test_exact_proportions_give_their_format(self):
        for name, (w, h) in selection.FORMATS.items():
            self.assertEqual(selection.closest_format(w * 100, h * 100), name)

    def test_real_sizes(self):
        cases = ((1920, 1080, "16:9"), (3840, 2160, "16:9"), (1080, 1920, "9:16"), (4000, 3000, "4:3"), (3000, 4000, "3:4"),
                 (1000, 1000, "1:1"), (6000, 4000, "3:2"), (2560, 1080, "21:9"), (1080, 1350, "4:5"), (1280, 1024, "5:4"),
                 (3000, 1000, "21:9"), (4000, 2000, "2:1"), (4000, 1000, "21:9"), (500, 1000, "1:2"), (500, 1500, "9:21"))
        for w, h, want in cases:
            self.assertEqual(selection.closest_format(w, h), want, (w, h))

    def test_it_is_symmetric_for_a_turned_image(self):
        for w, h in ((1920, 1080), (1500, 1000), (1234, 987), (2400, 1000)):
            landscape, portrait = selection.closest_format(w, h), selection.closest_format(h, w)
            a, b = (int(x) for x in landscape.split(":"))
            self.assertEqual(portrait, f"{b}:{a}")

    def test_a_tie_goes_to_the_earlier_format(self):
        # 1.0 is exactly 1:1, never a tie; a ratio exactly between two formats picks the earlier one
        mid = math.exp((math.log(16 / 9) + math.log(3 / 2)) / 2)
        self.assertEqual(selection.closest_format(mid * 1000, 1000), "16:9")

    def test_nonsense_sizes_are_refused(self):
        for w, h in ((0, 10), (10, 0), (-1, 5)):
            with self.assertRaises(selection.FormatError):
                selection.closest_format(w, h)


class TestCustomRatio(unittest.TestCase):
    def test_spellings(self):
        for text, want in (("16:10", 1.6), ("16/10", 1.6), ("16x10", 1.6), (" 16 : 10 ", 1.6), ("1.85", 1.85), ("2", 2.0), ("0.5", 0.5)):
            w, h = selection.parse_ratio(text)
            self.assertAlmostEqual(w / h, want, msg=text)

    def test_bad_ratios(self):
        for text in ("", "  ", "abc", "16:", ":9", "0:9", "-1:2", "16:0", "1000:1", "1:1000", "nan", "inf:1", "1:2:3"):
            with self.assertRaises(selection.FormatError, msg=repr(text)):
                selection.parse_ratio(text)


class TestSize(unittest.TestCase):
    def test_sides_are_multiples_of_32(self):
        for name, (w, h) in selection.FORMATS.items():
            for mp in (0.05, 0.25, 0.5, 1.0, 1.03, 2.0, 4.0, 16.0):
                width, height, _ = selection.size_for(w, h, mp)
                self.assertEqual((width % 32, height % 32), (0, 0), (name, mp))
                self.assertGreaterEqual(min(width, height), 32)

    def test_the_area_follows_the_megapixels(self):
        for name, (w, h) in selection.FORMATS.items():
            width, height, _ = selection.size_for(w, h, 1.0)
            self.assertAlmostEqual(width * height / 1e6, 1.0, delta=0.22, msg=name)

    def test_the_proportions_are_kept_close(self):
        for name, (w, h) in selection.FORMATS.items():
            width, height, _ = selection.size_for(w, h, 1.03)
            self.assertAlmostEqual(math.log(width / height), math.log(w / h), delta=0.05, msg=name)

    def test_h3s_own_canvas_at_its_own_area(self):
        self.assertEqual(selection.size_for(16, 9, 1.03)[:2], (1344, 768))
        self.assertEqual(selection.size_for(9, 16, 1.03)[:2], (768, 1344))

    def test_the_cap_cuts_a_big_request_down_and_says_so(self):
        width, height, note = selection.size_for(16, 9, 4.0, limit_h3=True)
        self.assertEqual((width, height), (1344, 768))
        self.assertIn("limited to MiniMax H3's canvas", note)
        self.assertIn("4 MP", note)

    def test_the_cap_holds_for_every_format(self):
        for name, (w, h) in selection.FORMATS.items():
            for mp in (1.03, 1.5, 8.0, 64.0):
                width, height, _ = selection.size_for(w, h, mp, limit_h3=True)
                self.assertLessEqual(width * height, selection.H3_MAX_PIXELS, (name, mp))

    def test_no_note_when_the_cap_changed_nothing(self):
        self.assertEqual(selection.size_for(16, 9, 0.5, limit_h3=True)[2], "")
        self.assertEqual(selection.size_for(16, 9, 4.0, limit_h3=False)[2], "")

    def test_without_the_cap_big_sizes_are_allowed(self):
        width, height, _ = selection.size_for(16, 9, 4.0)
        self.assertGreater(width * height, 3_500_000)

    def test_extreme_ratios_still_give_valid_sizes(self):
        for w, h in ((20, 1), (1, 20), (1, 1)):
            for mp in (0.05, 1.0):
                width, height, _ = selection.size_for(w, h, mp, limit_h3=True)
                self.assertEqual((width % 32, height % 32), (0, 0))
                self.assertLessEqual(width * height, selection.H3_MAX_PIXELS)

    def test_bad_megapixels(self):
        for value in (0, -1, 0.01, 65, float("nan"), float("inf"), "x", None):
            with self.assertRaises(selection.FormatError, msg=repr(value)):
                selection.size_for(16, 9, value)


class TestCrop(unittest.TestCase):
    def test_a_wide_image_loses_its_sides_equally(self):
        self.assertEqual(selection.crop_box(1920, 1080, 1000, 1000), (420, 0, 1080, 1080))

    def test_a_tall_image_loses_top_and_bottom_equally(self):
        self.assertEqual(selection.crop_box(1000, 1500, 1344, 768), (0, 464, 1000, 571))

    def test_the_same_proportions_cut_nothing(self):
        self.assertEqual(selection.crop_box(1344, 768, 1344, 768), (0, 0, 1344, 768))
        self.assertEqual(selection.crop_box(64, 64, 32, 32), (0, 0, 64, 64))

    def test_an_exact_16_9_image_loses_only_a_sliver_because_1344_x_768_is_1_75(self):
        self.assertEqual(selection.crop_box(1920, 1080, 1344, 768), (15, 0, 1890, 1080))

    def test_the_box_has_the_targets_proportions_and_lies_inside(self):
        for sw, sh in ((1920, 1080), (1080, 1920), (777, 1001), (5000, 700), (33, 31)):
            for tw, th in ((1344, 768), (768, 1344), (1024, 1024), (1568, 672)):
                x, y, w, h = selection.crop_box(sw, sh, tw, th)
                self.assertTrue(0 <= x and 0 <= y and x + w <= sw and y + h <= sh, (sw, sh, tw, th))
                self.assertAlmostEqual(w / h, tw / th, delta=max(1.5 / min(w, h), 0.02), msg=(sw, sh, tw, th))
                self.assertTrue(w == sw or h == sh)  # the largest box: it touches both sides in one direction
                self.assertLessEqual(abs((sw - w) - 2 * x), 1)
                self.assertLessEqual(abs((sh - h) - 2 * y), 1)

    def test_the_share_that_is_cut(self):
        box = selection.crop_box(1920, 1080, 1000, 1000)
        self.assertAlmostEqual(selection.cropped_share(1920, 1080, box), 1 - 1080 * 1080 / (1920 * 1080))
        self.assertEqual(selection.cropped_share(100, 100, (0, 0, 100, 100)), 0)


class TestDescribe(unittest.TestCase):
    def test_text(self):
        text = selection.describe("16:9", "auto: the image is 1.78:1", (1920, 1080), (1344, 768), (0, 0, 1920, 1080), "")
        self.assertEqual(text, "16:9 (auto: the image is 1.78:1) | 1344x768 = 1.03 MP | from 1920x1080, 0% cropped")
        capped = selection.describe("1:1", "", None, (992, 992), None, "limited to MiniMax H3's canvas")
        self.assertEqual(capped, "1:1 | 992x992 = 0.98 MP\nlimited to MiniMax H3's canvas")


@unittest.skipUnless(HAS_TORCH, "torch is needed")
class TestNode(unittest.TestCase):
    def setUp(self):
        import torch

        self.torch = torch
        self.nodes = module("format_detector.nodes")
        self.node = self.nodes.FormatDetector()

    def gradient(self, height, width, batch=1, channels=3):
        """An image whose value is its own column / row, so a crop can be checked exactly."""
        cols = self.torch.linspace(0, 1, width).reshape(1, 1, width, 1).expand(batch, height, width, 1)
        rows = self.torch.linspace(0, 1, height).reshape(1, height, 1, 1).expand(batch, height, width, 1)
        planes = [cols, rows, cols * 0 + 0.5, cols * 0 + 1.0][:channels]
        return self.torch.cat(planes, dim=-1).clone()

    def test_auto_picks_the_format_and_fills_the_frame(self):
        width, height, image, aspect, ratio, info = self.node.detect("auto", 1.03, True, self.gradient(1080, 1920))
        self.assertEqual((width, height, aspect), (1344, 768, "16:9"))
        self.assertEqual(tuple(image.shape), (1, 768, 1344, 3))
        self.assertAlmostEqual(ratio, 16 / 9)
        self.assertIn("auto", info)
        self.assertIn("2% cropped", info)  # 1344 x 768 is 1.75:1, a hair narrower than 16:9

    def test_a_portrait_image_gets_a_portrait_format(self):
        width, height, image, aspect, _, _ = self.node.detect("auto", 1.03, True, self.gradient(1920, 1080))
        self.assertEqual((width, height, aspect), (768, 1344, "9:16"))
        self.assertEqual(tuple(image.shape), (1, 1344, 768, 3))

    def test_a_chosen_format_overrides_the_image(self):
        width, height, image, aspect, _, info = self.node.detect("1:1", 1.03, True, self.gradient(1080, 1920))
        self.assertEqual(aspect, "1:1")
        self.assertEqual(width, height)
        self.assertEqual(tuple(image.shape), (1, height, width, 3))
        self.assertIn("% cropped", info)

    def test_the_crop_is_centred_and_does_not_stretch(self):
        # a 300x100 gradient into a square: the middle 100x100 columns, scaled up, left to right still 1/3..2/3
        _, _, image, _, _, _ = self.node.detect("1:1", 0.1, False, self.gradient(100, 300))
        h, w = image.shape[1], image.shape[2]
        self.assertEqual(h, w)
        left, right = image[0, h // 2, 0, 0].item(), image[0, h // 2, -1, 0].item()
        self.assertAlmostEqual(left, 1 / 3, delta=0.02)
        self.assertAlmostEqual(right, 2 / 3, delta=0.02)
        self.assertAlmostEqual(image[0, 0, 0, 1].item(), 0.0, delta=0.02)  # the full height is kept
        self.assertAlmostEqual(image[0, -1, 0, 1].item(), 1.0, delta=0.02)

    def test_no_image_gives_the_sizes_and_nothing_else(self):
        width, height, image, aspect, ratio, info = self.node.detect("auto", 1.03, True)
        self.assertEqual((width, height, aspect), (1344, 768, "16:9"))
        self.assertIsNone(image)
        self.assertIn("no image", info)
        self.assertNotIn("cropped", info)
        self.assertAlmostEqual(ratio, 16 / 9)

    def test_custom_ratio(self):
        width, height, image, aspect, ratio, _ = self.node.detect("custom", 1.0, True, self.gradient(100, 100), "1.85")
        self.assertAlmostEqual(width / height, 1.85, delta=0.08)
        self.assertAlmostEqual(ratio, 1.85)
        self.assertEqual(aspect, "1.85:1")
        self.assertEqual(tuple(image.shape), (1, height, width, 3))

    def test_the_cap_and_its_note(self):
        width, height, _, _, _, info = self.node.detect("16:9", 4.0, True)
        self.assertEqual((width, height), (1344, 768))
        self.assertIn("limited to MiniMax H3's canvas", info)
        width, height, _, _, _, info = self.node.detect("16:9", 4.0, False)
        self.assertGreater(width * height, 3_500_000)
        self.assertNotIn("limited", info)

    def test_a_batch_is_fitted_frame_by_frame(self):
        _, _, image, _, _, _ = self.node.detect("auto", 0.25, False, self.gradient(60, 100, batch=3))
        self.assertEqual(image.shape[0], 3)
        self.assertEqual(image.shape[1] % 32, 0)

    def test_alpha_and_grey_survive(self):
        _, _, image, _, _, _ = self.node.detect("16:9", 0.25, False, self.gradient(40, 40, channels=4))
        self.assertEqual(image.shape[-1], 4)
        _, _, image, _, _, _ = self.node.detect("16:9", 0.25, False, self.torch.rand(1, 40, 40, 1))
        self.assertEqual(image.shape[-1], 1)

    def test_values_stay_in_range_and_the_input_is_untouched(self):
        source = self.torch.rand(1, 70, 90, 3)
        copy = source.clone()
        _, _, image, _, _, _ = self.node.detect("1:1", 1.0, False, source)
        self.assertGreaterEqual(image.min().item(), 0.0)
        self.assertLessEqual(image.max().item(), 1.0)
        self.assertTrue(self.torch.equal(source, copy))

    def test_an_image_that_already_has_the_size_is_passed_through_unchanged(self):
        source = self.torch.rand(1, 768, 1344, 3)
        _, _, image, _, _, _ = self.node.detect("16:9", 1.03, True, source)
        self.assertTrue(self.torch.equal(image, source))

    def test_a_single_frame_without_a_batch_axis(self):
        _, _, image, _, _, _ = self.node.detect("16:9", 0.25, False, self.torch.rand(40, 60, 3))
        self.assertEqual(image.ndim, 4)

    def test_errors_are_runtime_errors_that_say_what_is_wrong(self):
        for kwargs in ({"format": "custom", "custom_ratio": "nope"}, {"format": "16:9", "megapixels": 0}):
            args = {"format": "16:9", "megapixels": 1.0, **kwargs}
            with self.assertRaises(RuntimeError) as ctx:
                self.node.detect(**args)
            self.assertIn("Format Detector:", str(ctx.exception))

    def test_validation(self):
        validate = self.nodes.FormatDetector.VALIDATE_INPUTS
        self.assertTrue(validate())
        self.assertTrue(validate(format="custom", custom_ratio="16:10", megapixels=1.0))
        self.assertIn("ratio", validate(format="custom", custom_ratio="x"))
        self.assertTrue(validate(format="16:9", custom_ratio="x"))  # only checked when custom is chosen
        self.assertIn("megapixels", validate(megapixels=0))

    def test_schema(self):
        spec = self.nodes.FormatDetector.INPUT_TYPES()
        self.assertEqual(spec["required"]["format"][0][0], "auto")
        self.assertEqual(spec["required"]["megapixels"][1]["default"], 1.03)
        self.assertTrue(spec["required"]["limit_h3"][1]["default"])
        self.assertEqual(spec["optional"]["image"][0], "IMAGE")
        self.assertEqual(self.nodes.FormatDetector.RETURN_NAMES, ("width", "height", "image", "aspect", "ratio", "info"))
        self.assertEqual(self.nodes.FormatDetector.CATEGORY, "Bart's nodes/Image")


if __name__ == "__main__":
    unittest.main()
