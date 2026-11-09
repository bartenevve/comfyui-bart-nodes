"""Pure logic of Simple concatenate: turning values into text and joining them. No ComfyUI, no torch."""
import json
import re

DEFAULT_SEPARATOR = "\\n"  # typed as the two characters backslash-n; it means a line break (see unescape)
MAX_DEPTH = 8  # lists inside lists inside lists: deep enough for anything a graph produces

_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\"}
_ESCAPE = re.compile(r"\\([ntr\\])")


class TextError(ValueError):
    """A value that cannot be turned into text."""


def unescape(separator):
    """The separator as typed: `\\n` is a line break, `\\t` a tab, `\\r` a carriage return, `\\\\` one backslash.

    A single-line box cannot show a real line break, so the default is typed as `\\n`. Any other backslash is
    kept as it is.
    """
    return _ESCAPE.sub(lambda match: _ESCAPES[match.group(1)], separator or "")


def to_text(value, name="input", depth=0):
    """The text of one value; None means "nothing here" and gives None.

    Strings are kept as they are, numbers and booleans are written the way Python writes them (`3`, `0.25`,
    `True`), a dictionary becomes JSON. Anything else (an image, a model, a latent, ...) is refused with a message
    that names the input and the kind of thing it is, instead of producing `<object at 0x...>`. A list or tuple is
    handled by `texts_of`, which turns each of its items into text.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value)
    if hasattr(value, "item") and type(value).__module__.split(".")[0] == "numpy" and getattr(value, "ndim", 1) == 0:
        return to_text(value.item(), name, depth)  # a numpy scalar
    if isinstance(value, dict):
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=False)
        except (TypeError, ValueError):
            pass
    raise TextError(f"{name} is {_kind(value)}, which cannot be turned into text")


def texts_of(value, name="input", depth=0):
    """A list of texts from one input: a list or tuple contributes each of its items (they are joined with the
    separator like separate inputs), anything else contributes its own text, None contributes nothing."""
    if isinstance(value, (list, tuple)):
        if depth >= MAX_DEPTH:
            raise TextError(f"{name} is nested too deeply to turn into text")
        out = []
        for item in value:
            out.extend(texts_of(item, name, depth + 1))
        return out
    text = to_text(value, name)
    return [] if text is None else [text]


def _kind(value):
    kind = type(value).__name__
    return ("an " if kind[:1].lower() in "aeiou" else "a ") + kind


def slot_order(name):
    """Sort key of an input name such as `text0`, `text1`, `text10`: by the number, not alphabetically."""
    match = re.search(r"(\d+)$", name)
    return (int(match.group(1)) if match else 0, name)


def join_texts(values, separator=DEFAULT_SEPARATOR):
    """The inputs joined with the separator. `values` is a dict {input name: value} (in slot order) or a list.

    Inputs that hold nothing (None: a slot nothing is connected to) are skipped; an empty string is a text like
    any other and keeps its place; a list contributes each of its items.
    """
    items = sorted(values.items(), key=lambda pair: slot_order(pair[0])) if isinstance(values, dict) else [
        (f"input {index}", value) for index, value in enumerate(values, 1)
    ]
    texts = []
    for name, value in items:
        texts.extend(texts_of(value, name))
    return unescape(separator).join(texts)
