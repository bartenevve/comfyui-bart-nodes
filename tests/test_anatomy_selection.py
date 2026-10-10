import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

sel = module("anatomy.selection")


def verdict_json(**checks):
    return json.dumps({"checks": {k: v for k, v in checks.items()}})


class TestSelectedKeys(unittest.TestCase):
    def test_keeps_report_order_not_set_order(self):
        keys = sel.selected_keys({"smeared_limbs", "extra_limbs"})
        self.assertEqual(keys, ["extra_limbs", "smeared_limbs"])

    def test_custom_appended_only_when_non_blank(self):
        self.assertEqual(sel.selected_keys({"bad_fingers"}, "  "), ["bad_fingers"])
        self.assertEqual(sel.selected_keys({"bad_fingers"}, "wrong shadow"), ["bad_fingers", "custom"])

    def test_nothing_selected_is_empty(self):
        self.assertEqual(sel.selected_keys(set()), [])


class TestBuildPrompt(unittest.TestCase):
    def test_lists_only_requested_checks(self):
        prompt = sel.build_prompt(["bad_fingers"])
        self.assertIn('"bad_fingers"', prompt)
        self.assertNotIn('"extra_limbs"', prompt)

    def test_custom_criterion_text_is_used(self):
        prompt = sel.build_prompt(["custom"], "three nipples")
        self.assertIn("three nipples", prompt)


class TestParseVerdict(unittest.TestCase):
    def test_parses_nested_checks(self):
        text = verdict_json(bad_fingers={"found": True, "confidence": 0.9, "note": "6 fingers"})
        verdict = sel.parse_verdict(text, ["bad_fingers"])
        self.assertEqual(verdict["bad_fingers"], {"found": True, "confidence": 0.9, "note": "6 fingers"})

    def test_accepts_top_level_checks_and_code_fences(self):
        text = '```json\n{"bad_fingers": {"found": false, "confidence": 0.1}}\n```'
        verdict = sel.parse_verdict(text, ["bad_fingers"])
        self.assertFalse(verdict["bad_fingers"]["found"])

    def test_accepts_bare_boolean_entries(self):
        verdict = sel.parse_verdict('{"checks": {"bad_fingers": true}}', ["bad_fingers"])
        self.assertTrue(verdict["bad_fingers"]["found"])
        self.assertEqual(verdict["bad_fingers"]["confidence"], 1.0)

    def test_found_without_confidence_counts_as_fully_confident(self):
        verdict = sel.parse_verdict(verdict_json(extra_limbs={"found": "yes"}), ["extra_limbs"])
        self.assertEqual(verdict["extra_limbs"]["confidence"], 1.0)

    def test_confidence_is_clamped(self):
        verdict = sel.parse_verdict(verdict_json(extra_limbs={"found": True, "confidence": 7}), ["extra_limbs"])
        self.assertEqual(verdict["extra_limbs"]["confidence"], 1.0)

    def test_check_left_out_counts_as_not_found(self):
        text = verdict_json(extra_limbs={"found": False, "confidence": 0.0})
        verdict = sel.parse_verdict(text, ["extra_limbs", "bad_fingers"])
        self.assertFalse(verdict["bad_fingers"]["found"])
        self.assertEqual(verdict["bad_fingers"]["note"], "not reported")

    def test_answer_mentioning_no_requested_check_is_rejected(self):
        with self.assertRaises(sel.VerdictError):
            sel.parse_verdict('{"answer": "looks fine"}', ["extra_limbs"])

    def test_non_json_is_rejected(self):
        with self.assertRaises(sel.VerdictError):
            sel.parse_verdict("sorry, I cannot help with that", ["extra_limbs"])

    def test_broken_json_is_rejected(self):
        with self.assertRaises(sel.VerdictError):
            sel.parse_verdict('{"checks": {"extra_limbs": ', ["extra_limbs"])


class TestDecide(unittest.TestCase):
    def verdict(self, found, confidence):
        return {"bad_fingers": {"found": found, "confidence": confidence, "note": ""}}

    def test_found_at_threshold_fails(self):
        self.assertEqual(sel.decide(self.verdict(True, 0.6), 0.6), (False, ["bad_fingers"]))

    def test_found_below_threshold_passes(self):
        self.assertEqual(sel.decide(self.verdict(True, 0.59), 0.6), (True, []))

    def test_not_found_passes_even_with_high_confidence(self):
        self.assertEqual(sel.decide(self.verdict(False, 0.99), 0.1), (True, []))

    def test_any_single_defect_is_enough(self):
        verdict = {
            "a": {"found": False, "confidence": 0.9, "note": ""},
            "b": {"found": True, "confidence": 0.8, "note": ""},
        }
        self.assertEqual(sel.decide(verdict, 0.5), (False, ["b"]))


class TestSplitAndReport(unittest.TestCase):
    def test_split_indices(self):
        self.assertEqual(sel.split_indices([True, False, True, False]), ([0, 2], [1, 3]))

    def test_split_all_passed_leaves_failed_empty(self):
        self.assertEqual(sel.split_indices([True, True]), ([0, 1], []))

    def test_indices_string(self):
        self.assertEqual(sel.indices_string([0, 3, 5]), "0,3,5")
        self.assertEqual(sel.indices_string([]), "")

    def test_report_lines(self):
        results = [
            {"index": 0, "passed": True, "failed_checks": [], "checks": {}},
            {
                "index": 1,
                "passed": False,
                "failed_checks": ["bad_fingers"],
                "checks": {"bad_fingers": {"found": True, "confidence": 0.85, "note": "6 fingers"}},
            },
        ]
        self.assertEqual(sel.format_report(results), "#0 PASS\n#1 FAIL bad_fingers (0.85): 6 fingers")
        self.assertEqual(json.loads(sel.report_json(results))[1]["failed_checks"], ["bad_fingers"])


if __name__ == "__main__":
    unittest.main()
