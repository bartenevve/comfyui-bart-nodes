import importlib.util
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

HAS_DEPS = importlib.util.find_spec("PIL") is not None and importlib.util.find_spec("numpy") is not None


@unittest.skipUnless(HAS_DEPS, "Pillow and numpy are needed")
class TestImageLoad(unittest.TestCase):
    def setUp(self):
        import numpy as np
        from PIL import Image, ImageFile

        self.np = np
        self.Image = Image
        self.ImageFile = ImageFile
        self.imageload = module("imageload")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def noise(self, width, height, channels=3, seed=7):
        data = (self.np.random.default_rng(seed).random((height, width, channels)) * 255).astype(self.np.uint8)
        return self.Image.fromarray(data)

    # ---- damaged files
    def test_a_truncated_jpeg_still_loads(self):
        buffer = io.BytesIO()
        self.Image.effect_noise((400, 300), 60).convert("RGB").save(buffer, "JPEG", quality=90)
        with open(self.path("cut.jpg"), "wb") as handle:
            handle.write(buffer.getvalue()[: int(len(buffer.getvalue()) * 0.8)])
        rgb, mask = self.imageload.load_frames(self.path("cut.jpg"))
        self.assertEqual(rgb.shape, (1, 300, 400, 3))
        self.assertEqual(mask.shape, (1, 300, 400))

    def test_the_lenient_flag_is_restored_afterwards(self):
        before = self.ImageFile.LOAD_TRUNCATED_IMAGES
        buffer = io.BytesIO()
        self.Image.effect_noise((200, 200), 60).convert("RGB").save(buffer, "JPEG")
        with open(self.path("cut.jpg"), "wb") as handle:
            handle.write(buffer.getvalue()[:-500])
        self.imageload.load_frames(self.path("cut.jpg"))
        self.assertEqual(self.ImageFile.LOAD_TRUNCATED_IMAGES, before)

    def test_a_file_that_is_not_an_image_still_fails(self):
        with open(self.path("text.png"), "wb") as handle:
            handle.write(b"this is not an image")
        with self.assertRaises(Exception):
            self.imageload.load_frames(self.path("text.png"))

    def test_a_missing_file_is_reported_as_missing(self):
        with self.assertRaises(FileNotFoundError):
            self.imageload.load_frames(self.path("nope.png"))

    # ---- pixel handling
    def test_sixteen_bit_grayscale_is_scaled_not_clipped(self):
        ramp = self.np.tile(self.np.linspace(0, 65535, 256).astype(self.np.uint16), (8, 1))
        self.Image.fromarray(ramp).save(self.path("depth.png"))
        rgb, _ = self.imageload.load_frames(self.path("depth.png"))
        row = rgb[0, 0, :, 0]
        for x, expected in ((0, 0.0), (64, 0.25), (128, 0.5), (192, 0.75), (255, 1.0)):
            self.assertAlmostEqual(float(row[x]), expected, delta=0.01, msg=f"x={x}")

    def test_plain_eight_bit_images_pass_through_unchanged(self):
        self.noise(20, 10).save(self.path("a.png"))
        rgb, mask = self.imageload.load_frames(self.path("a.png"))
        expected = self.np.array(self.Image.open(self.path("a.png")).convert("RGB")).astype(self.np.float32) / 255.0
        self.assertTrue(self.np.array_equal(rgb[0], expected))
        self.assertEqual(float(mask.sum()), 0.0)

    def test_the_mask_is_one_minus_alpha(self):
        image = self.Image.new("RGBA", (4, 4), (255, 0, 0, 255))
        image.putpixel((1, 1), (255, 0, 0, 0))
        image.save(self.path("alpha.png"))
        _, mask = self.imageload.load_frames(self.path("alpha.png"))
        self.assertEqual(float(mask[0, 1, 1]), 1.0)
        self.assertEqual(float(mask[0, 0, 0]), 0.0)

    def test_palette_transparency_reaches_the_mask(self):
        image = self.noise(16, 16).convert("P", palette=self.Image.ADAPTIVE, colors=8)
        image.save(self.path("sticker.png"), transparency=0)
        _, mask = self.imageload.load_frames(self.path("sticker.png"))
        self.assertGreater(float(mask.sum()), 0.0)
        self.assertEqual(mask.shape, (1, 16, 16))

    def test_a_palette_image_without_transparency_has_an_empty_mask(self):
        self.noise(16, 16).convert("P", palette=self.Image.ADAPTIVE, colors=8).save(self.path("solid.png"))
        _, mask = self.imageload.load_frames(self.path("solid.png"))
        self.assertEqual(float(mask.sum()), 0.0)

    def test_exif_orientation_is_applied(self):
        image = self.Image.new("RGB", (60, 40))
        exif = image.getexif()
        exif[0x0112] = 6
        image.save(self.path("turned.jpg"), exif=exif)
        rgb, mask = self.imageload.load_frames(self.path("turned.jpg"))
        self.assertEqual(rgb.shape, (1, 60, 40, 3))
        self.assertEqual(mask.shape, (1, 60, 40))

    # ---- frames and crop
    def test_every_frame_of_an_animation_is_loaded(self):
        # different frames: Pillow merges identical neighbours into one frame
        frames = [self.noise(30, 20, seed=seed).convert("P", palette=self.Image.ADAPTIVE) for seed in (1, 2, 3)]
        frames[0].save(self.path("anim.gif"), save_all=True, append_images=frames[1:], duration=50)
        rgb, mask = self.imageload.load_frames(self.path("anim.gif"))
        self.assertEqual(rgb.shape, (3, 20, 30, 3))
        self.assertEqual(mask.shape, (3, 20, 30))

    def test_the_box_callback_crops_every_frame_and_sees_the_frame_size(self):
        self.noise(50, 40).save(self.path("big.png"))
        seen = []

        def box(width, height):
            seen.append((width, height))
            return 10, 5, 20, 15

        rgb, mask = self.imageload.load_frames(self.path("big.png"), box=box)
        self.assertEqual(seen, [(50, 40)])
        self.assertEqual(rgb.shape, (1, 15, 20, 3))
        self.assertEqual(mask.shape, (1, 15, 20))
        original = self.np.array(self.Image.open(self.path("big.png")).convert("RGB")).astype(self.np.float32) / 255.0
        self.assertTrue(self.np.array_equal(rgb[0], original[5:20, 10:30]))


if __name__ == "__main__":
    unittest.main()
