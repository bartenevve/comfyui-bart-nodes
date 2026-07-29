import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

jsmini = module("prompts52.jsmini")


def run(body, values=None, selected=(), seed=0):
    """Run `body` as the inside of a generateThings() function."""
    source = "function generateThings()\n{\n" + body + "\n}\n"
    return jsmini.run_script(source, values=values, selected=selected, rng=random.Random(seed))


class TestTokenizer(unittest.TestCase):
    def test_html_style_comments_are_line_comments(self):
        # every generator file separates its sections with these
        tokens = jsmini.tokenize("<!------- Signs -------->\nvar a = 1;")
        self.assertEqual([token.value for token in tokens if token.kind == "name"], ["var", "a"])

    def test_slash_comments_and_block_comments(self):
        tokens = jsmini.tokenize("// note\nvar a = 1; /* also\nnote */ var b = 2;")
        self.assertEqual([token.value for token in tokens if token.kind == "name"], ["var", "a", "var", "b"])

    def test_escaped_quote_inside_string(self):
        tokens = jsmini.tokenize(r"'Everyone forgets someone\'s birthday.'")
        self.assertEqual(tokens[0].value, "Everyone forgets someone's birthday.")

    def test_newline_before_is_tracked_for_semicolon_insertion(self):
        tokens = jsmini.tokenize("a = 1\nb = 2")
        flags = [(token.kind, token.value, token.newline_before) for token in tokens]
        self.assertEqual(
            flags[:5],
            [
                ("name", "a", True),  # the first token counts as line-initial
                ("punc", "=", False),
                ("num", 1.0, False),
                ("name", "b", True),  # this is where a semicolon gets inserted
                ("punc", "=", False),
            ],
        )

    def test_unterminated_string_raises(self):
        with self.assertRaises(jsmini.JSError):
            jsmini.tokenize("var a = 'oops")


class TestCoercions(unittest.TestCase):
    def test_integral_floats_print_without_a_decimal_point(self):
        self.assertEqual(jsmini.js_string(3.0), "3")
        self.assertEqual(jsmini.js_string(3.5), "3.5")

    def test_arrays_stringify_with_commas(self):
        # the two-person scenario generator relies on this: with no name typed
        # in, it concatenates the *array* of fallback names
        self.assertEqual(jsmini.js_string(["Character A"]), "Character A")
        self.assertEqual(jsmini.js_string(["a", "b"]), "a,b")

    def test_add_concatenates_when_either_side_is_a_string(self):
        self.assertEqual(jsmini.js_add("n=", 3.0), "n=3")
        self.assertEqual(jsmini.js_add(1.0, 2.0), 3.0)

    def test_blank_string_is_zero_and_garbage_is_nan(self):
        self.assertEqual(jsmini.js_number(""), 0.0)
        self.assertTrue(jsmini.js_number("abc") != jsmini.js_number("abc"))


