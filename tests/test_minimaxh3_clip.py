"""The CLIP backend of the MiniMax H3 node: a text-LLM encoder of the running graph writes the text
instead of Ollama. Driven with a fake CLIP: no ComfyUI, no model, no network."""
import os
import sys
import unittest
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402
from test_minimaxh3_runner import PROMPT, VALUES  # noqa: E402

clipchat = module("minimaxh3prompt.clipchat")
h3kit = module("minimaxh3prompt.h3kit")
runner = module("minimaxh3prompt.runner")
nodes = module("minimaxh3prompt.nodes")


class FakeClip:
    """The three methods core's Generate Text node uses; records what it was asked."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.tokenized = []
        self.generated = []

    def tokenize(self, text, **kwargs):
        self.tokenized.append({"text": text, **kwargs})
        return ("tokens", len(self.tokenized))

    def generate(self, tokens, **kwargs):
        self.generated.append({"tokens": tokens, **kwargs})
        return ["ids", len(self.generated)]

    def decode(self, ids):
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


class Interrupted(Exception):
    pass


Interrupted.__name__ = "InterruptProcessingException"


class TestFlatten(unittest.TestCase):
    def test_system_and_first_user_turn(self):
        system, user = clipchat.flatten([{"role": "system", "content": "S"}, {"role": "user", "content": "U"}])
        self.assertEqual((system, user), ("S", "U"))

    def test_retry_history_is_folded_into_the_user_prompt(self):
        messages = [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "write it"},
            {"role": "assistant", "content": "first try"},
            {"role": "user", "content": "fix these"},
        ]
        system, user = clipchat.flatten(messages)
        self.assertEqual(system, "S")
        self.assertEqual(user, "write it\n\nYour previous answer:\nfirst try\n\nfix these")

    def test_a_json_schema_becomes_an_instruction(self):
        _, user = clipchat.flatten([{"role": "user", "content": "plan"}], fmt={"type": "object"})
        self.assertTrue(user.startswith("plan"))
        self.assertIn("single JSON object only", user)
        self.assertTrue(user.endswith('{"type": "object"}'))


class TestSplitReasoning(unittest.TestCase):
    def test_reasoning_block_is_dropped(self):
        self.assertEqual(clipchat.split_reasoning("<think>hmm</think>\n answer "), "answer")

    def test_text_without_reasoning_is_kept(self):
        self.assertEqual(clipchat.split_reasoning("  plain "), "plain")

    def test_a_stray_close_tag_does_not_eat_the_text(self):
        self.assertEqual(clipchat.split_reasoning("a </think> b"), "a </think> b")


class TestMakeChat(unittest.TestCase):
    def test_not_a_text_encoder_is_refused_with_advice(self):
        with self.assertRaises(clipchat.ClipError) as ctx:
            clipchat.make_chat(object())
        self.assertIn("text-LLM encoder", str(ctx.exception))

    def test_options_reach_the_encoder(self):
        clip = FakeClip("the answer")
        seen = []
        chat = clipchat.make_chat(clip)
        out = chat([{"role": "system", "content": "S"}, {"role": "user", "content": "U"}], "ignored", "ignored", True,
                   temperature=0.5, num_predict=300, seed=42, on_answer=seen.append)
        self.assertEqual(out, "the answer")
        self.assertEqual(seen, ["the answer"])
        tokenized, generated = clip.tokenized[0], clip.generated[0]
        self.assertEqual((tokenized["text"], tokenized["system_prompt"], tokenized["thinking"]), ("U", "S", True))
        self.assertFalse(tokenized["skip_template"])
        self.assertEqual((generated["max_length"], generated["seed"], generated["temperature"]), (300, 42, 0.5))
        self.assertTrue(generated["do_sample"])

    def test_defaults_and_ceiling_of_the_token_budget(self):
        clip = FakeClip("x")
        chat = clipchat.make_chat(clip)
        chat([{"role": "user", "content": "U"}])
        chat([{"role": "user", "content": "U"}], num_predict=10 ** 6)
        self.assertEqual([g["max_length"] for g in clip.generated], [clipchat.DEFAULT_MAX_LENGTH, clipchat.MAX_LENGTH])

    def test_zero_temperature_means_greedy(self):
        clip = FakeClip("x")
        clipchat.make_chat(clip)([{"role": "user", "content": "U"}], temperature=0.0)
        self.assertFalse(clip.generated[0]["do_sample"])
        self.assertGreater(clip.generated[0]["temperature"], 0)  # core's node refuses 0

    def test_interrupt_passes_through_untouched(self):
        clip = FakeClip("x")
        clip.generate = mock.Mock(side_effect=Interrupted("stop"))
        with self.assertRaises(Interrupted):
            clipchat.make_chat(clip)([{"role": "user", "content": "U"}])

    def test_wrong_kind_of_clip_is_explained(self):
        clip = FakeClip("x")
        clip.tokenize = mock.Mock(side_effect=TypeError("tokenize() got an unexpected keyword argument 'thinking'"))
        with self.assertRaises(clipchat.ClipError) as ctx:
            clipchat.make_chat(clip)([{"role": "user", "content": "U"}])
        self.assertIn("text-LLM encoder", str(ctx.exception))

    def test_other_failures_are_named_and_bounded(self):
        clip = FakeClip("x")
        clip.generate = mock.Mock(side_effect=RuntimeError("out of memory " + "x" * 1000))
        with self.assertRaises(clipchat.ClipError) as ctx:
            clipchat.make_chat(clip)([{"role": "user", "content": "U"}])
        self.assertIn("RuntimeError", str(ctx.exception))
        self.assertLess(len(str(ctx.exception)), 400)


class NoNetwork(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(h3kit._OPENER, "open", side_effect=AssertionError("the CLIP backend must not open a socket"))
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(urllib.request, "urlopen", side_effect=AssertionError("no network"))
        patcher.start()
        self.addCleanup(patcher.stop)


class TestRunnerWithClip(NoNetwork):
    def test_prompt_is_written_by_the_clip(self):
        clip = FakeClip(PROMPT)
        result = runner.generate({**VALUES}, clip=clip)
        self.assertEqual(result["variant"], "t2va")
        self.assertIn("validator: OK", result["report"])
        self.assertEqual(len(clip.tokenized), 1)
        self.assertIn("kodak_portra", clip.tokenized[0]["text"] + clip.tokenized[0]["system_prompt"])

    def test_ollama_fields_are_not_needed(self):
        values = {**VALUES, "ollama_url": "not a url at all", "model": ""}
        self.assertTrue(runner.generate(values, clip=FakeClip(PROMPT))["clips"])

    def test_the_same_values_are_still_checked_without_a_clip(self):
        with self.assertRaises(runner.InputError):
            runner.generate({**VALUES, "model": ""})

    def test_seed_and_think_reach_the_encoder(self):
        clip = FakeClip(PROMPT)
        runner.generate({**VALUES, "seed": 77, "think": True, "num_predict": 900}, clip=clip)
        self.assertEqual((clip.generated[0]["seed"], clip.generated[0]["max_length"]), (77, 900))
        self.assertTrue(clip.tokenized[0]["thinking"])

    def test_retry_sends_the_validator_complaints(self):
        clip = FakeClip("just chatter, no shots at all", PROMPT)
        result = runner.generate({**VALUES, "retries": 1}, clip=clip)
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(clip.tokenized), 2)
        self.assertIn("Your previous answer:", clip.tokenized[1]["text"])
        self.assertIn("has these problems", clip.tokenized[1]["text"])

    def test_slots_needs_ollama(self):
        with self.assertRaises(runner.InputError) as ctx:
            runner.generate({**VALUES, "variant": "slots"}, clip=FakeClip(PROMPT))
        self.assertIn("Ollama", str(ctx.exception))

    def test_empty_answer_blames_the_clip(self):
        with self.assertRaises(runner.H3Error) as ctx:
            runner.generate({**VALUES}, clip=FakeClip("   "))
        self.assertIn("the CLIP model returned an empty answer", str(ctx.exception))
        self.assertNotIn("append_no_think", str(ctx.exception))

    def test_a_clip_that_cannot_generate_is_an_h3_error(self):
        with self.assertRaises(runner.H3Error) as ctx:
            runner.generate({**VALUES}, clip=object())
        self.assertIn("cannot generate text", str(ctx.exception))

    def test_encoder_failure_is_an_h3_error(self):
        clip = FakeClip(PROMPT)
        clip.generate = mock.Mock(side_effect=RuntimeError("out of memory"))
        with self.assertRaises(runner.H3Error) as ctx:
            runner.generate({**VALUES}, clip=clip)
        self.assertIn("RuntimeError", str(ctx.exception))

    def test_unusable_story_plan_does_not_blame_a_server(self):
        values = {**VALUES, "duration": 30, "retries": 0}
        with self.assertRaises(runner.H3Error) as ctx:
            runner.generate(values, clip=FakeClip("no json here"))
        self.assertIn("the CLIP model returned an unusable answer", str(ctx.exception))
        self.assertNotIn("server", str(ctx.exception))

    def test_story_plan_asks_for_json_in_the_prompt(self):
        clip = FakeClip("no json here")
        with self.assertRaises(runner.H3Error):
            runner.generate({**VALUES, "duration": 30, "retries": 0}, clip=clip)
        self.assertIn("single JSON object only", clip.tokenized[0]["text"])


class TestNodeWithClip(NoNetwork):
    def call(self, **overrides):
        args = {**VALUES, "generated": "", "generated_key": "", **overrides}
        return nodes.MiniMaxH3Prompt().run(**args)

    def test_node_generates_through_the_clip(self):
        clip = FakeClip(PROMPT)
        out = self.call(clip=clip)
        self.assertEqual(len(out["result"][0]), 1)
        self.assertIn("generated", out["ui"])
        self.assertEqual(len(clip.generated), 1)

    def test_saved_text_still_wins_and_the_clip_is_not_used(self):
        clip = FakeClip(PROMPT)
        out = self.call(clip=clip, generated="my own text")
        self.assertEqual(out["result"][0], ["my own text"])
        self.assertEqual(clip.generated, [])

    def test_node_reports_failures_as_runtime_errors(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.call(clip=FakeClip("  "))
        self.assertIn("MiniMax H3 prompt:", str(ctx.exception))

    def test_clip_is_an_optional_socket_of_type_clip(self):
        spec = nodes.MiniMaxH3Prompt.INPUT_TYPES()
        self.assertEqual(spec["optional"]["clip"][0], "CLIP")
        self.assertEqual(list(spec["optional"])[-1], "clip")
        self.assertNotIn("clip", spec["required"])


class TestValidateWithClip(unittest.TestCase):
    validate = staticmethod(nodes.MiniMaxH3Prompt.VALIDATE_INPUTS)

    def test_a_bad_url_does_not_matter_when_the_clip_is_linked(self):
        self.assertTrue(self.validate(generated="", ollama_url="ftp://nope", model="", request="a cat",
                                      input_types={"clip": "CLIP"}))

    def test_a_bad_url_still_matters_without_a_clip(self):
        self.assertNotEqual(self.validate(generated="", ollama_url="ftp://nope", model="m", request="a cat",
                                          input_types={}), True)
        self.assertNotEqual(self.validate(generated="", ollama_url="ftp://nope", model="m", request="a cat"), True)

    def test_slots_is_refused_with_a_linked_clip(self):
        result = self.validate(generated="", request="a cat", variant="slots", input_types={"clip": "CLIP"})
        self.assertIn("Ollama", result)

    def test_slots_is_fine_without_a_clip(self):
        self.assertTrue(self.validate(generated="", ollama_url="http://localhost:11434", model="m", request="a cat",
                                      variant="slots", input_types={}))

    def test_an_empty_request_is_still_caught(self):
        self.assertIn("request is empty", self.validate(generated="", request="  ", input_types={"clip": "CLIP"}))


if __name__ == "__main__":
    unittest.main()
