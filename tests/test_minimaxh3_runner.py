import http.client
import io
import json
import os
import socket
import sys
import time
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

h3kit = module("minimaxh3prompt.h3kit")
runner = module("minimaxh3prompt.runner")
nodes = module("minimaxh3prompt.nodes")
selection = module("minimaxh3prompt.selection")

REQUEST = "девушка в кафе смотрит в окно на дождь, потом улыбается"
TRIGGERS = "kodak_portra, subject:ohwx_girl"
PROMPT = (
    "integrated_multimodal_description: [Shot 1] Live-action, cinematic, kodak_portra look, soft overcast light, "
    "an eye-level medium shot frames a ohwx_girl young woman in a grey sweater on the left third of the frame in "
    "profile facing right, beside a rain-streaked café window on the right third. First she watches raindrops "
    "slide down the glass, then she wraps both hands around a white cup. The camera pushes in with small amplitude "
    "at slow speed toward her face. By the end of the shot her face fills the left half of the frame. [Shot 2] "
    "At 00:04.000, the camera cuts to a close-up of her face in the center of the frame, facing the window. First "
    "she lowers the cup, then a small smile slowly appears. The camera holds a static shot. By the end of the shot "
    "she is still smiling, her eyes on the rain.\n\n"
    "overall_soundscape: Steady rain taps against the window under quiet café ambience. A cup clinks softly on a "
    "saucer.\n\n"
    "non_diegetic_music: Sparse piano notes at a slow tempo that gradually fade out."
)

VALUES = {
    "ollama_url": "http://localhost:11434",
    "model": "qwen3.6:35b-a3b",
    "request": REQUEST,
    "duration": 8,
    "aspect": "16:9",
    "mode": "T2VA",
    "variant": "auto",
    "seed": 123,
    "triggers": TRIGGERS,
}


class FakeResponse:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self, amount=-1):
        return self._raw if amount is None or amount < 0 else self._raw[:amount]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """Stands in for h3kit's opener: remembers the request, answers with a canned payload."""

    def __init__(self, payload=None, raw=None):
        self.payload = {"message": {"content": "ok"}} if payload is None else payload
        self.raw = raw
        self.requests = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        if self.raw is not None:
            response = FakeResponse({})
            response._raw = self.raw
            return response
        return FakeResponse(self.payload)


