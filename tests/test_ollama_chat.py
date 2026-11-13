"""The Ollama node: the client against a local stand-in server (what really arrives is recorded), and
the image encoding. No Ollama, no model, no network beyond 127.0.0.1."""
import base64
import importlib.util
import io
import json
import os
import socket
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pack import module  # noqa: E402

client = module("ollama_chat.client")
HAS_IMAGING = all(importlib.util.find_spec(name) is not None for name in ("torch", "numpy", "PIL"))

ANSWER = {
    "model": "m",
    "message": {"role": "assistant", "content": "  A story about two heroes.  "},
    "done": True,
    "done_reason": "stop",
    "prompt_eval_count": 120,
    "eval_count": 30,
    "total_duration": 2_500_000_000,
}


class FakeOllama:
    """A stand-in server: records every request, answers with `behaviour`."""

    def __init__(self):
        self.requests = []
        self.behaviour = ("ok", ANSWER)
        self.ps = None  # what GET /api/ps answers; None = 404
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                outer.requests.append({"path": self.path, "raw": raw, "headers": dict(self.headers)})
                kind, payload = outer.behaviour
                if kind == "ok":
                    self.reply(200, json.dumps(payload))
                elif kind == "status":
                    self.reply(payload[0], payload[1])
                elif kind == "redirect":
                    self.send_response(302)
                    self.send_header("Location", payload)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                elif kind == "sleep":
                    time.sleep(payload)
                    with_suppressed = getattr(self, "reply", None)
                    try:
                        with_suppressed(200, json.dumps(ANSWER))
                    except OSError:
                        pass
                elif kind == "close":
                    self.connection.shutdown(socket.SHUT_RDWR)

            def do_GET(self):
                if self.path == "/api/ps" and outer.ps is not None:
                    self.reply(200, json.dumps(outer.ps))
                else:
                    self.reply(404, "{}")

            def reply(self, status, text):
                data = text.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def last_body(self):
        return json.loads(self.requests[-1]["raw"])


class WithServer(unittest.TestCase):
    def setUp(self):
        self.server = FakeOllama()
        self.addCleanup(self.server.close)


class TestAddress(unittest.TestCase):
    def test_a_bare_host_gets_http_and_the_ollama_port(self):
        for typed, want in (("localhost", "http://localhost:11434"), ("", "http://localhost:11434"),
                            ("  192.168.1.5 ", "http://192.168.1.5:11434"), ("myhost:11500", "http://myhost:11500")):
            self.assertEqual(client.normalize_address(typed), want, typed)

    def test_a_full_url_is_kept(self):
        self.assertEqual(client.normalize_address("http://box"), "http://box")
        self.assertEqual(client.normalize_address("https://proxy.example/ollama/"), "https://proxy.example/ollama")
        self.assertEqual(client.normalize_address("http://[::1]:11434"), "http://[::1]:11434")

    def test_unusable_addresses_are_refused(self):
        for bad in ("ftp://host", "http://u:p@host", "http://host?x=1", "http://host#f", "http://host:99x",
                    "http://host/a;b", "ho st", "http://", "x" * 3000, "host\nHeader: 1"):
            with self.assertRaises(client.SettingsError, msg=bad):
                client.normalize_address(bad)


