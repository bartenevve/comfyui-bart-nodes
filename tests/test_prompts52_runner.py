import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

catalog = module("prompts52.catalog")
runner = module("prompts52.runner")

# A stand-in for a real generator script, in the same shape the site's use.
FAKE_SCRIPT = """
      function generateThings()
      {
<!-------------- Words --------------->
var myWords = ['first thing', 'second thing', 'third thing'];
var randomWord = myWords[Math.floor(Math.random()*myWords.length)]
var who = document.getElementById("Input1").value
if(who.length == 0)
who = 'Someone'
document.getElementById("promptDisplay").innerHTML = "<b>Who:</b> " + who + "<br><i>" + randomWord + "</i>";
      }
"""


class TestCatalog(unittest.TestCase):
    def test_labels_are_unique_and_lookupable(self):
        labels = catalog.GENERATOR_LABELS
        self.assertEqual(len(labels), len(set(labels)))
        for label in labels:
            self.assertIs(catalog.get_generator(label), catalog._BY_LABEL[label])

    def test_slugs_are_unique(self):
        slugs = [generator.slug for generator in catalog.GENERATORS]
        self.assertEqual(len(slugs), len(set(slugs)))

    def test_default_is_a_real_label(self):
        self.assertIn(catalog.DEFAULT_GENERATOR, catalog.GENERATOR_LABELS)

    def test_fields_only_use_widgets_the_node_declares(self):
        for generator in catalog.GENERATORS:
            widgets = [item.widget for item in generator.fields]
            self.assertEqual(len(widgets), len(set(widgets)), generator.label)
            for widget in widgets:
                self.assertIn(widget, catalog.WIDGET_NAMES, generator.label)

    def test_selected_if_blank_points_at_a_field_the_generator_has(self):
        for generator in catalog.GENERATORS:
            dom_ids = {item.dom_id for item in generator.fields}
            for paired in generator.selected_if_blank.values():
                self.assertIn(paired, dom_ids, generator.label)

    def test_unknown_label_raises(self):
        with self.assertRaises(KeyError):
            catalog.get_generator("Not A Generator")

    def test_describe_is_json_friendly(self):
        described = catalog.describe(catalog.get_generator("Scenarios - Two Person"))
        self.assertEqual([field["widget"] for field in described["fields"]], ["input_1", "input_2"])
        self.assertTrue(described["page_url"].endswith("/random-scenario-generator/"))


class TestFindScriptUrl(unittest.TestCase):
    def test_finds_the_cdn_script(self):
        page = (
            '<script src="https://52prompts.com/wp-includes/js/jquery.min.js?ver=3.7.1"></script>'
            '<script src="https://res.cloudinary.com/dqmdb7fgg/raw/upload/v1/gens/demo_ab12cd.js"></script>'
        )
        self.assertEqual(
            runner.find_script_url(page),
            "https://res.cloudinary.com/dqmdb7fgg/raw/upload/v1/gens/demo_ab12cd.js",
        )

    def test_a_page_without_one_is_an_error(self):
        with self.assertRaises(runner.GeneratorError):
            runner.find_script_url("<html><body>no generator here</body></html>")

    def test_other_hosts_are_not_accepted(self):
        # the URL comes out of fetched HTML, so it stays pinned to the CDN
        with self.assertRaises(runner.GeneratorError):
            runner.find_script_url('<script src="https://example.com/evil.js"></script>')


class TestHtmlToText(unittest.TestCase):
    def test_breaks_become_newlines_and_tags_are_dropped(self):
        self.assertEqual(
            runner.html_to_text("<b>Sun: </b> Cancer<br> <b>Moon: </b>Taurus"),
            "Sun: Cancer\nMoon: Taurus",
        )

    def test_entities_are_unescaped(self):
        self.assertEqual(runner.html_to_text("Tom &amp; Jerry&#39;s"), "Tom & Jerry's")

    def test_whitespace_is_collapsed_per_line(self):
        self.assertEqual(runner.html_to_text("  a   b  <br>  c  "), "a b\nc")


class TestBuildDocumentState(unittest.TestCase):
    def test_blank_optional_field_falls_back_to_its_default(self):
        generator = catalog.get_generator("Objects")
        values, selected = runner.build_document_state(generator, {"input_1": ""})
        self.assertEqual(values, {"Input1": "1"})
        self.assertEqual(selected, set())

    def test_blank_required_field_is_an_error(self):
        generator = catalog.get_generator("Scenarios - Cast of Characters")
        with self.assertRaises(runner.GeneratorError):
            runner.build_document_state(generator, {"choice_list": "   "})

    def test_multiline_field_keeps_its_inner_newlines(self):
        generator = catalog.get_generator("Scenarios - Cast of Characters")
        values, _ = runner.build_document_state(generator, {"choice_list": "\nAlice\nBob\n"})
        self.assertEqual(values["choicelist"], "Alice\nBob")

    def test_selected_id_is_set_only_while_the_paired_field_is_blank(self):
        generator = catalog.get_generator("Silly Characters")
        _, selected = runner.build_document_state(generator, {"input_1": ""})
        self.assertEqual(selected, {"random"})
        _, selected = runner.build_document_state(generator, {"input_1": "Alice"})
        self.assertEqual(selected, set())

    def test_widgets_the_generator_ignores_are_not_passed_through(self):
        generator = catalog.get_generator("Prompts")
        values, _ = runner.build_document_state(generator, {"input_1": "ignored"})
        self.assertEqual(values, {})


class TestGenerate(unittest.TestCase):
    def test_runs_a_script_and_returns_plain_text(self):
        text = runner.generate("Scenarios - Single Person", {"input_1": "Alice"}, seed=1, source=FAKE_SCRIPT)
        first, second = text.split("\n")
        self.assertEqual(first, "Who: Alice")
        self.assertIn(second, ("first thing", "second thing", "third thing"))

    def test_blank_input_uses_the_scripts_own_fallback(self):
        text = runner.generate("Scenarios - Single Person", {}, seed=1, source=FAKE_SCRIPT)
        self.assertTrue(text.startswith("Who: Someone"), text)

    def test_same_seed_gives_the_same_prompt(self):
        first = runner.generate("Prompts", {}, seed=4242, source=FAKE_SCRIPT)
        second = runner.generate("Prompts", {}, seed=4242, source=FAKE_SCRIPT)
        self.assertEqual(first, second)

    def test_different_seeds_reach_different_prompts(self):
        results = {runner.generate("Prompts", {}, seed=seed, source=FAKE_SCRIPT) for seed in range(30)}
        self.assertGreater(len(results), 1)

    def test_a_script_we_cannot_run_reports_the_generator(self):
        with self.assertRaises(runner.GeneratorError) as caught:
            runner.generate("Prompts", {}, seed=0, source="function generateThings() { var f = () => 1; }")
        self.assertIn("Prompts", str(caught.exception))

    def test_a_script_that_writes_nothing_is_an_error(self):
        with self.assertRaises(runner.GeneratorError):
            runner.generate("Prompts", {}, seed=0, source="function generateThings() { var a = 1; }")

    def test_unknown_generator_raises(self):
        with self.assertRaises(KeyError):
            runner.generate("Not A Generator", {}, seed=0, source=FAKE_SCRIPT)


if __name__ == "__main__":
    unittest.main()
