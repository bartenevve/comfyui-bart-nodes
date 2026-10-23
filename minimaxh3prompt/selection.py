import re
import urllib.parse

# Seed ceiling shared with the other Ollama node: well inside what a JS number
# (the frontend's widget storage) and Ollama's int64 both hold exactly.
MAX_SEED = 0x7FFFFFFF

ASPECTS = ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"]
MODES = ["T2VA", "I2VA", "FL2VA", "L2VA"]
VARIANTS = ["auto", "t2va", "i2va", "fl2va", "talking", "product", "ref", "story", "slots"]

# widget name -> (default, min, max) for the numeric options both the node and
# the button route read, so the two can never disagree on a limit
NUMERIC = {
    "duration": (8, 4, 120),
    "shots": (0, 0, 3),
    "seed": (0, 0, MAX_SEED),
    # the kit's prompts alone take 1.6-3k tokens (more with retries): a smaller window makes Ollama
    # cut the instructions off silently
    "num_ctx": (8192, 4096, 131072),
    "num_predict": (0, 0, 32768),
    "retries": (2, 0, 5),
    "timeout": (600, 10, 3600),
    # pixels of the short side for the width/height outputs; the H3 nodes work in steps of 32
    "short_side": (768, 256, 4096),
}

FPS = 24
SIZE_STEP = 32
TEXT_FIELDS = ["request", "triggers", "dialogue", "text", "image", "start", "end", "refs"]
MAX_TEXT = 20000  # characters per text field; the longest real request is a few hundred

_CLIP_MARK = re.compile(r"^=== CLIP (\d+)(?: \((\d+) s\))? ===[ \t]*$", re.M)


class InputError(ValueError):
    """The widget values can't be turned into a request (bad URL, empty text, ...)."""


def normalize_url(url):
    """Base URL without a trailing slash; only http(s) with a host.

    The request goes to `<url>/api/chat`, so the URL may carry a path prefix (Ollama behind a
    reverse proxy) but nothing that could move the end of that path: a query or fragment
    (`http://host/-/quit#` would otherwise POST to `/-/quit`), parameters, or credentials.
    """
    if url is not None and not isinstance(url, str):
        # the Generate route takes this straight from JSON: a number or list must be a 400, not an AttributeError
        raise InputError(f"ollama_url must be text like http://host:11434, got: {url!r}")
    url = (url or "").strip()
    try:
        parsed = urllib.parse.urlparse(url)
        _ = parsed.port  # raises ValueError for a port that is not a number
    except ValueError:
        raise InputError(f"ollama_url is not a valid URL: {url!r}") from None
    if parsed.scheme not in ("http", "https") or not parsed.netloc or not parsed.hostname:
        raise InputError(f"ollama_url must be an http(s) URL like http://host:11434, got: {url!r}")
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise InputError("ollama_url must not contain credentials (user:password@host)")
    if parsed.query or parsed.fragment or parsed.params or "?" in url or "#" in url or ";" in parsed.path:
        raise InputError(f"ollama_url must be just the server address (no ?query, #fragment or ;params): {url!r}")
    return url.rstrip("/")


