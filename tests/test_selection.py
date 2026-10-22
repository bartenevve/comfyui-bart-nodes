"""Pure-logic tests for selection.py - no ComfyUI/torch/numpy/PIL required.

Run with: python3 -m unittest discover -s tests
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from selection import list_images, resolve_filenames  # noqa: E402


class ResolveFilenamesTests(unittest.TestCase):
    def setUp(self):
        self.files = ["a.png", "b.png", "c.png"]

    def test_manual_valid_filename(self):
        chosen, next_ = resolve_filenames(self.files, False, False, "b.png")
        self.assertEqual(chosen, "b.png")
        self.assertEqual(next_, "b.png")

    def test_manual_missing_filename_falls_back_to_first(self):
        chosen, _ = resolve_filenames(self.files, False, False, "deleted.png")
        self.assertEqual(chosen, "a.png")

    def test_manual_empty_filename_falls_back_to_first(self):
        chosen, _ = resolve_filenames(self.files, False, False, "")
        self.assertEqual(chosen, "a.png")

    def test_randomize_returns_value_from_files(self):
        chosen, next_ = resolve_filenames(self.files, True, False, "")
        self.assertIn(chosen, self.files)
        self.assertEqual(chosen, next_)

    def test_sequential_advances_from_current_widget_value_on_first_call(self):
        state = {}
        chosen, next_ = resolve_filenames(self.files, False, True, "b.png", unique_id="node1", state=state)
        self.assertEqual(chosen, "b.png")
        self.assertEqual(next_, "c.png")

    def test_sequential_wraps_around_at_end(self):
        state = {}
        chosen, next_ = resolve_filenames(self.files, False, True, "c.png", unique_id="node1", state=state)
        self.assertEqual(chosen, "c.png")
        self.assertEqual(next_, "a.png")

    def test_sequential_uses_in_memory_state_over_stale_input_on_repeat_calls(self):
        # simulates two prompts queued back-to-back with the same stale
        # `filename` snapshot, before the frontend had a chance to push the
        # advanced value back into the widget between them
        state = {}
        first = resolve_filenames(self.files, False, True, "a.png", unique_id="node1", state=state)
        second = resolve_filenames(self.files, False, True, "a.png", unique_id="node1", state=state)
        self.assertEqual(first[0], "a.png")
        self.assertEqual(second[0], "b.png")  # not "a.png" again, despite identical stale input

    def test_sequential_re_picking_the_file_that_just_ran_repeats_it(self):
        # run 1 starts at a.png and the frontend moves the widget on to b.png; the user then picks
        # a.png again by hand (the frontend marks that with a fresh edit_serial) and expects a.png
        state = {}
        first = resolve_filenames(self.files, False, True, "a.png", unique_id="n", state=state, edit_serial="s1")
        self.assertEqual(first, ("a.png", "b.png"))
        again = resolve_filenames(self.files, False, True, "a.png", unique_id="n", state=state, edit_serial="s2")
        self.assertEqual(again[0], "a.png")

    def test_sequential_with_a_serial_ignores_the_widget_until_the_user_edits_it(self):
        # a batch of 3 queued from one frontend: the UI synced run 1's advance into the widget
        # before run 3 was serialized, so the widget values are c.png, c.png, a.png - no equality
        # test can tell that a.png is stale, but the unchanged serial can
        state = {}
        seen = [
            resolve_filenames(self.files, False, True, widget, unique_id="n", state=state, edit_serial="s1")[0]
            for widget in ("c.png", "c.png", "a.png")
        ]
        self.assertEqual(seen, ["c.png", "a.png", "b.png"])

    def test_sequential_first_run_with_a_serial_uses_the_widget(self):
        chosen, nxt = resolve_filenames(self.files, False, True, "b.png", unique_id="n", state={}, edit_serial="s1")
        self.assertEqual((chosen, nxt), ("b.png", "c.png"))

    def test_sequential_batch_with_one_edit_serial_still_advances(self):
        # a batch queued after a hand pick: every item carries the same widget value AND the same serial
        state = {}
        seen = [
            resolve_filenames(self.files, False, True, "b.png", unique_id="n", state=state, edit_serial="s7")[0]
            for _ in range(3)
        ]
        self.assertEqual(seen, ["b.png", "c.png", "a.png"])

    def test_sequential_without_a_serial_keeps_the_value_based_rule(self):
        # an API caller never sets edit_serial: identical input twice is a queued duplicate
        state = {}
        first = resolve_filenames(self.files, False, True, "a.png", unique_id="n", state=state)
        second = resolve_filenames(self.files, False, True, "a.png", unique_id="n", state=state)
        self.assertEqual((first[0], second[0]), ("a.png", "b.png"))

    def test_sequential_honors_a_widget_that_moved_since_the_last_run(self):
        # sequential -> user picks another file by hand -> sequential again:
        # the pointer must not override what the widget now shows
        state = {}
        resolve_filenames(self.files, False, True, "a.png", unique_id="n", state=state)  # pointer -> b
        chosen, next_ = resolve_filenames(self.files, False, True, "c.png", unique_id="n", state=state)
        self.assertEqual((chosen, next_), ("c.png", "a.png"))

    def test_sequential_follows_frontend_sync_between_runs(self):
        # normal one-at-a-time use: after each run the frontend writes the
        # advance into the widget, so the next run arrives with it
        state = {}
        seen = []
        widget = "a.png"
        for _ in range(4):
            chosen, widget = resolve_filenames(self.files, False, True, widget, unique_id="n", state=state)
            seen.append(chosen)
        self.assertEqual(seen, ["a.png", "b.png", "c.png", "a.png"])

    def test_sequential_batch_of_queued_runs_with_one_snapshot_still_advances(self):
        state = {}
        seen = [
            resolve_filenames(self.files, False, True, "b.png", unique_id="n", state=state)[0]
            for _ in range(4)
        ]
        self.assertEqual(seen, ["b.png", "c.png", "a.png", "b.png"])

    def test_sequential_repeated_blank_filename_keeps_advancing(self):
        # API-driven use: the widget is never synced, filename stays empty
        state = {}
        seen = [resolve_filenames(self.files, False, True, "", unique_id="n", state=state)[0] for _ in range(4)]
        self.assertEqual(seen, ["a.png", "b.png", "c.png", "a.png"])

    def test_sequential_falls_back_to_filename_when_pointer_is_stale(self):
        state = {("node1", None): ("deleted.png", "x.png", "")}
        chosen, _ = resolve_filenames(self.files, False, True, "b.png", unique_id="node1", state=state)
        self.assertEqual(chosen, "b.png")

    def test_sequential_falls_back_to_first_file_when_pointer_and_input_both_stale(self):
        state = {("node1", None): ("deleted.png", "also_deleted.png", "")}
        chosen, _ = resolve_filenames(self.files, False, True, "also_deleted.png", unique_id="node1", state=state)
        self.assertEqual(chosen, "a.png")

    def test_sequential_different_unique_ids_are_independent(self):
        state = {}
        resolve_filenames(self.files, False, True, "a.png", unique_id="node1", state=state)
        chosen, _ = resolve_filenames(self.files, False, True, "a.png", unique_id="node2", state=state)
        self.assertEqual(chosen, "a.png")


class ListImagesTests(unittest.TestCase):
    def test_filters_extensions_and_sorts_case_insensitively_recursively(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ["B.png", "a.jpg", "note.txt", "c.PNG"]:
                open(os.path.join(d, name), "w").close()
            os.makedirs(os.path.join(d, "sub"))
            open(os.path.join(d, "sub", "d.webp"), "w").close()

            result = list_images(d)
            self.assertEqual(result, ["a.jpg", "B.png", "c.PNG", os.path.join("sub", "d.webp")])


if __name__ == "__main__":
    unittest.main()
