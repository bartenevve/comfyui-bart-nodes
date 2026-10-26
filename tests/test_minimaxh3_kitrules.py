"""Rules of the bundled h3kit that the docs and the universal prompt promise: shot plan timing and the
placeholder check. (The kit itself is third-party code dropped into the pack: these pin its behaviour.)"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

h3kit = module("minimaxh3prompt.h3kit")


class TestShotPlan(unittest.TestCase):
    def test_up_to_six_seconds_is_one_shot(self):
        self.assertEqual(h3kit.plan_shots(6), [(0, 6)])

    def test_seven_to_nine_seconds_cut_at_four(self):
        for seconds in (7, 8, 9):
            self.assertEqual(h3kit.plan_shots(seconds), [(0, 4), (4, seconds)])

    def test_ten_to_twelve_seconds_cut_at_five(self):
        for seconds in (10, 11, 12):
            self.assertEqual(h3kit.plan_shots(seconds), [(0, 5), (5, seconds)])

    def test_thirteen_to_fifteen_seconds_are_three_shots_by_thirds(self):
        for seconds in (13, 14, 15):
            plan = h3kit.plan_shots(seconds)
            self.assertEqual(len(plan), 3)
            self.assertEqual((plan[0][0], plan[-1][1]), (0, seconds))
            self.assertTrue(all(end - start >= 3 for start, end in plan))

    def test_a_forced_two_shot_plan_cuts_at_five_over_nine_seconds(self):
        self.assertEqual(h3kit.plan_shots(15, "T2VA", 2), [(0, 5), (5, 15)])

    def test_the_plan_is_contiguous(self):
        for seconds in range(4, 16):
            plan = h3kit.plan_shots(seconds)
            self.assertTrue(all(a[1] == b[0] for a, b in zip(plan, plan[1:])), seconds)


class TestPlaceholderCheck(unittest.TestCase):
    def errors(self, camera_target):
        req = h3kit.make_request(request="a cat", duration=6)
        text = (
            "integrated_multimodal_description: [Shot 1] Live-action, cinematic, soft light, an eye-level medium shot "
            "frames a grey cat on the left third of the frame, facing right. First it sits, then it yawns. The camera "
            f"pushes in with small amplitude at slow speed {camera_target}. By the end of the shot the cat fills the "
            "left half of the frame.\n\noverall_soundscape: Soft purring.\n\nnon_diegetic_music: None."
        )
        return [e for e in h3kit.validate(text, req) if "placeholder" in e]

    def test_a_leftover_x_target_is_reported(self):
        self.assertTrue(self.errors("toward X"))
        self.assertTrue(self.errors("past X"))

    def test_a_real_target_is_fine(self):
        self.assertEqual(self.errors("toward its face"), [])


if __name__ == "__main__":
    unittest.main()
