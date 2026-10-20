import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

selection = module("smartload.selection")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_FILE = os.path.join(ROOT, "js", "smart_load_image.js")


class TestClampBox(unittest.TestCase):
    def test_zero_width_or_height_means_no_crop(self):
        for box in ((10, 10, 0, 50), (10, 10, 50, 0), (0, 0, 0, 0), (5, 5, -3, 10)):
            with self.subTest(box=box):
                self.assertEqual(selection.clamp_box(*box, 800, 600), (0, 0, 800, 600))

    def test_box_inside_is_untouched(self):
        self.assertEqual(selection.clamp_box(100, 50, 300, 200, 800, 600), (100, 50, 300, 200))

    def test_box_sticking_out_is_cut_at_the_edge(self):
        self.assertEqual(selection.clamp_box(700, 500, 300, 300, 800, 600), (700, 500, 100, 100))

    def test_origin_outside_is_pulled_in_and_keeps_at_least_one_pixel(self):
        self.assertEqual(selection.clamp_box(5000, 5000, 10, 10, 800, 600), (799, 599, 1, 1))
        self.assertEqual(selection.clamp_box(-20, -5, 100, 100, 800, 600), (0, 0, 100, 100))

    def test_crop_for_a_smaller_replacement_file_still_works(self):
        # a workflow saved for a 4000px photo, now pointing at a 500px one
        x, y, width, height = selection.clamp_box(3000, 2000, 800, 600, 500, 400)
        self.assertTrue(0 <= x < 500 and 0 <= y < 400 and width >= 1 and height >= 1)
        self.assertLessEqual(x + width, 500)
        self.assertLessEqual(y + height, 400)


class TestWidgetChoices(unittest.TestCase):
    def test_locks_and_snaps(self):
        self.assertEqual(selection.ASPECT_LOCKS[:2], ["free", "original"])
        for lock in selection.ASPECT_LOCKS[2:]:
            first, second = lock.split(":")
            self.assertTrue(first.isdigit() and second.isdigit(), lock)
        self.assertEqual(selection.SNAPS[0], 1)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestFrontendGeometry(unittest.TestCase):
    """The crop editor's drag math lives in the JS file; run it under node."""

    def test_geometry(self):
        with open(JS_FILE, encoding="utf-8") as handle:
            source = handle.read()
        start = source.index("const clamp =")
        end = source.index("app.registerExtension")
        script = (
            "const MIN_SIDE = 8;\n"
            "let failures = 0;\n"
            "const eq = (got, want, label) => { if (JSON.stringify(got) !== JSON.stringify(want)) "
            "{ failures++; console.log('FAIL', label, JSON.stringify(got), '!=', JSON.stringify(want)); } };\n"
            + source[start:end]
            + JS_TESTS
            + "\nif (failures) process.exit(1);\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "geometry.js")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(script)
            run = subprocess.run(["node", path], capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


JS_TESTS = r"""
const W = 1000, H = 600;
// move stays inside
eq(dragBox("move", {x:100,y:100,w:200,h:100}, {x:150,y:150}, {x:2000,y:-500}, null, W, H, 1), {x:800,y:0,w:200,h:100}, "move clamps to the image");
// free corner drag from se
eq(dragBox("se", {x:100,y:100,w:200,h:100}, {x:300,y:200}, {x:500,y:400}, null, W, H, 1), {x:100,y:100,w:400,h:300}, "se corner grows");
// nw drag crossing over flips
eq(dragBox("nw", {x:100,y:100,w:200,h:100}, {x:100,y:100}, {x:400,y:250}, null, W, H, 1), {x:300,y:200,w:100,h:50}, "nw drag past the opposite corner flips");
// edge e free
eq(dragBox("e", {x:100,y:100,w:200,h:100}, {x:300,y:150}, {x:700,y:555}, null, W, H, 1), {x:100,y:100,w:600,h:100}, "east edge only changes width");
// bounds
eq(dragBox("se", {x:100,y:100,w:200,h:100}, {x:300,y:200}, {x:5000,y:5000}, null, W, H, 1), {x:100,y:100,w:900,h:500}, "se is capped by the image edge");
// ratio lock 16:9 from a new box
const r = 16/9;
const nb = dragBox("new", {x:0,y:0,w:1000,h:600}, {x:100,y:100}, {x:420,y:200}, r, W, H, 1);
eq([nb.x, nb.y, Math.abs(nb.w/nb.h - r) < 0.02], [100, 100, true], "new box with 16:9 lock keeps the ratio");
// ratio + edge keeps centre
const eb = dragBox("e", {x:200,y:200,w:160,h:90}, {x:360,y:245}, {x:520,y:245}, r, W, H, 1);
eq([eb.w, eb.h, eb.x, Math.abs((eb.y + eb.h/2) - 245) <= 1], [320, 180, 200, true], "east edge with lock grows h around the centre");
// ratio at the image edge scales down instead of leaving
const cb = dragBox("se", {x:700,y:300,w:160,h:90}, {x:860,y:390}, {x:2000,y:2000}, r, W, H, 1);
eq([cb.x + cb.w <= W, cb.y + cb.h <= H, Math.abs(cb.w/cb.h - r) < 0.02], [true, true, true], "locked corner drag stays inside the image");
// snap 64
const sb = dragBox("se", {x:0,y:0,w:64,h:64}, {x:64,y:64}, {x:520,y:300}, null, W, H, 64);
eq([sb.w % 64, sb.h % 64, sb.w, sb.h], [0, 0, 512, 320], "snap 64 rounds sizes to the grid");
// snap never exceeds the room: image 1000 wide, box from x=900
const sb2 = dragBox("se", {x:900,y:0,w:64,h:64}, {x:964,y:64}, {x:1000,y:128}, null, W, H, 64);
eq([sb2.x + sb2.w <= W, sb2.w % 64], [true, 0], "snap near the edge floors to the room left");
// fitBox
eq(fitBox({x:0,y:0,w:1000,h:600}, {x:500,y:300}, 1, 1), {x:200,y:0,w:600,h:600}, "fit 1:1 into 1000x600");
eq(fitBox({x:0,y:0,w:1000,h:600}, {x:500,y:300}, 16/9, 64), {x:52,y:44,w:896,h:512}, "fit 16:9 with snap 64 picks the closest ratio on the grid");
eq(fitBox({x:0,y:0,w:1100,h:700}, {x:550,y:350}, 16/9, 64), {x:38,y:62,w:1024,h:576}, "fit 16:9 with snap 64 uses the exact 1024x576 when it fits");
eq(fitBox({x:0,y:0,w:1100,h:640}, {x:550,y:320}, 16/9, 64), {x:38,y:32,w:1024,h:576}, "fit 16:9 with snap 64 finds the exact 1024x576");
const pr = snapPair(16/9, 64, 960, 600, 700); eq([pr.w % 64, pr.h % 64], [0, 0], "snapPair returns grid multiples");
const lockedSnap = dragBox("se", {x:0,y:0,w:64,h:64}, {x:64,y:64}, {x:1000,y:560}, 16/9, 1100, 640, 64);
eq([lockedSnap.w % 64, lockedSnap.h % 64, Math.abs(lockedSnap.w/lockedSnap.h - 16/9) < 0.01], [0, 0, true], "locked drag with snap lands on an exact 16:9 grid pair when one exists");
eq(ratioOf("3:4", 10, 10), 0.75, "ratio 3:4");
eq(ratioOf("original", 400, 200), 2, "ratio original");
eq(ratioOf("free", 1, 1), null, "free");

"""


if __name__ == "__main__":
    unittest.main()