class FakeModel:
    """Stands in for h3kit.ollama_chat; records the calls it received."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, messages, model, host="", think=False, fmt=None, **kw):
        self.calls.append({"messages": messages, "model": model, "host": host, "think": think, "fmt": fmt, **kw})
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if kw.get("on_answer") is not None:  # the real client reports what the model wrote
            kw["on_answer"](answer)
        return answer


class TestKitSeed(unittest.TestCase):
    def sent_body(self, **kw):
        opener = FakeOpener()
        with mock.patch.object(h3kit, "_OPENER", opener):
            h3kit.ollama_chat([{"role": "user", "content": "x"}], "m", **kw)
        return json.loads(opener.requests[0].data)

    def test_seed_reaches_the_request_options(self):
        self.assertEqual(self.sent_body(seed=77)["options"]["seed"], 77)
        self.assertEqual(self.sent_body(seed=0)["options"]["seed"], 0)

    def test_no_seed_leaves_ollama_random(self):
        self.assertNotIn("seed", self.sent_body()["options"])

    def test_no_think_marks_only_the_last_user_message_and_not_the_callers_list(self):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "a"},
            {"role": "user", "content": "second"},
        ]
        opener = FakeOpener()
        with mock.patch.object(h3kit, "_OPENER", opener):
            h3kit.ollama_chat(messages, "m", no_think=True)
        sent = [m["content"] for m in json.loads(opener.requests[0].data)["messages"]]
        self.assertEqual(sent, ["sys", "first", "a", "second\n/no_think"])
        self.assertEqual(messages[-1]["content"], "second")

    def test_no_think_off_by_default(self):
        self.assertNotIn("/no_think", json.dumps(self.sent_body()["messages"]))

    def test_the_request_goes_to_api_chat_on_the_given_address(self):
        opener = FakeOpener()
        with mock.patch.object(h3kit, "_OPENER", opener):
            h3kit.ollama_chat([{"role": "user", "content": "x"}], "m", host="http://box:11434/")
        self.assertEqual(opener.requests[0].full_url, "http://box:11434/api/chat")

    def test_on_answer_sees_the_models_own_text(self):
        seen = []
        with mock.patch.object(h3kit, "_OPENER", FakeOpener({"message": {"content": "hello"}})):
            returned = h3kit.ollama_chat([{"role": "user", "content": "x"}], "m", on_answer=seen.append)
        self.assertEqual((returned, seen), ("hello", ["hello"]))

    def test_an_oversized_response_is_refused(self):
        with mock.patch.object(h3kit, "MAX_RESPONSE_BYTES", 100):
            with mock.patch.object(h3kit, "_OPENER", FakeOpener(raw=b"x" * 500)):
                with self.assertRaises(ValueError):
                    h3kit.ollama_chat([{"role": "user", "content": "x"}], "m")

    def test_redirects_are_not_followed(self):
        # an Ollama server never redirects; following one would turn the POST into a GET elsewhere
        handler = h3kit._NoRedirect()
        request = h3kit.urllib.request.Request("http://a/api/chat", data=b"{}")
        self.assertIsNone(handler.redirect_request(request, None, 302, "Found", {}, "http://b/secret"))


class TestKitOffline(unittest.TestCase):
    def test_example_prompt_passes_the_validator(self):
        # the node's tests lean on this sample being a valid answer
        req = h3kit.make_request(request=REQUEST, duration=8, aspect="16:9", triggers=TRIGGERS)
        fixed, _ = h3kit.autofix(PROMPT, req)
        self.assertEqual(h3kit.validate(fixed, req), [])

    def test_prompts_ship_with_the_package(self):
        for variant in h3kit.VARIANTS:
            self.assertTrue(h3kit.load_system(variant).strip(), variant)


class TestBuildRequest(unittest.TestCase):
    def test_refs_one_per_line(self):
        options = selection.coerce_options({**VALUES, "refs": "image|subject|a robot\n\naudio|voice|calm voice|S1"})
        req = runner.build_request(options)
        self.assertEqual([r["kind"] for r in req["refs"]], ["image", "audio"])

    def test_bad_ref_is_an_input_error(self):
        options = selection.coerce_options({**VALUES, "refs": "hologram|subject|x"})
        with self.assertRaises(selection.InputError):
            runner.build_request(options)

    def test_shots_zero_means_automatic(self):
        req = runner.build_request(selection.coerce_options(VALUES))
        self.assertIsNone(req["shots"])
        req = runner.build_request(selection.coerce_options({**VALUES, "shots": 3}))
        self.assertEqual(req["shots"], 3)


class TestGenerate(unittest.TestCase):
    def run_with(self, model, **overrides):
        with mock.patch.object(h3kit, "ollama_chat", model):
            return runner.generate({**VALUES, **overrides})

    def test_happy_path_single_prompt(self):
        model = FakeModel(PROMPT)
        result = self.run_with(model)
        self.assertEqual(result["variant"], "t2va")
        self.assertEqual(len(result["clips"]), 1)
        self.assertEqual(result["text"], result["clips"][0])
        self.assertEqual(result["errors"], [])
        self.assertIn("validator: OK", result["report"])
        self.assertEqual(len(model.calls), 1)

    def test_options_reach_ollama(self):
        model = FakeModel(PROMPT)
        self.run_with(model, seed=999, temperature=0.7, num_ctx=4096, num_predict=500, timeout=77, think=True)
        call = model.calls[0]
        self.assertEqual(call["seed"], 999)
        self.assertEqual(call["temperature"], 0.7)
        self.assertEqual(call["num_ctx"], 4096)
        self.assertEqual(call["num_predict"], 500)
        self.assertEqual(call["timeout"], 77)
        self.assertEqual(call["host"], "http://localhost:11434")
        self.assertTrue(call["think"])
        self.assertFalse(call["no_think"])  # asking for the reasoning cancels the switch that turns it off

    def test_no_think_is_on_by_default(self):
        model = FakeModel(PROMPT)
        self.run_with(model)
        self.assertTrue(model.calls[0]["no_think"])

    def test_no_think_can_be_switched_off(self):
        model = FakeModel(PROMPT)
        self.run_with(model, append_no_think=False)
        self.assertFalse(model.calls[0]["no_think"])

    def test_num_predict_zero_is_left_to_the_model(self):
        model = FakeModel(PROMPT)
        self.run_with(model, num_predict=0)
        self.assertIsNone(model.calls[0]["num_predict"])

    def test_remaining_errors_are_reported_not_raised(self):
        model = FakeModel("just chatter, no shots at all")
        result = self.run_with(model, retries=1)
        self.assertTrue(result["errors"])
        self.assertIn("remaining validator errors", result["report"])
        self.assertEqual(len(model.calls), 2)  # first try + 1 retry
        self.assertTrue(result["text"])

    def test_story_returns_a_prompt_per_clip(self):
        plan = json.dumps(
            {
                "style": "Live-action, cinematic",
                "character": "a ginger cat",
                "clips": [
                    {"beat": f"beat {n}", "start": f"start {n}", "end": f"end {n}", "lines": []} for n in range(1, 4)
                ],
            }
        )
        calls = []

        def model(messages, name, host="", think=False, fmt=None, **kw):
            calls.append(fmt)
            return plan if fmt is not None else PROMPT

        with mock.patch.object(h3kit, "ollama_chat", model):
            result = runner.generate({**VALUES, "duration": 30, "retries": 0})
        self.assertEqual(result["variant"], "story")
        self.assertEqual(len(result["clips"]), 3)
        self.assertEqual(len(selection.split_clips(result["text"])), 3)
        self.assertIn("=== CLIP 1 (10 s) ===", result["text"])
        self.assertTrue(all(error.startswith("clip ") for error in result["errors"]))

    def test_empty_request_is_an_input_error(self):
        with self.assertRaises(selection.InputError):
            runner.generate({**VALUES, "request": "  "})

    def test_empty_model_answer_is_an_error(self):
        with self.assertRaises(runner.H3Error):
            self.run_with(FakeModel("   "), retries=0)


class TestNetworkErrors(unittest.TestCase):
    def failing(self, exc):
        def model(*args, **kwargs):
            raise exc

        with mock.patch.object(h3kit, "ollama_chat", model):
            with self.assertRaises(runner.H3Error) as caught:
                runner.generate(VALUES)
        return str(caught.exception)

    def test_unreachable(self):
        self.assertIn("cannot reach", self.failing(urllib.error.URLError(ConnectionRefusedError("refused"))))

    def test_timeouts(self):
        self.assertIn("did not answer", self.failing(socket.timeout()))
        self.assertIn("did not answer", self.failing(urllib.error.URLError(socket.timeout())))

    def test_http_error_carries_ollamas_message(self):
        error = urllib.error.HTTPError("u", 404, "Not Found", {}, io.BytesIO(b'{"error": "model not found"}'))
        message = self.failing(error)
        self.assertIn("404", message)
        self.assertIn("model not found", message)

    def test_unexpected_payload(self):
        self.assertIn("unusable answer", self.failing(KeyError("message")))
        self.assertIn("unusable answer", self.failing(json.JSONDecodeError("x", "", 0)))

    def test_a_server_that_hangs_up_or_is_not_ollama_is_a_clean_error(self):
        for exc in (http.client.RemoteDisconnected("closed"), http.client.IncompleteRead(b"par"), ConnectionResetError("reset"),
                    http.client.BadStatusLine("SSH-2.0-OpenSSH_9.6"), http.client.InvalidURL("nonnumeric port")):
            with self.subTest(exc=type(exc).__name__):
                message = self.failing(exc)
                self.assertIn("dropped or garbled the connection", message)
                self.assertIn(type(exc).__name__, message)

    def test_what_the_peer_sent_is_never_echoed(self):
        # an SSH banner, or a body with a secret in it: only the exception's class may be reported
        for exc in (http.client.BadStatusLine("SSH-2.0-OpenSSH_9.6 secret-banner"),
                    UnicodeDecodeError("utf-8", b'{"token": "abc123"}', 0, 1, "invalid start byte"),
                    ValueError("body: token=abc123")):
            with self.subTest(exc=type(exc).__name__):
                message = self.failing(exc)
                self.assertNotIn("secret-banner", message)
                self.assertNotIn("abc123", message)

    def test_an_oversized_or_non_utf8_answer_is_a_clean_error(self):
        self.assertIn("unusable answer", self.failing(UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")))
        self.assertIn("unusable answer", self.failing(OverflowError("too big")))

    def test_http_error_detail_is_shortened(self):
        error = urllib.error.HTTPError("u", 500, "Boom", {}, io.BytesIO(json.dumps({"error": "x" * 5000}).encode()))
        self.assertLess(len(self.failing(error)), 400)

    def test_http_error_with_an_unreadable_body_still_reports_the_status(self):
        error = urllib.error.HTTPError("u", 502, "Bad Gateway", {}, io.BytesIO(b"<html>not json</html>"))
        self.assertIn("502", self.failing(error))


class TestNode(unittest.TestCase):
    def call(self, **overrides):
        node = nodes.MiniMaxH3Prompt()
        args = {**VALUES, "generated": "", "generated_key": "", **overrides}
        return node.run(**args)

    def test_saved_text_is_output_untouched_and_nothing_is_generated(self):
        with mock.patch.object(h3kit, "ollama_chat", side_effect=AssertionError("must not be called")):
            out = self.call(generated="my hand-edited prompt")
        self.assertEqual(out["result"][0], ["my hand-edited prompt"])
        self.assertNotIn("generated", out["ui"])

    def test_saved_story_is_split_into_clips(self):
        text = selection.join_clips(["a", "b"], [10, 10])
        self.assertEqual(self.call(generated=text)["result"][0], ["a", "b"])

    def test_saved_text_wins_even_when_the_inputs_changed(self):
        out = self.call(generated="old result", request="something completely different", generated_key="stale-key")
        self.assertEqual(out["result"][0], ["old result"])

    def test_empty_saved_text_generates_and_reports_to_the_ui(self):
        with mock.patch.object(h3kit, "ollama_chat", FakeModel(PROMPT)):
            out = self.call()
        clips, report = out["result"][:2]
        self.assertEqual(len(clips), 1)
        self.assertEqual(out["ui"]["generated"], [clips[0]])
        self.assertIn("variant:", report)

    def test_generation_failure_surfaces_as_a_node_error(self):
        with mock.patch.object(h3kit, "ollama_chat", side_effect=urllib.error.URLError("down")):
            with self.assertRaises(RuntimeError) as caught:
                self.call()
        self.assertIn("MiniMax H3 prompt", str(caught.exception))

    def test_outputs_are_appended_after_the_original_two(self):
        # links are stored by slot index: prompt and report must keep slots 0 and 1
        node = nodes.MiniMaxH3Prompt
        self.assertEqual(node.RETURN_NAMES, ("prompt", "report", "duration", "frames", "width", "height", "seed"))
        self.assertEqual(node.RETURN_TYPES, ("STRING", "STRING", "INT", "INT", "INT", "INT", "INT"))
        self.assertEqual(node.OUTPUT_IS_LIST, (True, False, True, True, False, False, False))

    def test_saved_text_outputs_duration_frames_size_and_seed(self):
        out = self.call(generated="my prompt", duration=9, aspect="9:16", seed=77, short_side=768)
        prompt, report, duration, frames, width, height, seed = out["result"]
        self.assertEqual((prompt, duration, frames), (["my prompt"], [9], [216]))
        self.assertEqual((width, height, seed), (768, 1344, 77))

    def test_short_side_defaults_when_the_widget_is_absent(self):
        out = self.call(generated="x", aspect="16:9")  # a workflow saved before short_side existed
        self.assertEqual(out["result"][4:6], (1344, 768))

    def test_saved_story_outputs_one_duration_per_clip_from_the_markers(self):
        text = selection.join_clips(["a", "b", "c"], [10, 10, 7])
        out = self.call(generated=text, duration=27)
        self.assertEqual(out["result"][2], [10, 10, 7])
        self.assertEqual(out["result"][3], [240, 240, 168])

    def test_saved_clips_without_marker_durations_share_the_total(self):
        out = self.call(generated="=== CLIP 1 ===\na\n\n=== CLIP 2 ===\nb", duration=20)
        self.assertEqual(out["result"][2], [10, 10])

    def test_generated_run_outputs_the_requested_duration(self):
        with mock.patch.object(h3kit, "ollama_chat", FakeModel(PROMPT)):
            out = self.call(duration=8, seed=5)
        self.assertEqual(out["result"][2:4], ([8], [192]))
        self.assertEqual(out["result"][6], 5)

    def test_generated_story_outputs_its_clip_durations(self):
        plan = json.dumps(
            {
                "style": "Live-action, cinematic",
                "character": "a cat",
                "clips": [{"beat": "b", "start": "s", "end": "e", "lines": []} for _ in range(3)],
            }
        )

        def model(messages, name, host="", think=False, fmt=None, **kw):
            return plan if fmt is not None else PROMPT

        with mock.patch.object(h3kit, "ollama_chat", model):
            out = self.call(duration=30, retries=0)
        self.assertEqual(len(out["result"][0]), 3)
        self.assertEqual(out["result"][2], [10, 10, 10])
        self.assertEqual(out["result"][3], [240, 240, 240])

    def test_is_changed_follows_saved_text_only_when_present(self):
        is_changed = nodes.MiniMaxH3Prompt.IS_CHANGED
        same_a = is_changed(generated="text", request="one", seed=1)
        same_b = is_changed(generated="text", request="two", seed=2)
        self.assertEqual(same_a, same_b)
        self.assertNotEqual(same_a, is_changed(generated="text edited", request="one", seed=1))
        # nothing saved: the seed decides what gets generated
        self.assertNotEqual(is_changed(generated="", request="one", seed=1), is_changed(generated="", request="one", seed=2))
        self.assertEqual(is_changed(generated="", request="one", seed=1), is_changed(generated="", request="one", seed=1))


class TestFrontendContract(unittest.TestCase):
    """The JS file and the node must agree on these lists; nothing else would notice a drift."""

    @staticmethod
    def js_list(name):
        import re

        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "js", "minimax_h3.js")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        block = re.search(r"const " + name + r" = \[(.*?)\];", source, re.S).group(1)
        return re.findall(r'"([a-z_0-9]+)"', block)

    def test_the_widgets_that_decide_the_text_are_the_same_in_python_and_js(self):
        self.assertEqual(list(nodes.CONTENT_WIDGETS), self.js_list("CONTENT_WIDGETS"))

    def test_the_button_sends_every_widget_the_route_reads(self):
        self.assertEqual(set(self.js_list("REQUEST_WIDGETS")), set(nodes._WIDGETS))

    def test_the_node_hands_back_what_it_used(self):
        node = nodes.MiniMaxH3Prompt()
        with mock.patch.object(h3kit, "ollama_chat", FakeModel(PROMPT)):
            out = node.run(**{**VALUES, "generated": "", "generated_key": ""})
        used = json.loads(out["ui"]["used"][0])
        self.assertEqual(list(used), list(nodes.CONTENT_WIDGETS))
        self.assertEqual((used["request"], used["duration"], used["triggers"]), (REQUEST, 8, TRIGGERS))
        self.assertIsNone(used["shots"])  # not passed: reported as absent, like a missing widget


class TestValidateInputs(unittest.TestCase):
    validate = staticmethod(nodes.MiniMaxH3Prompt.VALIDATE_INPUTS)
    OK = dict(generated="", ollama_url="http://localhost:11434", model="m", request="a cat", refs="", variant="auto")

    def test_ok(self):
        self.assertIs(self.validate(**self.OK), True)

    def test_saved_text_skips_every_check(self):
        self.assertIs(self.validate(**{**self.OK, "generated": "x", "request": "", "ollama_url": "nope"}), True)

    def test_linked_inputs_are_left_to_execution(self):
        self.assertIs(self.validate(**{**self.OK, "request": None}), True)
        self.assertIs(self.validate(**{**self.OK, "ollama_url": None, "model": None}), True)
        self.assertIs(self.validate(**{**self.OK, "generated": None}), True)

    def test_problems_are_reported_at_queue_time(self):
        self.assertIn("request is empty", self.validate(**{**self.OK, "request": ""}))
        self.assertIn("ollama_url", self.validate(**{**self.OK, "ollama_url": "file:///x"}))
        self.assertIn("hologram", self.validate(**{**self.OK, "refs": "hologram|subject|x"}))
        self.assertIn("variant", self.validate(**{**self.OK, "variant": "nope"}))

    def test_a_hidden_refs_line_does_not_block_the_run(self):
        # the refs widget is only shown for auto / ref; a leftover line under t2va is ignored
        bad = "hologram|subject|x"
        self.assertIs(self.validate(**{**self.OK, "refs": bad, "variant": "t2va"}), True)
        self.assertIn("hologram", self.validate(**{**self.OK, "refs": bad, "variant": "ref"}))
        self.assertIn("hologram", self.validate(**{**self.OK, "refs": bad, "variant": "auto"}))

    def test_only_what_needs_a_custom_check_is_named(self):
        # naming every input (or taking **kwargs) would switch off ComfyUI's own range / combo checks
        import inspect

        parameters = set(inspect.signature(nodes.MiniMaxH3Prompt.VALIDATE_INPUTS).parameters)
        self.assertEqual(parameters, {"generated", "ollama_url", "model", "request", "refs", "variant", "input_types"})
        for numeric in ("duration", "seed", "num_ctx", "short_side", "aspect", "mode"):
            self.assertNotIn(numeric, parameters)


class TestBlankAnswers(unittest.TestCase):
    def test_a_blank_answer_is_an_error_for_every_variant_even_though_the_kit_pads_it(self):
        # I2VA / FL2VA / L2VA / ref get an alignment line or a skeleton added to an empty answer
        cases = {
            "i2va": {"mode": "I2VA", "image": "a cat on a sill"},
            "fl2va": {"mode": "FL2VA", "start": "a", "end": "b"},
            "l2va": {"mode": "L2VA", "end": "b"},
            "ref": {"refs": "image|subject|a cat"},
        }
        for name, extra in cases.items():
            with self.subTest(variant=name):
                with mock.patch.object(h3kit, "ollama_chat", FakeModel("")):
                    with self.assertRaises(runner.H3Error) as caught:
                        runner.generate({**VALUES, **extra, "retries": 1})
                self.assertIn("empty answer", str(caught.exception))

    def test_a_blank_first_try_that_the_retry_fixes_is_fine(self):
        with mock.patch.object(h3kit, "ollama_chat", FakeModel("   ", PROMPT)):
            result = runner.generate({**VALUES, "retries": 1})
        self.assertEqual(result["errors"], [])

    def test_a_story_planner_that_answers_nothing_is_an_error_with_the_hint(self):
        with mock.patch.object(h3kit, "ollama_chat", FakeModel("")):
            with self.assertRaises(runner.H3Error) as caught:
                runner.generate({**VALUES, "duration": 30})
        self.assertIn("empty answer", str(caught.exception))

    def test_a_story_planner_with_garbage_is_an_error_without_a_traceback(self):
        with mock.patch.object(h3kit, "ollama_chat", FakeModel("no braces here")):
            with self.assertRaises(runner.H3Error) as caught:
                runner.generate({**VALUES, "duration": 30})
        self.assertIn("unusable answer", str(caught.exception))
        plan_with_string_clips = json.dumps({"style": "s", "character": "c", "clips": ["a", "b", "c"]})
        with mock.patch.object(h3kit, "ollama_chat", FakeModel(plan_with_string_clips)):
            with self.assertRaises(runner.H3Error):
                runner.generate({**VALUES, "duration": 30})


class TestHiddenRefs(unittest.TestCase):
    def test_refs_are_only_read_for_variants_that_use_them(self):
        options = selection.coerce_options({**VALUES, "refs": "image|subject|a robot", "variant": "t2va"})
        self.assertEqual(runner.build_request(options)["refs"], [])
        for variant in ("auto", "ref"):
            options = selection.coerce_options({**VALUES, "refs": "image|subject|a robot", "variant": variant})
            self.assertEqual(len(runner.build_request(options)["refs"]), 1)


class TestRepairSpeed(unittest.TestCase):
    """A model stuck in a loop can answer with thousands of blank lines; the repair regexes must stay fast."""

    def timed(self, function, text, req):
        start = time.perf_counter()
        function(text, req)
        return time.perf_counter() - start

    def test_pathological_answers_are_repaired_in_well_under_a_second(self):
        req = h3kit.make_request(request="a cat", duration=8, triggers="kodak_portra")
        req_ref = h3kit.make_request(request="a cat", duration=8, refs=["image|subject|a cat"])
        shapes = [
            "integrated_multimodal_description: [Shot 1] Live-action. " + "\n" * 6000,
            "integrated_multimodal_description: [Shot 1] a cat" + " " * 6000 + "walks, at a moderate speed",
            "*" * 6000 + "integrated_multimodal_description: x",
            "* " * 3000 + "x",
            "The camera pans" + " ," * 3000 + " at a calm pace",
            "summary" + "\n * # " * 2000 + "detailed_description: x",
        ]
        for text in shapes:
            with self.subTest(shape=text[:30]):
                self.assertLess(self.timed(h3kit.autofix, text, req), 1.0)
                self.assertLess(self.timed(h3kit.autofix_ref, text, req_ref), 1.0)

    def test_a_huge_answer_is_cut_before_it_is_repaired(self):
        req = h3kit.make_request(request="a cat", duration=8)
        fixed, _ = h3kit.autofix("word " * 200_000, req)
        self.assertLessEqual(len(fixed), h3kit.MAX_ANSWER_CHARS + 500)

    def test_markdown_decorated_field_names_are_still_repaired(self):
        req = h3kit.make_request(request="a cat", duration=8, triggers="kodak_portra")
        decorated = (
            "Sure! Here it is:\n**integrated_multimodal_description**: " + PROMPT.split("integrated_multimodal_description:")[1].split("\n\n")[0].strip()
            + "\n\n## overall_soundscape: Rain on glass.\n\n**non_diegetic_music**: Soft piano."
        )
        fixed, fixes = h3kit.autofix(decorated, req)
        self.assertTrue(fixed.startswith("integrated_multimodal_description:") or "integrated_multimodal_description:" in fixed.splitlines()[0])
        self.assertIn("removed text before integrated_multimodal_description", fixes)
        self.assertNotIn("**", fixed)


if __name__ == "__main__":
    unittest.main()
