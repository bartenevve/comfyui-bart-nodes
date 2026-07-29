import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

resolve_index = module("booru.selection").resolve_index


class FixedRng:
    def __init__(self, value):
        self.value = value
        self.calls = []

    def randrange(self, total):
        self.calls.append(total)
        return self.value


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
        state = {(None, None): 99}
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
