"""Everything of the Ollama node that needs neither torch nor ComfyUI: the address, the settings JSON,
the request body, the HTTP call and the debug report. Nothing here limits `num_ctx` (or any other
option): what the user writes is what Ollama receives."""
import http.client
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_ADDRESS = "localhost"
DEFAULT_PORT = 11434
DEFAULT_TIMEOUT = 900  # seconds: a vision model on a big context can think for minutes
MAX_RESPONSE_BYTES = 64 * 1024 * 1024
MAX_ERROR_CHARS = 4000  # of a server's error body / reasoning shown in the debug text
HUGE_CONTEXT = 65536  # a context this big is almost never wanted: it is what makes a small model eat tens of GB

# What the settings box is filled with: Ollama's documented defaults of the options people actually
# touch, plus a context of 8192. The context is the node's own choice, not Ollama's: left to the server
# it can be huge (a 1.7B vision model was loaded with 262144 and took 33 GB), and 8192 holds a few
# images plus a long prompt. Delete the line and the server's own limit applies again.
DEFAULT_OPTIONS = {
    "temperature": 0.8,
    "top_k": 40,
    "top_p": 0.9,
    "min_p": 0.0,
    "repeat_penalty": 1.1,
    "repeat_last_n": 64,
    "seed": -1,  # random. Ollama's docs say 0, but 0 is a FIXED seed there (the same answer every time)
    "num_predict": -1,
    "num_ctx": 8192,
}
DEFAULT_SETTINGS = json.dumps(DEFAULT_OPTIONS, indent=2)

# keys of the settings JSON that are not model options: they go at the top level of the request
# (Ollama's own fields) or steer the node
TOP_LEVEL_KEYS = ("think", "keep_alive", "format", "system")
NODE_KEYS = ("timeout", "image_max_side")
DEFAULT_IMAGE_MAX_SIDE = 2048


class SettingsError(ValueError):
    """The address or the settings JSON cannot be used."""


def normalize_address(text):
    """`scheme://host:port[/prefix]` from what the user typed.

    "localhost", "192.168.1.5", "myhost:11500" and "https://proxy.example/ollama" all work; a bare host
    gets http and Ollama's port 11434. Credentials, a query, a fragment and other schemes are refused.
    """
    raw = (text or "").strip() or DEFAULT_ADDRESS
    if len(raw) > 2000 or any(ch in raw for ch in "\x00\r\n \t"):
        raise SettingsError("address is not a valid URL")
    if "://" not in raw:
        raw = "http://" + raw
    try:
        parts = urllib.parse.urlsplit(raw)
        port = parts.port
    except ValueError:
        raise SettingsError(f"address is not a valid URL: {text!r}") from None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise SettingsError("address must be an http(s) address such as localhost or http://host:11434")
    if parts.username is not None or parts.password is not None:
        raise SettingsError("address must not contain credentials (user:password@host)")
    if parts.query or parts.fragment or ";" in parts.path:
        raise SettingsError("address must be just the server (no ?query, #fragment or ;params)")
    netloc = parts.netloc
    if port is None and "://" not in (text or "").strip():  # a bare host: Ollama's own port
        netloc = f"{netloc}:{DEFAULT_PORT}"
    return f"{parts.scheme}://{netloc}{parts.path.rstrip('/')}"


def parse_settings(text):
    """(options, top_level, node): the settings JSON split by where each key belongs.

    An empty text means no settings. Values are passed on untouched - no range is enforced here, the
    server decides what it can do (a `num_ctx` of 8192, 131072 or anything else reaches it as written).
    """
    if not (text or "").strip():
        return {}, {}, {}
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise SettingsError(f"settings is not valid JSON: {exc}") from None
    if not isinstance(data, dict):
        raise SettingsError("settings must be a JSON object, like {\"temperature\": 0.8}")
    top = {key: data[key] for key in TOP_LEVEL_KEYS if key in data}
    node = {key: data[key] for key in NODE_KEYS if key in data}
    options = {key: value for key, value in data.items() if key not in TOP_LEVEL_KEYS and key not in NODE_KEYS}
    return options, top, node


def node_number(node, key, default, low):
    """A numeric node-level setting (timeout, image_max_side), with its default and a lower bound."""
    value = node.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value or value < low:
        raise SettingsError(f"{key} must be a number of at least {low}, got {value!r}")
    return value


def is_random_seed(options):
    """True when Ollama will choose the seed itself (none, or a negative one): every run is a new take."""
    seed = options.get("seed", -1)
    return isinstance(seed, bool) or not isinstance(seed, (int, float)) or seed < 0


def build_body(model, prompt, images, options, top):
    message = {"role": "user", "content": prompt}
    if images:
        message["images"] = list(images)
    body = {"model": model, "messages": [message], "stream": False}
    if options:
        body["options"] = options
    body.update(top)
    return body


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect would send the prompt (and the images) to a place the user did not name."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def post_chat(base, body, timeout):
    """(HTTP status, response text). An HTTP error status is returned, not raised."""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        base + "/api/chat", data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            status, raw = response.status, response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        try:
            status, raw = exc.code, exc.read(MAX_RESPONSE_BYTES + 1)
        finally:
            exc.close()
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError(f"the response is larger than {MAX_RESPONSE_BYTES} bytes")
    return status, raw.decode("utf-8", errors="replace")


