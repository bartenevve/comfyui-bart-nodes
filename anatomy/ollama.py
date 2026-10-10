import json
import socket
import urllib.error
import urllib.parse
import urllib.request


class OllamaError(RuntimeError):
    pass


def normalize_url(url):
    """Base URL without a trailing slash; only http/https is accepted."""
    url = (url or "").strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise OllamaError(f"ollama_url must be an http(s) URL like http://host:11434, got: {url!r}")
    return url.rstrip("/")


def chat(url, model, prompt, image_b64, timeout=120, seed=0, num_ctx=4096):
    """One-shot vision question to Ollama's /api/chat, returns the answer text.

    Temperature 0 plus a fixed seed keeps repeated runs on the same image as
    stable as the model allows; `format: json` makes Ollama constrain the
    answer to valid JSON. `think: false` matters for thinking-capable models
    (qwen3-vl's default tag is one): left on, the answer arrives in a separate
    `thinking` field after a long ramble and `content` stays empty. `num_ctx`
    is pinned small because Ollama otherwise sizes the context from free
    memory - tens of GB on a big machine - which makes a one-image question
    needlessly slow; a checklist prompt + one image + a short JSON answer fit
    in 4096 comfortably.
    """
    endpoint = normalize_url(url) + "/api/chat"
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt, "images": [image_b64]}],
            "stream": False,
            "format": "json",
            "think": False,
            "options": {"temperature": 0, "seed": seed, "num_ctx": num_ctx, "num_predict": 1024},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", "")
        except Exception:
            pass
        raise OllamaError(f"ollama answered HTTP {exc.code} from {endpoint}: {detail or exc.reason}") from exc
    except (socket.timeout, TimeoutError) as exc:
        raise OllamaError(f"ollama did not answer within {timeout}s ({endpoint})") from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            raise OllamaError(f"ollama did not answer within {timeout}s ({endpoint})") from exc
        raise OllamaError(f"cannot reach ollama at {endpoint}: {exc.reason}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise OllamaError(f"ollama at {endpoint} returned a non-JSON response") from exc

    message = payload.get("message") or {}
    content = message.get("content", "")
    if not content.strip():
        if message.get("thinking"):
            raise OllamaError(
                f"model {model!r} spent its whole token budget thinking and never produced an "
                "answer (done_reason: " + str(payload.get("done_reason")) + "). For qwen3-family "
                "models keep append_no_think on; otherwise use a non-thinking model."
            )
        raise OllamaError(f"ollama returned an empty answer from model {model!r}")
    return content
