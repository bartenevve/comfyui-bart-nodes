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
    "num_ctx": (8192, 1024, 131072),
    "num_predict": (0, 0, 32768),
    "retries": (2, 0, 5),
    "timeout": (600, 10, 3600),
}
TEXT_FIELDS = ["request", "triggers", "dialogue", "text", "image", "start", "end", "refs"]

_CLIP_MARK = re.compile(r"^=== CLIP (\d+)(?: \((\d+) s\))? ===[ \t]*$", re.M)


class InputError(ValueError):
    """The widget values can't be turned into a request (bad URL, empty text, ...)."""


def normalize_url(url):
    """Base URL without a trailing slash; only http/https is accepted."""
    url = (url or "").strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise InputError(f"ollama_url must be an http(s) URL like http://host:11434, got: {url!r}")
    return url.rstrip("/")


def coerce_options(values):
    """Clean, typed copy of the widget values (`values` may come from JSON).

    Raises InputError naming the offending field.
    """
    out = {}
    for name, (default, low, high) in NUMERIC.items():
        raw = values.get(name, default)
        if isinstance(raw, bool) or raw in (None, ""):
            raw = default
        try:
            number = int(raw)
        except (TypeError, ValueError):
            raise InputError(f"{name} must be an integer, got {raw!r}") from None
        if not low <= number <= high:
            raise InputError(f"{name} must be {low}..{high}, got {number}")
        out[name] = number

    try:
        out["temperature"] = float(values.get("temperature", 0.3))
    except (TypeError, ValueError):
        raise InputError("temperature must be a number") from None
    if not 0.0 <= out["temperature"] <= 2.0:
        raise InputError(f"temperature must be 0..2, got {out['temperature']}")

    out["think"] = bool(values.get("think", False))
    out["append_no_think"] = bool(values.get("append_no_think", True))
    out["ollama_url"] = normalize_url(values.get("ollama_url"))
    out["model"] = str(values.get("model") or "").strip()
    if not out["model"]:
        raise InputError("model is empty")

    for name in TEXT_FIELDS:
        out[name] = str(values.get(name) or "")

    for name, allowed, default in (("aspect", ASPECTS, "16:9"), ("mode", MODES, "T2VA"), ("variant", VARIANTS, "auto")):
        value = str(values.get(name) or default)
        if value not in allowed:
            raise InputError(f"{name} must be one of {allowed}, got {value!r}")
        out[name] = value
    return out


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


def split_clips(text):
    """Inverse of join_clips; text with no marker is a single clip.

    Hand-edited saved text goes through here, so it is forgiving: whatever sits
    before the first marker is its own clip, empty clips are dropped.
    """
    text = text.strip()
    if not text:
        return []
    marks = list(_CLIP_MARK.finditer(text))
    if not marks:
        return [text]
    pieces = [text[: marks[0].start()]]
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        pieces.append(text[mark.end() : end])
    return [piece.strip() for piece in pieces if piece.strip()]


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