def get_loaded(base, model, timeout=5):
    """What the server holds in memory for `model` (from /api/ps), or None: {context, size, size_vram}.

    Best effort: an older server, a proxy without /api/ps or a model that already left memory is not an error.
    """
    try:
        with _OPENER.open(urllib.request.Request(base + "/api/ps"), timeout=timeout) as response:
            data = json.loads(response.read(1024 * 1024))
    except (OSError, ValueError, http.client.HTTPException):
        return None
    models = data.get("models") if isinstance(data, dict) else None
    for entry in models if isinstance(models, list) else []:
        if isinstance(entry, dict) and model in (entry.get("name"), entry.get("model")):
            return {key: entry.get(key) for key in ("context_length", "size", "size_vram")}
    return None


def describe_loaded(loaded, options):
    """Debug lines about the model's footprint on the server, and a warning when the server picked a huge context."""
    if not loaded:
        return []
    context, size, vram = loaded.get("context_length"), loaded.get("size"), loaded.get("size_vram")
    parts = []
    if isinstance(context, int):
        parts.append(f"context {context}")
    if isinstance(size, (int, float)) and size:
        parts.append(f"{size / 2**30:.1f} GB")
        if isinstance(vram, (int, float)):
            parts.append(f"{100 * vram / size:.0f}% on GPU")
    if not parts:
        return []
    lines = ["loaded by the server: " + " | ".join(parts)]
    if "num_ctx" not in options and isinstance(context, int) and context >= HUGE_CONTEXT:
        lines.append(
            f"WARNING: the server loaded this model with a context of {context}"
            + (f" ({size / 2**30:.0f} GB of memory)" if isinstance(size, (int, float)) and size else "")
            + ". Set num_ctx in settings (for example 8192) or OLLAMA_CONTEXT_LENGTH on the server to keep it small."
        )
    return lines


def _clip(text, limit=MAX_ERROR_CHARS):
    text = str(text)
    return text if len(text) <= limit else text[:limit] + f"... [{len(text) - limit} more characters]"


def _seconds(nanoseconds):
    return f"{nanoseconds / 1e9:.1f} s" if isinstance(nanoseconds, (int, float)) else "?"


def describe_response(data, options):
    """Debug lines about a successful answer: why it stopped, how many tokens, and a truncation warning."""
    lines = []
    keys = ("done_reason", "prompt_eval_count", "eval_count", "total_duration", "load_duration")
    facts = [f"{key}: {_seconds(data[key]) if key.endswith('duration') else data[key]}" for key in keys if key in data]
    if facts:
        lines.append(" | ".join(facts))
    wanted = options.get("num_ctx")
    seen = data.get("prompt_eval_count")
    if isinstance(wanted, (int, float)) and isinstance(seen, int) and 0 < wanted <= seen:
        lines.append(
            f"WARNING: the prompt used {seen} tokens, the whole context of {int(wanted)}: Ollama probably cut off "
            "the start of it. Raise num_ctx."
        )
    elif wanted is None and isinstance(seen, int):
        lines.append(f"num_ctx not set: the server's own limit applies (it processed {seen} prompt tokens).")
    return lines


def run(address, model, prompt, images=(), settings=""):
    """Ask Ollama. Returns (text, debug): never raises, every failure is described in `debug`."""
    debug = []
    try:
        base = normalize_address(address)
        model = (model or "").strip()
        if not model:
            raise SettingsError("model is empty")
        if not (prompt or "").strip():
            raise SettingsError("prompt is empty")
        options, top, node = parse_settings(settings)
        timeout = node_number(node, "timeout", DEFAULT_TIMEOUT, 1)
        body = build_body(model, prompt, images, options, top)
    except SettingsError as exc:
        return "", f"ERROR: {exc}"

    size = len(json.dumps(body, ensure_ascii=False).encode("utf-8"))
    debug.append(f"POST {base}/api/chat | model: {model} | images: {len(images)} | request: {size / 1e6:.2f} MB")
    debug.append(f"options: {json.dumps(options, ensure_ascii=False)}" + (f" | top-level: {json.dumps(top)}" if top else ""))
    started = time.monotonic()
    try:
        status, raw = post_chat(base, body, timeout)
    except (socket.timeout, TimeoutError):
        debug.append(f"ERROR: no answer within {timeout} s (set \"timeout\" in settings to wait longer)")
        return "", "\n".join(debug)
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, (socket.timeout, TimeoutError)):
            debug.append(f"ERROR: no answer within {timeout} s (set \"timeout\" in settings to wait longer)")
        else:
            debug.append(f"ERROR: cannot reach {base}: {reason}")
        return "", "\n".join(debug)
    except (http.client.HTTPException, OSError, ValueError) as exc:
        debug.append(f"ERROR: the connection failed ({type(exc).__name__}: {_clip(exc, 300)})")
        return "", "\n".join(debug)
    debug.append(f"HTTP {status} in {time.monotonic() - started:.1f} s")

    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    if status != 200:
        detail = data.get("error") if isinstance(data, dict) and "error" in data else raw
        debug.append(f"ERROR: the server answered HTTP {status}: {_clip(detail)}")
        return "", "\n".join(debug)
    if not isinstance(data, dict):
        debug.append(f"ERROR: the answer is not JSON: {_clip(raw, 800)}")
        return "", "\n".join(debug)
    if "error" in data:
        debug.append(f"ERROR: {_clip(data['error'])}")
        return "", "\n".join(debug)

    message = data.get("message") if isinstance(data.get("message"), dict) else {}
    text = message.get("content") or ""
    debug.extend(describe_response(data, options))
    debug.extend(describe_loaded(get_loaded(base, model), options))
    thinking = message.get("thinking")
    if thinking:
        debug.append(f"thinking ({len(thinking)} characters): {_clip(thinking, 1500)}")
    if not text.strip():
        debug.append(
            "WARNING: the answer is empty."
            + (" The model only produced reasoning: try {\"think\": false} or a larger num_predict." if thinking else "")
        )
    return text.strip(), "\n".join(debug)
