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


class TestAnalyticsSnippet(unittest.TestCase):
    """The site appended a GA4 block to the end of every generator script;
    until it parsed, all 20 generators failed against the live site."""

    SNIPPET = (
        '// Track generator use in GA4\n'
        'if (typeof window.gtag === "function") {\n'
        '  window.gtag("event", "generator_used", {\n'
        '    generator_name: "Zodiac"\n'
        '  });\n'
        '}\n'
    )

    def test_snippet_parses_and_is_a_noop(self):
        body = 'document.getElementById("promptDisplay").innerHTML = "done";\n' + self.SNIPPET
        self.assertEqual(run(body), "done")

    def test_window_gtag_is_undefined_so_it_is_never_called(self):
        body = (
            'var kind = typeof window.gtag;\n'
            'document.getElementById("promptDisplay").innerHTML = kind;'
        )
        self.assertEqual(run(body), "undefined")

    def test_typeof_of_undeclared_name_does_not_raise(self):
        body = 'document.getElementById("promptDisplay").innerHTML = typeof nowhere;'
        self.assertEqual(run(body), "undefined")

    def test_typeof_of_values(self):
        body = (
            'var a = ["x"]; var n = 1; var s = "t"; var f = Math.floor;\n'
            'document.getElementById("promptDisplay").innerHTML = '
            'typeof n + "," + typeof s + "," + typeof a + "," + typeof (n === 1);'
        )
        self.assertEqual(run(body), "number,string,object,boolean")

    def test_object_literal_parses_in_expression_position(self):
        body = 'var o = {a: 1, "b": "two"};\ndocument.getElementById("promptDisplay").innerHTML = "ok";'
        self.assertEqual(run(body), "ok")

    def test_window_has_no_other_surface(self):
        # a call on window must not silently succeed: nothing may phone home
        with self.assertRaises(jsmini.JSError):
            run('window.gtag("event", "x", {});')


class TestHardening(unittest.TestCase):
    """The interpreted source is a remote script we don't control; none of
    these may escape as anything but a JSError (or a correct JS result)."""

    def shown(self, expression):
        return run('document.getElementById("promptDisplay").innerHTML = ' + expression + ";")

    def test_pow_matches_js_where_python_raises_or_goes_complex(self):
        self.assertEqual(self.shown("Math.pow(2, 10)"), "1024")
        self.assertEqual(self.shown("Math.pow(-8, 1/3)"), "NaN")  # complex in Python
        self.assertEqual(self.shown("Math.pow(0, -1)"), "Infinity")  # ZeroDivisionError in Python
        self.assertEqual(self.shown("Math.pow(10, 1000)"), "Infinity")  # OverflowError in Python
        self.assertEqual(self.shown("Math.pow(-2, 3)"), "-8")

    def test_nested_loops_share_one_iteration_budget(self):
        original = jsmini.MAX_LOOP_ITERATIONS
        jsmini.MAX_LOOP_ITERATIONS = 1000
        try:
            with self.assertRaises(jsmini.JSError):
                # 100 * 100 = 10000 > 1000, though no single loop passes 100
                run("for (var i = 0; i < 100; i++) { for (var j = 0; j < 100; j++) { var x = 1; } }")
        finally:
            jsmini.MAX_LOOP_ITERATIONS = original

    def test_huge_array_is_rejected(self):
        with self.assertRaises(jsmini.JSError):
            run("var a = new Array(99999999999);")

    def test_runaway_recursion_becomes_jserror(self):
        with self.assertRaises(jsmini.JSError):
            jsmini.run_script("function f() { return f(); }\nfunction generateThings() { f(); }\n")

    def test_malformed_unicode_escape_becomes_jserror(self):
        with self.assertRaises(jsmini.JSError):
            run(r'var s = "\u12";')


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


class TestGrowthLimits(unittest.TestCase):
    """A hostile or rewritten remote script must hit an error, not take the whole ComfyUI process down."""

    def run_js(self, source):
        return jsmini.run_script(source)

    def test_doubling_a_string_in_a_loop_stops_at_the_limit(self):
        with self.assertRaises(jsmini.JSError) as caught:
            self.run_js("var s = 'x'; for (var i = 0; i < 60; i++) { s = s + s; }")
        self.assertIn("string longer than", str(caught.exception))

    def test_concat_and_join_are_limited_too(self):
        for source in (
            "var s = 'x'; for (var i = 0; i < 60; i++) { s = s.concat(s); }",
            "var a = []; for (var i = 0; i < 900000; i++) { a.push('abcdefghij'); } var s = a.join('');",
            "var s = 'x'; for (var i = 0; i < 60; i++) { s = [s, s].join(''); }",
        ):
            with self.subTest(source=source[:50]):
                with self.assertRaises(jsmini.JSError):
                    self.run_js(source)

    def test_doubling_an_array_stops_at_the_limit(self):
        for source in (
            "var a = [1]; for (var i = 0; i < 60; i++) { a = a.concat(a); }",
            "var a = [1]; for (var i = 0; i < 60; i++) { a = a.concat(a, a); }",
        ):
            with self.subTest(source=source[:50]):
                with self.assertRaises(jsmini.JSError):
                    self.run_js(source)

    def test_ordinary_sizes_are_untouched(self):
        out = self.run_js(
            "var s = ''; for (var i = 0; i < 1000; i++) { s = s + 'word '; }"
            "var a = []; for (var j = 0; j < 5000; j++) { a.push('x'); }"
            "document.getElementById('promptDisplay').innerHTML = s.length + ':' + a.join('').length;"
        )
        self.assertEqual(out, "5000:5000")


if __name__ == "__main__":
    unittest.main()
