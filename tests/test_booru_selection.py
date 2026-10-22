import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

_selection = module("booru.selection")
resolve_index = _selection.resolve_index
snapshot_increment = _selection.snapshot_increment
restore_increment = _selection.restore_increment


class FixedRng:
    def __init__(self, value):
        self.value = value
        self.calls = []

    def randrange(self, total):
        self.calls.append(total)
        return self.value


class TestIncrementReconcilesWithWidget(unittest.TestCase):
    def test_widget_that_moved_since_the_last_run_wins(self):
        state = {}
        resolve_index(10, False, True, 2, unique_id="n", state=state)  # pointer -> 3
        self.assertEqual(resolve_index(10, False, True, 7, unique_id="n", state=state), (7, 8))

    def test_frontend_sync_between_runs_walks_the_list(self):
        state = {}
        seen, widget = [], 2
        for _ in range(4):
            chosen, widget = resolve_index(4, False, True, widget, unique_id="n", state=state)
            seen.append(chosen)
        self.assertEqual(seen, [2, 3, 0, 1])


class TestEditSerial(unittest.TestCase):
    def test_typing_back_the_position_that_just_ran_repeats_it(self):
        state = {}
        first = resolve_index(10, False, True, 5, unique_id="n", state=state, edit_serial="s1")
        self.assertEqual(first, (5, 6))  # the frontend now moves the widget to 6
        again = resolve_index(10, False, True, 5, unique_id="n", state=state, edit_serial="s2")
        self.assertEqual(again[0], 5)

    def test_with_a_serial_the_widget_is_ignored_until_the_user_edits_it(self):
        # three runs of one queued batch whose later items were serialized after the UI had synced
        # the earlier runs' advances: widget 5, 5, 6 (not a stale copy of any single value)
        state = {}
        seen = [resolve_index(10, False, True, widget, unique_id="n", state=state, edit_serial="s1")[0] for widget in (5, 5, 6)]
        self.assertEqual(seen, [5, 6, 7])

    def test_a_batch_queued_after_a_hand_edit_still_advances(self):
        state = {}
        seen = [resolve_index(10, False, True, 5, unique_id="n", state=state, edit_serial="s9")[0] for _ in range(3)]
        self.assertEqual(seen, [5, 6, 7])

    def test_without_a_serial_identical_input_is_a_queued_duplicate(self):
        state = {}
        seen = [resolve_index(10, False, True, 5, unique_id="n", state=state)[0] for _ in range(3)]
        self.assertEqual(seen, [5, 6, 7])


class TestRollback(unittest.TestCase):
    def test_snapshot_and_restore_put_the_pointer_back(self):
        state = {}
        resolve_index(10, False, True, 2, unique_id="n", search_key="k", state=state)  # pointer -> 3
        before = snapshot_increment("n", "k", state=state)
        resolve_index(10, False, True, 2, unique_id="n", search_key="k", state=state)  # pointer -> 4
        restore_increment("n", "k", before, state=state)
        self.assertEqual(resolve_index(10, False, True, 2, unique_id="n", search_key="k", state=state)[0], 3)

    def test_restoring_nothing_forgets_the_entry(self):
        state = {}
        before = snapshot_increment("n", "k", state=state)
        self.assertIsNone(before)
        resolve_index(10, False, True, 2, unique_id="n", search_key="k", state=state)
        restore_increment("n", "k", before, state=state)
        self.assertEqual(state, {})


class TestResolveIndex(unittest.TestCase):
    def test_empty_result_list_raises(self):
        with self.assertRaises(ValueError):
            resolve_index(0, False, False, 0, state={})

    def test_fixed_index_is_returned_as_is(self):
        self.assertEqual(resolve_index(100, False, False, 7, state={}), (7, 7))

    def test_out_of_range_index_falls_back_to_zero(self):
        self.assertEqual(resolve_index(5, False, False, 99, state={}), (0, 0))
        self.assertEqual(resolve_index(5, False, False, -3, state={}), (0, 0))

    def test_random_uses_full_range_and_does_not_advance(self):
        rng = FixedRng(3)
        self.assertEqual(resolve_index(10, True, False, 5, state={}, rng=rng), (3, 3))
        self.assertEqual(rng.calls, [10])

    def test_increment_seeds_from_index_then_advances(self):
        state = {}
        self.assertEqual(resolve_index(4, False, True, 2, unique_id="1", state=state), (2, 3))
        self.assertEqual(resolve_index(4, False, True, 2, unique_id="1", state=state), (3, 0))
        self.assertEqual(resolve_index(4, False, True, 2, unique_id="1", state=state), (0, 1))

    def test_increment_ignores_stale_widget_index_once_seeded(self):
        # the widget value is snapshotted at queue time, so a batch of runs all
        # pass the same index - the pointer must win, or they'd repeat
        state = {}
        first = resolve_index(3, False, True, 0, unique_id="n", state=state)
        second = resolve_index(3, False, True, 0, unique_id="n", state=state)
        self.assertEqual((first, second), ((0, 1), (1, 2)))

    def test_increment_pointers_are_isolated_per_node_and_search(self):
        state = {}
        resolve_index(10, False, True, 0, unique_id="a", search_key="gelbooru cat", state=state)
        resolve_index(10, False, True, 0, unique_id="a", search_key="gelbooru cat", state=state)
        other_node = resolve_index(10, False, True, 0, unique_id="b", search_key="gelbooru cat", state=state)
        other_tags = resolve_index(10, False, True, 0, unique_id="a", search_key="gelbooru dog", state=state)
        self.assertEqual(other_node, (0, 1))
        self.assertEqual(other_tags, (0, 1))

    def test_increment_pointer_past_shrunken_total_resets(self):
        state = {(None, None): (99, 0, "")}
        self.assertEqual(resolve_index(5, False, True, 0, state=state), (0, 1))

    def test_random_takes_precedence_over_increment(self):
        # both-on is rejected by VALIDATE_INPUTS, but a hand-edited workflow
        # could still reach here - random must not corrupt the pointer
        state = {}
        self.assertEqual(resolve_index(10, True, True, 0, state=state, rng=FixedRng(4)), (4, 4))
        self.assertEqual(state, {})

    def test_random_stays_in_range_over_many_draws(self):
        for _ in range(200):
            chosen, nxt = resolve_index(7, True, False, 0, state={}, rng=random)
            self.assertEqual(chosen, nxt)
            self.assertTrue(0 <= chosen < 7)


if __name__ == "__main__":
    unittest.main()