class TestSettings(unittest.TestCase):
    def test_the_prefilled_settings_are_ollamas_defaults_with_a_context_of_8192(self):
        options, top, node = client.parse_settings(client.DEFAULT_SETTINGS)
        self.assertEqual(options["temperature"], 0.8)
        self.assertEqual(options["top_k"], 40)
        self.assertEqual(options["num_ctx"], 8192)
        self.assertEqual(options["seed"], -1)  # random: Ollama's real default (its docs say 0, which is a fixed seed)
        self.assertEqual((top, node), ({}, {}))

    def test_random_seed_detection(self):
        for options in ({}, {"seed": -1}, {"seed": -5}, {"seed": "x"}, {"seed": True}, {"seed": None}):
            self.assertTrue(client.is_random_seed(options), options)
        for options in ({"seed": 0}, {"seed": 42}, {"seed": 2**40}):
            self.assertFalse(client.is_random_seed(options), options)

    def test_keys_go_where_they_belong(self):
        options, top, node = client.parse_settings(json.dumps(
            {"num_ctx": 8192, "think": False, "keep_alive": "5m", "format": "json", "system": "s", "timeout": 30,
             "image_max_side": 512, "seed": 1}))
        self.assertEqual(options, {"num_ctx": 8192, "seed": 1})
        self.assertEqual(top, {"think": False, "keep_alive": "5m", "format": "json", "system": "s"})
        self.assertEqual(node, {"timeout": 30, "image_max_side": 512})

    def test_empty_settings_mean_none(self):
        self.assertEqual(client.parse_settings("  "), ({}, {}, {}))
        self.assertEqual(client.parse_settings(None), ({}, {}, {}))

    def test_values_are_passed_untouched(self):
        options, _, _ = client.parse_settings('{"num_ctx": 999999999, "anything": [1, "x"], "temperature": "hot"}')
        self.assertEqual(options, {"num_ctx": 999999999, "anything": [1, "x"], "temperature": "hot"})

    def test_bad_settings_are_named(self):
        for bad in ("{oops", "[1, 2]", "42", "null", "[" * 100000):
            with self.assertRaises(client.SettingsError, msg=bad[:20]):
                client.parse_settings(bad)

    def test_node_numbers_are_checked(self):
        self.assertEqual(client.node_number({}, "timeout", 900, 1), 900)
        self.assertEqual(client.node_number({"timeout": 5}, "timeout", 900, 1), 5)
        for bad in (0, -1, True, "x", None, float("nan")):
            with self.assertRaises(client.SettingsError):
                client.node_number({"timeout": bad}, "timeout", 900, 1)


class TestWhatReachesOllama(WithServer):
    def ask(self, settings="", images=(), prompt="придумай сценарий", model="qwen3-vl:2b-instruct"):
        return client.run(self.server.url, model, prompt, images, settings)

    def test_any_num_ctx_arrives_as_written(self):
        for value in (256, 2048, 4096, 6000, 6001, 8192, 16384, 32768, 65536, 131072, 1_000_000):
            self.ask(json.dumps({"num_ctx": value}))
            self.assertEqual(self.server.last_body()["options"]["num_ctx"], value, value)
        self.assertEqual(len(self.server.requests), 11)

    def test_the_prefilled_settings_send_8192(self):
        self.ask(client.DEFAULT_SETTINGS)
        self.assertEqual(self.server.last_body()["options"]["num_ctx"], 8192)

    def test_without_num_ctx_none_is_sent(self):
        self.ask('{"temperature": 0.8}')
        self.assertNotIn("num_ctx", self.server.last_body()["options"])
        self.ask("")
        self.assertNotIn("options", self.server.last_body())

    def test_the_request_shape(self):
        self.ask('{"num_ctx": 8192, "think": false}', images=["QUJD"])
        request = self.server.requests[-1]
        self.assertEqual(request["path"], "/api/chat")
        self.assertEqual(request["headers"]["Content-Type"], "application/json")
        body = json.loads(request["raw"])
        self.assertEqual(body["model"], "qwen3-vl:2b-instruct")
        self.assertIs(body["stream"], False)
        self.assertIs(body["think"], False)
        self.assertEqual(body["messages"], [{"role": "user", "content": "придумай сценарий", "images": ["QUJD"]}])

    def test_no_images_key_without_images(self):
        self.ask()
        self.assertNotIn("images", self.server.last_body()["messages"][0])

    def test_a_big_request_arrives_intact(self):
        images = [base64.b64encode(os.urandom(2_000_000)).decode() for _ in range(4)]  # ~10 MB of base64
        text, debug = self.ask('{"num_ctx": 32768}', images=images, prompt="x" * 50000)
        self.assertEqual(text, "A story about two heroes.")
        body = self.server.last_body()
        self.assertEqual(body["messages"][0]["images"], images)
        self.assertEqual(len(body["messages"][0]["content"]), 50000)
        self.assertIn("images: 4", debug)
        self.assertIn("request: 10.", debug)

    def test_non_ascii_text_survives(self):
        self.ask(prompt="персонажи: «Анна» и 猫")
        self.assertEqual(self.server.last_body()["messages"][0]["content"], "персонажи: «Анна» и 猫")


