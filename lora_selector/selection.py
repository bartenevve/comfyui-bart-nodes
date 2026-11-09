"""The node's stack of LoRAs: parsing and checking the JSON the frontend keeps in a hidden widget, and the
text of the names output. Pure Python."""
import json
import math
import os

MAX_LORAS = 64
MAX_STRENGTH = 100.0  # ComfyUI's own LoRA loader accepts -100..100
MAX_NAME = 500


class StackError(ValueError):
    """The stack of LoRAs cannot be used."""


def _strength(value, what):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise StackError(f"{what} must be a number, got {value!r}")
    try:
        number = float(value)
    except ValueError:
        raise StackError(f"{what} must be a number, got {value!r}") from None
    if not math.isfinite(number) or abs(number) > MAX_STRENGTH:
        raise StackError(f"{what} must be between -{MAX_STRENGTH:g} and {MAX_STRENGTH:g}, got {value!r}")
    return number


def parse_stack(text):
    """The list of LoRAs the node holds: [{name, enabled, strength_model, strength_clip}], in order.

    `strength_clip` None means "the same as the model strength". Rows without a name (the empty row the
    editor keeps at the end) are dropped. Raises StackError naming the problem.
    """
    if not (text or "").strip():
        return []
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise StackError(f"loras is not valid JSON: {exc}") from None
    if not isinstance(data, list):
        raise StackError("loras must be a JSON list")
    if len(data) > MAX_LORAS:
        raise StackError(f"at most {MAX_LORAS} LoRAs fit on one node, got {len(data)}")
    stack = []
    for index, row in enumerate(data, 1):
        if not isinstance(row, dict):
            raise StackError(f"LoRA {index} must be an object")
        name = row.get("name", "")
        if not isinstance(name, str) or "\x00" in name or len(name) > MAX_NAME:
            raise StackError(f"LoRA {index} has an invalid name")
        if not name.strip():
            continue
        name = name.strip().replace("\\", "/")
        clip = row.get("strength_clip")
        stack.append({
            "name": name,
            "enabled": row.get("enabled", True) is not False,
            "strength_model": _strength(row.get("strength_model", 1.0), f"strength of {name}"),
            "strength_clip": None if clip in (None, "") else _strength(clip, f"clip strength of {name}"),
        })
    return stack


def serialize_stack(stack):
    """The JSON text `parse_stack` reads back."""
    return json.dumps(stack, ensure_ascii=False, separators=(",", ":"))


def active(stack):
    """The rows that change anything: switched on, and not both strengths zero."""
    out = []
    for row in stack:
        if not row["enabled"]:
            continue
        clip = row["strength_model"] if row["strength_clip"] is None else row["strength_clip"]
        if row["strength_model"] == 0 and clip == 0:
            continue
        out.append(row)
    return out


_MODEL_FAMILIES = (
    ("sdxl", "SDXL"), ("sd3", "SD 3"), ("flux", "Flux"), ("wan", "Wan"), ("hunyuan", "Hunyuan"),
    ("qwen", "Qwen"), ("ltx", "LTX"), ("sd15", "SD 1.x / 2.x"), ("sd20", "SD 1.x / 2.x"), ("sd21", "SD 1.x / 2.x"),
)
_SD12 = {"SD 1.x", "SD 2.x", "SD 1.x / 2.x"}


def family_from_class_name(name):
    """The model family of a ComfyUI model class name (`SDXL`, `Flux`, `WAN21`, ...), or "" when not known."""
    low = (name or "").lower()
    for needle, family in _MODEL_FAMILIES:
        if needle in low:
            return family
    return ""


def compatible(lora_family, model_family):
    """False only when both families are known and differ (Pony is SDXL; SD 1.x and 2.x are not told apart)."""
    if not lora_family or not model_family:
        return True
    left = "SDXL" if lora_family.startswith("SDXL") else lora_family
    right = "SDXL" if model_family.startswith("SDXL") else model_family
    return left == right or (left in _SD12 and right in _SD12)


def compatibility_warnings(rows, families, model_family):
    """One sentence for every applied LoRA that looks like it was made for another model family."""
    out = []
    for row in rows:
        family = families.get(row["name"], "")
        if not compatible(family, model_family):
            out.append(f"{short_name(row['name'])} looks like a {family} LoRA, but the connected model is {model_family}")
    return out


def trigger_words(infos):
    """The trigger words of the LoRAs in use, in order, without repeats, as one comma separated text."""
    seen = []
    for info in infos:
        for word in info.get("triggers", []):
            if word and word not in seen:
                seen.append(word)
    return ", ".join(seen)


def short_name(name):
    """`style/foo.safetensors` -> `foo`."""
    return os.path.splitext(name.replace("\\", "/").rsplit("/", 1)[-1])[0]


def names_text(rows):
    """The `lora_names` output: the LoRAs in use, comma separated."""
    return ", ".join(short_name(row["name"]) for row in rows)