def _as_bool(name, value, default):
    """A JSON/widget boolean. Text is read as text ("false" is not truthy), anything odd is an error."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in ("true", "false", "1", "0", "yes", "no", "on", "off"):
        return value.strip().lower() in ("true", "1", "yes", "on")
    raise InputError(f"{name} must be true or false, got {value!r}")


def coerce_options(values, server=True):
    """Clean, typed copy of the widget values (`values` may come from JSON).

    `server=False` is the CLIP backend: there is no Ollama, so `ollama_url` and `model` are not
    looked at (they stay empty). Raises InputError naming the offending field.
    """
    out = {}
    for name, (default, low, high) in NUMERIC.items():
        raw = values.get(name, default)
        if isinstance(raw, bool) or raw in (None, ""):
            raw = default
        try:
            number = int(raw)
        except (TypeError, ValueError, OverflowError):  # OverflowError: JSON 1e999 / Infinity
            raise InputError(f"{name} must be an integer, got {raw!r}") from None
        if not low <= number <= high:
            raise InputError(f"{name} must be {low}..{high}, got {number}")
        out[name] = number

    try:
        out["temperature"] = float(values.get("temperature", 0.3))
    except (TypeError, ValueError, OverflowError):
        raise InputError("temperature must be a number") from None
    if not 0.0 <= out["temperature"] <= 2.0:
        raise InputError(f"temperature must be 0..2, got {out['temperature']}")

    out["think"] = _as_bool("think", values.get("think"), False)
    out["append_no_think"] = _as_bool("append_no_think", values.get("append_no_think"), True)
    if server:
        out["ollama_url"] = normalize_url(values.get("ollama_url"))
        out["model"] = str(values.get("model") or "").strip()
        if not out["model"]:
            raise InputError("model is empty")
        if len(out["model"]) > 300:
            raise InputError("model name is too long")
    else:
        out["ollama_url"] = out["model"] = ""

    for name in TEXT_FIELDS:
        out[name] = str(values.get(name) or "")
        if len(out[name]) > MAX_TEXT:
            raise InputError(f"{name} is too long ({len(out[name])} characters, the limit is {MAX_TEXT})")

    for name, allowed, default in (("aspect", ASPECTS, "16:9"), ("mode", MODES, "T2VA"), ("variant", VARIANTS, "auto")):
        value = str(values.get(name) or default)
        if value not in allowed:
            raise InputError(f"{name} must be one of {allowed}, got {value!r}")
        out[name] = value
    return out


def frame_size(aspect, short_side):
    """(width, height) for an `aspect` such as "16:9", the short side being `short_side` px.

    Both sides are rounded DOWN to the H3 nodes' multiple of 32, so the frame
    never exceeds the pixel budget the user asked for (16:9 at 768 gives
    1344x768, which is also the H3 nodes' own default).
    """
    first, second = (int(part) for part in aspect.split(":"))
    short = short_side // SIZE_STEP * SIZE_STEP
    long_side = short * max(first, second) // min(first, second) // SIZE_STEP * SIZE_STEP
    return (long_side, short) if first >= second else (short, long_side)


def clip_durations(timed, total):
    """Seconds per clip for the `duration` / `frames` outputs.

    `timed` is split_timed_clips()'s list. A clip whose marker carries no
    duration (hand-edited text) gets an even share of `total`; a lone clip is
    the whole `total`.
    """
    even = max(1, round(total / max(len(timed), 1)))
    return [duration if duration else (total if len(timed) == 1 else even) for _, duration in timed]


def join_clips(clips, durations=None):
    """Saved-text form of a result. One clip is stored bare; several get a marker line each."""
    if len(clips) == 1:
        return clips[0]
    parts = []
    for number, clip in enumerate(clips, 1):
        duration = durations[number - 1] if durations else None
        mark = f"=== CLIP {number} ({duration} s) ===" if duration else f"=== CLIP {number} ==="
        parts.append(f"{mark}\n{clip}")
    return "\n\n".join(parts)


def split_timed_clips(text):
    """split_clips() that also returns each clip's marker duration (None when it has none)."""
    text = text.strip()
    if not text:
        return []
    marks = list(_CLIP_MARK.finditer(text))
    if not marks:
        return [(text, None)]
    pieces = [(text[: marks[0].start()], None)]
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        duration = int(mark.group(2)) if mark.group(2) else None
        pieces.append((text[mark.end() : end], duration))
    return [(piece.strip(), duration) for piece, duration in pieces if piece.strip()]


def split_clips(text):
    """Inverse of join_clips; text with no marker is a single clip.

    Hand-edited saved text goes through here, so it is forgiving: whatever sits
    before the first marker is its own clip, empty clips are dropped.
    """
    return [clip for clip, _ in split_timed_clips(text)]


def format_report(variant, clips, errors, warnings):
    lines = [f"variant: {variant}", f"clips: {clips}"]
    if warnings:
        lines.append("warnings: " + "; ".join(warnings))
    if errors:
        lines.append("remaining validator errors:")
        lines.extend(f"- {error}" for error in errors)
    else:
        lines.append("validator: OK")
    return "\n".join(lines)