class TestAnswers(WithServer):
    def ask(self, settings="", **kwargs):
        return client.run(self.server.url, "m", "hi", (), settings, **kwargs)

    def test_text_is_the_message_content_stripped(self):
        text, debug = self.ask()
        self.assertEqual(text, "A story about two heroes.")
        self.assertIn("HTTP 200", debug)
        self.assertIn("done_reason: stop", debug)
        self.assertIn("prompt_eval_count: 120", debug)
        self.assertIn("total_duration: 2.5 s", debug)
        self.assertNotIn("ERROR", debug)

    def test_the_servers_footprint_is_shown(self):
        self.server.ps = {"models": [{"name": "m", "context_length": 8192, "size": 4 * 2**30, "size_vram": 2 * 2**30}]}
        _, debug = self.ask('{"num_ctx": 8192}')
        self.assertIn("loaded by the server: context 8192 | 4.0 GB | 50% on GPU", debug)
        self.assertNotIn("WARNING", debug)

    def test_a_huge_context_the_server_chose_itself_is_flagged(self):
        self.server.ps = {"models": [{"name": "m", "context_length": 262144, "size": 33 * 2**30, "size_vram": 20 * 2**30}]}
        _, debug = self.ask('{"temperature": 0.8}')
        self.assertIn("context 262144", debug)
        self.assertIn("WARNING: the server loaded this model with a context of 262144 (33 GB of memory)", debug)
        self.assertIn("OLLAMA_CONTEXT_LENGTH", debug)

    def test_a_huge_context_the_user_asked_for_is_not_a_warning(self):
        self.server.ps = {"models": [{"name": "m", "context_length": 262144, "size": 33 * 2**30, "size_vram": 33 * 2**30}]}
        self.assertNotIn("WARNING", self.ask('{"num_ctx": 262144}')[1])

    def test_a_server_without_api_ps_is_fine(self):
        text, debug = self.ask()  # fake answers 404
        self.assertEqual(text, "A story about two heroes.")
        self.assertNotIn("loaded by the server", debug)

    def test_another_model_in_memory_is_ignored(self):
        self.server.ps = {"models": [{"name": "other", "context_length": 262144, "size": 2**30, "size_vram": 2**30}]}
        self.assertNotIn("loaded by the server", self.ask()[1])

    def test_a_filled_context_is_reported_as_probable_truncation(self):
        self.server.behaviour = ("ok", {**ANSWER, "prompt_eval_count": 4096})
        _, debug = self.ask('{"num_ctx": 4096}')
        self.assertIn("WARNING", debug)
        self.assertIn("num_ctx", debug)

    def test_a_roomy_context_has_no_warning(self):
        self.server.behaviour = ("ok", {**ANSWER, "prompt_eval_count": 7421})
        _, debug = self.ask('{"num_ctx": 16384}')
        self.assertNotIn("WARNING", debug)

    def test_an_unset_context_says_the_server_decides(self):
        _, debug = self.ask("")
        self.assertIn("num_ctx not set", debug)

    def test_thinking_only_answers_are_explained(self):
        self.server.behaviour = ("ok", {**ANSWER, "message": {"role": "assistant", "content": "", "thinking": "hmm " * 10}})
        text, debug = self.ask()
        self.assertEqual(text, "")
        self.assertIn("thinking (", debug)
        self.assertIn("answer is empty", debug)
        self.assertIn("think", debug)

    def test_a_server_error_body_is_shown(self):
        self.server.behaviour = ("status", (404, json.dumps({"error": "model 'm' not found"})))
        text, debug = self.ask()
        self.assertEqual(text, "")
        self.assertIn("HTTP 404", debug)
        self.assertIn("model 'm' not found", debug)

    def test_an_error_inside_a_200_is_shown(self):
        self.server.behaviour = ("ok", {"error": "boom"})
        self.assertIn("ERROR: boom", self.ask()[1])

    def test_a_long_error_is_cut(self):
        self.server.behaviour = ("status", (500, "x" * 20000))
        debug = self.ask()[1]
        self.assertLess(len(debug), 6000)
        self.assertIn("more characters", debug)

    def test_not_json_is_reported(self):
        self.server.behaviour = ("status", (200, "<html>nope</html>"))
        text, debug = self.ask()
        self.assertEqual(text, "")
        self.assertIn("not JSON", debug)

    def test_a_redirect_is_not_followed(self):
        other = FakeOllama()
        self.addCleanup(other.close)
        self.server.behaviour = ("redirect", other.url + "/api/chat")
        text, debug = self.ask()
        self.assertEqual(text, "")
        self.assertEqual(other.requests, [])
        self.assertIn("HTTP 302", debug)

    def test_a_response_that_is_too_big_is_refused(self):
        with mock.patch.object(client, "MAX_RESPONSE_BYTES", 100):
            text, debug = self.ask()
        self.assertEqual(text, "")
        self.assertIn("larger than", debug)

    def test_a_dropped_connection(self):
        self.server.behaviour = ("close", None)
        text, debug = self.ask()
        self.assertEqual(text, "")
        self.assertIn("ERROR", debug)

    def test_a_timeout(self):
        self.server.behaviour = ("sleep", 2)
        started = time.monotonic()
        text, debug = self.ask('{"timeout": 1}')
        self.assertLess(time.monotonic() - started, 1.9)
        self.assertEqual(text, "")
        self.assertIn("no answer within 1", debug)

    def test_an_unreachable_server(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        text, debug = client.run(f"127.0.0.1:{port}", "m", "hi")
        self.assertEqual(text, "")
        self.assertIn("cannot reach", debug)

    def test_bad_input_never_sends_a_request(self):
        for args in (("", "", "hi"), ("", "m", "  "), ("ftp://x", "m", "hi")):
            text, debug = client.run(self.server.url if args[0] == "" else args[0], *args[1:])
            self.assertEqual(text, "")
            self.assertTrue(debug.startswith("ERROR"), debug)
        text, debug = client.run(self.server.url, "m", "hi", (), "{broken")
        self.assertTrue(debug.startswith("ERROR: settings is not valid JSON"))
        self.assertEqual(self.server.requests, [])


@unittest.skipUnless(HAS_IMAGING, "torch, numpy and Pillow are needed")
class TestNode(WithServer):
    def setUp(self):
        super().setUp()
        import torch

        self.torch = torch
        self.nodes = module("ollama_chat.nodes")

    def frames(self, *sizes):
        """A batch of constant-colour frames [n, h, w, 3] (all of the first size: a batch has one size)."""
        height, width = sizes[0]
        return self.torch.rand(len(sizes), height, width, 3)

    def test_each_frame_of_a_batch_is_one_jpeg(self):
        from PIL import Image

        encoded, labels = self.nodes.encode_images(self.frames((48, 64), (48, 64), (48, 64)))
        self.assertEqual(len(encoded), 3)
        self.assertEqual(labels, ["64x48"] * 3)
        picture = Image.open(io.BytesIO(base64.b64decode(encoded[0])))
        self.assertEqual((picture.format, picture.size, picture.mode), ("JPEG", (64, 48), "RGB"))

    def test_big_frames_are_scaled_down_and_small_ones_left_alone(self):
        encoded, labels = self.nodes.encode_images(self.torch.rand(1, 400, 1000, 3), max_side=500)
        self.assertEqual(labels, ["500x200"])
        self.assertEqual(self.nodes.encode_images(self.torch.rand(1, 40, 100, 3), max_side=500)[1], ["100x40"])

    def test_odd_shapes(self):
        self.assertEqual(self.nodes.encode_images(self.torch.rand(30, 40, 3))[1], ["40x30"])  # one frame
        self.assertEqual(self.nodes.encode_images(self.torch.rand(1, 30, 40, 1))[1], ["40x30"])  # grey
        self.assertEqual(self.nodes.encode_images(self.torch.rand(1, 30, 40, 4))[1], ["40x30"])  # alpha dropped
        weird = self.torch.full((1, 8, 8, 3), float("nan"))
        self.assertEqual(self.nodes.encode_images(weird)[1], ["8x8"])
        with self.assertRaises(ValueError):
            self.nodes.encode_images(self.torch.rand(0, 8, 8, 3))

    def test_the_node_sends_the_images_and_reports_them(self):
        node = self.nodes.BartEasyOllama()
        text, debug = node.chat(self.server.url, "m", "describe", self.frames((32, 32), (32, 32)),
                                '{"num_ctx": 8192, "image_max_side": 16}')
        self.assertEqual(text, "A story about two heroes.")
        self.assertIn("images sent: 16x16, 16x16", debug)
        body = self.server.last_body()
        self.assertEqual(len(body["messages"][0]["images"]), 2)
        self.assertEqual(body["options"]["num_ctx"], 8192)
        self.assertNotIn("image_max_side", body["options"])

    def test_without_images_the_node_still_works(self):
        text, debug = self.nodes.BartEasyOllama().chat(self.server.url, "m", "hi")
        self.assertEqual(text, "A story about two heroes.")
        self.assertNotIn("images sent", debug)

    def test_bad_image_settings_are_a_debug_error_not_a_crash(self):
        text, debug = self.nodes.BartEasyOllama().chat(self.server.url, "m", "hi", self.frames((8, 8)), '{"image_max_side": 1}')
        self.assertEqual(text, "")
        self.assertIn("ERROR", debug)
        self.assertEqual(self.server.requests, [])

    def test_validation(self):
        validate = self.nodes.BartEasyOllama.VALIDATE_INPUTS
        self.assertTrue(validate())
        self.assertTrue(validate(address="localhost", model="m", prompt="p", settings=client.DEFAULT_SETTINGS))
        self.assertIn("model is empty", validate(model="  "))
        self.assertIn("prompt is empty", validate(prompt=""))
        self.assertIn("not valid JSON", validate(settings="{"))
        self.assertIn("http(s)", validate(address="ftp://x"))
        self.assertIn("timeout", validate(settings='{"timeout": 0}'))

    def test_a_random_seed_runs_every_time_and_a_fixed_one_may_be_cached(self):
        changed = self.nodes.BartEasyOllama.IS_CHANGED
        for settings in (client.DEFAULT_SETTINGS, '{"temperature": 0.8}', "", '{"seed": -1}', "{broken", '{"seed": "x"}'):
            value = changed(settings)
            self.assertNotEqual(value, value, settings)  # nan
        fixed = changed('{"seed": 42, "num_ctx": 8192}')
        self.assertEqual(fixed, changed('{"seed": 42, "num_ctx": 8192}'))
        self.assertNotEqual(fixed, changed('{"seed": 43, "num_ctx": 8192}'))
        self.assertEqual(changed('{"seed": 0}'), changed('{"seed": 0}'))  # 0 is a fixed seed, not "none"
        self.assertNotEqual(changed(), changed())  # called without inputs (all linked): treated as random

    def test_schema(self):
        spec = self.nodes.BartEasyOllama.INPUT_TYPES()
        self.assertEqual(list(spec["required"]), ["address", "model", "prompt"])
        self.assertEqual(spec["required"]["address"][1]["default"], "localhost")
        self.assertEqual(spec["optional"]["images"], ("IMAGE",))
        self.assertEqual(json.loads(spec["optional"]["settings"][1]["default"])["top_k"], 40)
        self.assertEqual(self.nodes.BartEasyOllama.RETURN_NAMES, ("text", "debug"))


if __name__ == "__main__":
    unittest.main()
