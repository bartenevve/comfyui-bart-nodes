import importlib.util
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

HAS_PIL = importlib.util.find_spec("PIL") is not None


@unittest.skipUnless(HAS_PIL, "Pillow is not installed")
class TestMakeThumb(unittest.TestCase):
    def setUp(self):
        from PIL import Image

        self.Image = Image
        self.thumbs = module("imagepicker.thumbs")
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def path(self, name):
        return os.path.join(self.dir, name)

    def litter(self):
        return [name for name in os.listdir(self.dir) if name.endswith(".part")]

    def test_shrinks_to_the_bucket_and_keeps_the_aspect(self):
        self.Image.new("RGB", (1000, 500), (200, 30, 30)).save(self.path("a.png"))
        self.thumbs.make_thumb(self.path("a.png"), self.path("a.webp"), 256)
        with self.Image.open(self.path("a.webp")) as thumb:
            self.assertEqual(thumb.format, "WEBP")
            self.assertEqual(thumb.size, (256, 128))

    def test_small_images_are_not_enlarged(self):
        self.Image.new("RGB", (40, 30)).save(self.path("s.png"))
        self.thumbs.make_thumb(self.path("s.png"), self.path("s.webp"), 256)
        with self.Image.open(self.path("s.webp")) as thumb:
            self.assertEqual(thumb.size, (40, 30))

    def test_alpha_survives(self):
        self.Image.new("RGBA", (64, 64), (255, 0, 0, 90)).save(self.path("t.png"))
        self.thumbs.make_thumb(self.path("t.png"), self.path("t.webp"), 128)
        with self.Image.open(self.path("t.webp")) as thumb:
            self.assertIn("A", thumb.getbands())
            self.assertLess(thumb.getpixel((10, 10))[3], 255)

    def test_exif_rotation_is_applied(self):
        image = self.Image.new("RGB", (60, 40), (0, 0, 255))
        exif = image.getexif()
        exif[0x0112] = 6  # shown rotated by 90 degrees: 40 wide, 60 tall
        image.save(self.path("r.jpg"), exif=exif)
        self.thumbs.make_thumb(self.path("r.jpg"), self.path("r.webp"), 256)
        with self.Image.open(self.path("r.webp")) as thumb:
            self.assertEqual(thumb.size, (40, 60))

    def test_no_temporary_files_are_left_behind(self):
        self.Image.new("RGB", (50, 50)).save(self.path("ok.png"))
        self.thumbs.make_thumb(self.path("ok.png"), self.path("ok.webp"), 128)
        self.assertEqual(self.litter(), [])

    def test_a_corrupt_file_raises_and_leaves_nothing_behind(self):
        with open(self.path("bad.png"), "wb") as handle:
            handle.write(b"definitely not a png")
        with self.assertRaises(Exception):
            self.thumbs.make_thumb(self.path("bad.png"), self.path("bad.webp"), 128)
        self.assertEqual(self.litter(), [])
        self.assertFalse(os.path.exists(self.path("bad.webp")))

    def test_concurrent_requests_for_the_same_thumbnail_do_not_collide(self):
        # two tabs, or a reload while the first request is still encoding: all asking for one file
        self.Image.effect_noise((2400, 1600), 80).convert("RGB").save(self.path("big.png"))
        failures = []

        def worker(target):
            try:
                self.thumbs.make_thumb(self.path("big.png"), target, 256)
            except Exception as exc:  # noqa: BLE001 - the test reports whatever escapes
                failures.append(repr(exc))

        for round_number in range(6):
            target = self.path(f"shared{round_number}.webp")
            threads = [threading.Thread(target=worker, args=(target,)) for _ in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            with self.Image.open(target) as thumb:
                thumb.load()  # a corrupt or truncated file would raise here
        self.assertEqual(failures, [])
        self.assertEqual(self.litter(), [])


if __name__ == "__main__":
    unittest.main()
