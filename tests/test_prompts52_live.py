"""Opt-in check that every generator on the live site still runs.

Skipped by default - it makes ~40 requests to 52prompts.com and its CDN. Run it
after the site changes something, or before a release:

    PROMPTS52_LIVE=1 python -m unittest tests.test_prompts52_live

It asserts only that each generator produces non-empty text; the prompt bodies
are the site's content and are never stored here.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

catalog = module("prompts52.catalog")
runner = module("prompts52.runner")

SAMPLE_VALUES = {
    "input_1": "Alice",
    "input_2": "Bob",
    "input_3": "Cleo",
    "choice_list": "Alice\nBob\nCleo\nDan",
}


@unittest.skipUnless(os.environ.get("PROMPTS52_LIVE"), "set PROMPTS52_LIVE=1 to hit the live site")
class TestLiveGenerators(unittest.TestCase):
    def test_every_generator_produces_text(self):
        for generator in catalog.GENERATORS:
            with self.subTest(generator=generator.label):
                values = dict(SAMPLE_VALUES)
                # the count fields want a number, not a name
                for item in generator.fields:
                    if item.default.isdigit():
                        values[item.widget] = item.default
                text = runner.generate(generator.label, values, seed=12345)
                self.assertTrue(text.strip(), generator.label)
                self.assertNotIn("<", text, generator.label)

    def test_a_generator_is_reproducible_across_calls(self):
        label = catalog.DEFAULT_GENERATOR
        self.assertEqual(
            runner.generate(label, {}, seed=7),
            runner.generate(label, {}, seed=7),
        )


if __name__ == "__main__":
    unittest.main()