class TestStatements(unittest.TestCase):
    def test_pick_one_from_a_list(self):
        output = run(
            "var myWords = ['a', 'b', 'c'];\n"
            "var randomWord = myWords[Math.floor(Math.random()*myWords.length)];\n"
            'document.getElementById("promptDisplay").innerHTML = randomWord;'
        )
        self.assertIn(output, ("a", "b", "c"))

    def test_missing_semicolons_are_inserted_at_line_breaks(self):
        output = run(
            "var fun = new Array()\n"
            'fun[0] = "one"\n'
            'fun[1] = "two"\n'
            'document.getElementById("promptDisplay").innerHTML = fun[1]'
        )
        self.assertEqual(output, "two")

    def test_missing_semicolon_without_a_line_break_raises(self):
        with self.assertRaises(jsmini.JSError):
            run("var a = 1 var b = 2")

    def test_capitalize_loop(self):
        output = run(
            "var myWords = ['cowboy'];\n"
            "for(var i = 0 ; i < myWords.length ; i++)\n"
            "{\n"
            "    myWords[i] = myWords[i].charAt(0).toUpperCase() + "
            "myWords[i].substr(1,myWords[i].length-1);\n"
            "}\n"
            'document.getElementById("promptDisplay").innerHTML = myWords[0];'
        )
        self.assertEqual(output, "Cowboy")

    def test_splice_pop_draws_without_replacement(self):
        output = run(
            "var n = 3;\n"
            "var myWords = ['a', 'b', 'c'];\n"
            "var picked = [];\n"
            "for (var i=0; i<n; i++) {\n"
            "    picked.push(myWords.splice(Math.random()*(myWords.length-0),1).pop());\n"
            "}\n"
            "document.getElementById(\"promptDisplay\").innerHTML = picked.join('<br>');"
        )
        self.assertEqual(sorted(output.split("<br>")), ["a", "b", "c"])

    def test_string_field_value_drives_a_numeric_loop(self):
        # the object generator reads its count out of a text field
        output = run(
            'var n = document.getElementById("Input1").value;\n'
            "var out = [];\n"
            "for (var i=0; i<n; i++) { out.push('x'); }\n"
            "document.getElementById(\"promptDisplay\").innerHTML = out.join('');",
            values={"Input1": "4"},
        )
        self.assertEqual(output, "xxxx")

    def test_if_else_and_index_of(self):
        output = run(
            "var vowals = \"aeiouAEIOU\";\n"
            "var words = ['apple', 'pear'];\n"
            "for ( var n = 0; n < words.length; n++ )\n"
            "{\n"
            "     var first = words[n][0];\n"
            "     if ( vowals.indexOf(first) >= 0 )\n"
            '         words[n] = " An " + words[n];\n'
            "     else\n"
            '         words[n] = " A " + words[n];\n'
            "     }\n"
            "document.getElementById(\"promptDisplay\").innerHTML = words.join('|');"
        )
        self.assertEqual(output, " An apple| A pear")

    def test_swap_through_a_temporary(self):
        output = run(
            'var X = "first";\n'
            'var Y = "second";\n'
            "var SWAP = 0;\n"
            "if (1 == 1) {\n"
            "SWAP = X;\n"
            "X = Y;\n"
            "Y = SWAP;\n"
            "}\n"
            'document.getElementById("promptDisplay").innerHTML = X + "/" + Y;'
        )
        self.assertEqual(output, "second/first")

    def test_return_stops_the_script(self):
        output = run(
            "var choices = [];\n"
            "  if (choices.length == 0) return;\n"
            'document.getElementById("promptDisplay").innerHTML = "unreachable";'
        )
        self.assertEqual(output, "")

    def test_sparse_index_assignment_extends_the_array(self):
        # the zodiac generator fills a `new Array()` by index; reading a hole
        # has to give undefined, exactly as the browser would
        output = run(
            "var SIGN = new Array();\n"
            'SIGN[2] = "Gemini";\n'
            'document.getElementById("promptDisplay").innerHTML = SIGN[2] + "|" + SIGN[0];'
        )
        self.assertEqual(output, "Gemini|undefined")

    def test_selected_flag_switches_a_branch(self):
        body = (
            'var Y = document.getElementById("Input1").value;\n'
            'var A = "picked-for-you";\n'
            'if(document.getElementById("random").selected) {\n'
            "    Y = A\n"
            "  }\n"
            'document.getElementById("promptDisplay").innerHTML = Y;'
        )
        self.assertEqual(run(body, values={"Input1": "Alice"}), "Alice")
        self.assertEqual(run(body, values={"Input1": ""}, selected=("random",)), "picked-for-you")

    def test_unknown_field_reads_as_empty_rather_than_crashing(self):
        output = run(
            'document.getElementById("promptDisplay").innerHTML = '
            '"[" + document.getElementById("Surprise").value + "]";'
        )
        self.assertEqual(output, "[]")

    def test_split_on_a_newline_escape(self):
        output = run(
            'var choices = document.getElementById("choicelist").value.split("\\n");\n'
            "document.getElementById(\"promptDisplay\").innerHTML = choices.join('|');",
            values={"choicelist": "a\nb\nc"},
        )
        self.assertEqual(output, "a|b|c")

    def test_numeric_range_random(self):
        output = run(
            "var teen = Math.floor(Math.random() * (18 - 13 + 1)) + 13;\n"
            'document.getElementById("promptDisplay").innerHTML = teen + " year old";'
        )
        age = int(output.split()[0])
        self.assertTrue(13 <= age <= 18, output)

    def test_same_seed_gives_the_same_result(self):
        body = (
            "var myWords = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'];\n"
            "var randomWord = myWords[Math.floor(Math.random()*myWords.length)];\n"
            'document.getElementById("promptDisplay").innerHTML = randomWord;'
        )
        self.assertEqual(run(body, seed=99), run(body, seed=99))


class TestFailureModes(unittest.TestCase):
    def test_unsupported_syntax_raises_instead_of_guessing(self):
        with self.assertRaises(jsmini.JSError):
            run("var f = (x) => x + 1;")
        with self.assertRaises(jsmini.JSError):
            run("var a = `template`;")

    def test_unknown_variable_raises(self):
        with self.assertRaises(jsmini.JSError):
            run('document.getElementById("promptDisplay").innerHTML = nowhere;')

    def test_unsupported_method_raises(self):
        with self.assertRaises(jsmini.JSError):
            run("var a = ['x'].flatMap(1);")

    def test_runaway_loop_is_capped(self):
        original = jsmini.MAX_LOOP_ITERATIONS
        jsmini.MAX_LOOP_ITERATIONS = 100
        try:
            with self.assertRaises(jsmini.JSError):
                run("for (var i = 0; i < 1; i = i) { var x = 1; }")
        finally:
            jsmini.MAX_LOOP_ITERATIONS = original


if __name__ == "__main__":
    unittest.main()
