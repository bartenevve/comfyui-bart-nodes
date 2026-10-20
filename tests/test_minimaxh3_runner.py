import io
import json
import os
import socket
import sys
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

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeModel:
    """Stands in for h3kit.ollama_chat; records the calls it received."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, messages, model, host="", think=False, fmt=None, **kw):
        self.calls.append({"messages": messages, "model": model, "host": host, "think": think, "fmt": fmt, **kw})
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


class TestKitSeed(unittest.TestCase):
    def sent_body(self, **kw):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["body"] = json.loads(request.data)
            return FakeResponse({"message": {"content": "ok"}})

        with mock.patch.object(h3kit.urllib.request, "urlopen", fake_urlopen):
            h3kit.ollama_chat([{"role": "user", "content": "x"}], "m", **kw)
        return captured["body"]

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
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["body"] = json.loads(request.data)
            return FakeResponse({"message": {"content": "ok"}})

        with mock.patch.object(h3kit.urllib.request, "urlopen", fake_urlopen):
            h3kit.ollama_chat(messages, "m", no_think=True)
        sent = [m["content"] for m in captured["body"]["messages"]]
        self.assertEqual(sent, ["sys", "first", "a", "second\n/no_think"])
        self.assertEqual(messages[-1]["content"], "second")

    def test_no_think_off_by_default(self):
        self.assertNotIn("/no_think", json.dumps(self.sent_body()["messages"]))


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
        self.assertTrue(call["no_think"])  # on unless switched off

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
        self.assertIn("unexpected response", self.failing(KeyError("message")))
        self.assertIn("unexpected response", self.failing(json.JSONDecodeError("x", "", 0)))


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
        clips, report = out["result"]
        self.assertEqual(len(clips), 1)
        self.assertEqual(out["ui"]["generated"], [clips[0]])
        self.assertIn("variant:", report)

    def test_generation_failure_surfaces_as_a_node_error(self):
        with mock.patch.object(h3kit, "ollama_chat", side_effect=urllib.error.URLError("down")):
            with self.assertRaises(RuntimeError) as caught:
                self.call()
        self.assertIn("MiniMax H3 prompt", str(caught.exception))

    def test_output_is_a_list_for_clips_and_a_single_report(self):
        self.assertEqual(nodes.MiniMaxH3Prompt.OUTPUT_IS_LIST, (True, False))

    def test_is_changed_follows_saved_text_only_when_present(self):
        is_changed = nodes.MiniMaxH3Prompt.IS_CHANGED
        same_a = is_changed(generated="text", request="one", seed=1)
        same_b = is_changed(generated="text", request="two", seed=2)
        self.assertEqual(same_a, same_b)
        self.assertNotEqual(same_a, is_changed(generated="text edited", request="one", seed=1))
        # nothing saved: the seed decides what gets generated
        self.assertNotEqual(is_changed(generated="", request="one", seed=1), is_changed(generated="", request="one", seed=2))
        self.assertEqual(is_changed(generated="", request="one", seed=1), is_changed(generated="", request="one", seed=1))


class TestValidateInputs(unittest.TestCase):
    validate = staticmethod(nodes.MiniMaxH3Prompt.VALIDATE_INPUTS)

    def test_ok(self):
        self.assertIs(self.validate(generated="", **VALUES), True)

    def test_saved_text_skips_every_check(self):
        self.assertIs(self.validate(generated="x", **{**VALUES, "request": "", "ollama_url": "nope"}), True)

    def test_linked_inputs_are_left_to_execution(self):
        self.assertIs(self.validate(generated="", **{**VALUES, "request": None}), True)
        self.assertIs(self.validate(generated=None, **VALUES), True)

    def test_problems_are_reported_at_queue_time(self):
        self.assertIn("request is empty", self.validate(generated="", **{**VALUES, "request": ""}))
        self.assertIn("ollama_url", self.validate(generated="", **{**VALUES, "ollama_url": "file:///x"}))
        self.assertIn("hologram", self.validate(generated="", **{**VALUES, "refs": "hologram|subject|x"}))
        self.assertIn("duration", self.validate(generated="", **{**VALUES, "duration": 3}))


if __name__ == "__main__":
    unittest.main()
