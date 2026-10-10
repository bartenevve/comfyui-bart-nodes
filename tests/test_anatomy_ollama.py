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

ollama = module("anatomy.ollama")


class FakeResponse:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def answer(content):
    return FakeResponse({"message": {"role": "assistant", "content": content}})


class TestNormalizeUrl(unittest.TestCase):
    def test_strips_trailing_slash(self):
        self.assertEqual(ollama.normalize_url(" http://host:11434/ "), "http://host:11434")

    def test_rejects_other_schemes_and_garbage(self):
        for bad in ("", "host:11434", "file:///etc/passwd", "ftp://host", "http://"):
            with self.subTest(bad=bad), self.assertRaises(ollama.OllamaError):
                ollama.normalize_url(bad)


class TestChat(unittest.TestCase):
    def call(self, **kwargs):
        return ollama.chat("http://h:11434", "m", "prompt", "B64", **kwargs)

    def test_returns_message_content_and_sends_expected_request(self):
        with mock.patch.object(ollama.urllib.request, "urlopen", return_value=answer('{"ok": 1}')) as urlopen:
            self.assertEqual(self.call(timeout=7, seed=3), '{"ok": 1}')
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://h:11434/api/chat")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 7)
        body = json.loads(request.data)
        self.assertEqual(body["model"], "m")
        self.assertEqual(body["messages"][0]["images"], ["B64"])
        self.assertEqual(body["format"], "json")
        self.assertFalse(body["stream"])
        self.assertEqual(body["options"], {"temperature": 0, "seed": 3})

    def test_http_error_includes_server_message(self):
        error = urllib.error.HTTPError(
            "http://h", 404, "Not Found", {}, io.BytesIO(b'{"error": "model \\"m\\" not found"}')
        )
        with mock.patch.object(ollama.urllib.request, "urlopen", side_effect=error):
            with self.assertRaisesRegex(ollama.OllamaError, "404.*not found"):
                self.call()

    def test_unreachable_host(self):
        with mock.patch.object(
            ollama.urllib.request, "urlopen", side_effect=urllib.error.URLError(ConnectionRefusedError("refused"))
        ):
            with self.assertRaisesRegex(ollama.OllamaError, "cannot reach"):
                self.call()

    def test_timeouts_are_reported_as_timeouts(self):
        for exc in (socket.timeout(), urllib.error.URLError(socket.timeout())):
            with self.subTest(exc=type(exc).__name__):
                with mock.patch.object(ollama.urllib.request, "urlopen", side_effect=exc):
                    with self.assertRaisesRegex(ollama.OllamaError, "did not answer within"):
                        self.call(timeout=5)

    def test_empty_answer_is_an_error(self):
        with mock.patch.object(ollama.urllib.request, "urlopen", return_value=answer("  ")):
            with self.assertRaisesRegex(ollama.OllamaError, "empty answer"):
                self.call()

    def test_non_json_body_is_an_error(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"<html>proxy error</html>"
        with mock.patch.object(ollama.urllib.request, "urlopen", return_value=response):
            with self.assertRaisesRegex(ollama.OllamaError, "non-JSON"):
                self.call()


if __name__ == "__main__":
    unittest.main()
