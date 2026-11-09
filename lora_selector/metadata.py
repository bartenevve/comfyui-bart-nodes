"""What can be learned about a LoRA file without loading it: the safetensors header (training metadata and
tensor names), the sidecar files other tools leave next to it, and the user's own notes. Pure Python: no
torch, no ComfyUI. Nothing here executes or unpickles anything - only a JSON header is read."""
import html
import json
import math
import os
import re
import struct
import threading

MAX_HEADER_BYTES = 32 * 1024 * 1024  # a kohya header with a big tag frequency table is a few MB
MAX_SIDECAR_BYTES = 2 * 1024 * 1024
MAX_TRIGGERS = 50
MAX_TEXT = 2000
MAX_TAG_CHARS = 100

PREVIEW_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
PREVIEW_SUFFIXES = (".preview", "")  # foo.preview.png (A1111 / Civitai Helper), then foo.png

_CACHE = {}
_CACHE_LOCK = threading.Lock()
MAX_CACHE = 4096


def _number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
        return number if math.isfinite(number) else None
    return None


_TAG = re.compile(r"<[^>]*>")


def _text(value, limit=MAX_TEXT):
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return ""
    return " ".join(str(value).split())[:limit]


def _plain(value, limit=MAX_TEXT):
    """Text from HTML (Civitai descriptions are): tags dropped, entities decoded, white space squeezed."""
    if not isinstance(value, str):
        return ""
    return " ".join(html.unescape(_TAG.sub(" ", value)).split())[:limit]


def read_header(path):
    """(metadata dict of strings, list of tensor names) from a .safetensors file, or ({}, []) for anything else.

    Only the JSON header is read, bounded in size. A file that is not safetensors (.pt, .ckpt, .bin: pickles,
    which are never opened here) or that is damaged yields nothing.
    """
    if not path.lower().endswith(".safetensors"):
        return {}, []
    try:
        with open(path, "rb") as handle:
            raw = handle.read(8)
            if len(raw) != 8:
                return {}, []
            (length,) = struct.unpack("<Q", raw)
            if length <= 0 or length > MAX_HEADER_BYTES:
                return {}, []
            header = json.loads(handle.read(length))
    except (OSError, ValueError, struct.error, RecursionError):
        return {}, []
    if not isinstance(header, dict):
        return {}, []
    metadata = header.get("__metadata__")
    metadata = {str(k): v for k, v in metadata.items() if isinstance(v, str)} if isinstance(metadata, dict) else {}
    return metadata, [key for key in header if key != "__metadata__"]


# ---------------------------------------------------------------- family ----

def _family_from_text(text):
    low = (text or "").lower()
    if not low:
        return ""
    if "pony" in low:
        return "SDXL (Pony)"
    if "flux" in low:
        return "Flux"
    if "sdxl" in low or "stable-diffusion-xl" in low or "xl" == low:
        return "SDXL"
    if "sd3" in low or "stable-diffusion-3" in low:
        return "SD 3"
    if "stable-diffusion-v2" in low or low.startswith(("sd_v2", "sd2", "sd-2")) or "sd 2" in low:
        return "SD 2.x"
    if "stable-diffusion-v1" in low or low.startswith(("sd_v1", "sd1", "sd-1")) or "sd 1" in low:
        return "SD 1.x"
    if "wan" in low:
        return "Wan"
    if "hunyuan" in low:
        return "Hunyuan"
    if "qwen" in low:
        return "Qwen"
    if "z-image" in low or "z_image" in low:
        return "Z-Image"
    if "ltx" in low:
        return "LTX"
    return ""


def family_from_keys(keys):
    """A guess from the tensor names, for files that carry no metadata."""
    joined = "\n".join(keys[:4000])
    if "lora_te2_" in joined or "text_encoder_2" in joined or "lora_unet_input_blocks" in joined:
        return "SDXL"
    if "double_blocks" in joined or "single_blocks" in joined or "single_transformer_blocks" in joined:
        return "Flux"
    if "joint_blocks" in joined:
        return "SD 3"
    if "lora_unet_down_blocks" in joined or "lora_unet_mid_block" in joined or "lora_te_text_model" in joined:
        return "SD 1.x / 2.x"
    return ""


def detect_family(metadata, keys):
    for key in ("modelspec.architecture", "ss_base_model_version", "modelspec.implementation"):
        family = _family_from_text(metadata.get(key, ""))
        if family:
            if family == "SDXL" and "pony" in (metadata.get("ss_sd_model_name", "") + metadata.get("modelspec.title", "")).lower():
                return "SDXL (Pony)"
            return family
    if metadata.get("ss_v2", "").lower() == "true":
        return "SD 2.x"
    return family_from_keys(keys) or ""


def frequent_tags(metadata, limit=15):
    """The most frequent tags of the training set (kohya's ss_tag_frequency): often the trigger words."""
    raw = metadata.get("ss_tag_frequency")
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        return []
    totals = {}
    for tags in data.values() if isinstance(data, dict) else []:
        for tag, count in (tags.items() if isinstance(tags, dict) else []):
            number = _number(count)
            if number is not None and isinstance(tag, str):
                totals[tag.strip()] = totals.get(tag.strip(), 0) + number
    ranked = sorted(((count, tag) for tag, count in totals.items() if tag), key=lambda item: (-item[0], item[1]))
    return [tag[:MAX_TAG_CHARS] for _, tag in ranked[:limit]]


def training_info(metadata):
    """The training facts worth showing, as {label: text}."""
    out = {}
    for label, key in (
        ("trained on", "ss_sd_model_name"),
        ("network dim", "ss_network_dim"),
        ("network alpha", "ss_network_alpha"),
        ("resolution", "ss_resolution"),
        ("epochs", "ss_epoch"),
        ("images", "ss_num_train_images"),
        ("clip skip", "ss_clip_skip"),
        ("comment", "ss_training_comment"),
        ("title", "modelspec.title"),
        ("author", "modelspec.author"),
        ("description", "modelspec.description"),
    ):
        value = _text(metadata.get(key, ""), 400)
        if value and value.lower() not in ("none", "null"):
            out[label] = value
    return out


# ------------------------------------------------------------- sidecars ----

def sidecar_paths(path):
    base = os.path.splitext(path)[0]
    return {"civitai": base + ".civitai.info", "json": base + ".json"}


def _read_json(path):
    try:
        if os.path.getsize(path) > MAX_SIDECAR_BYTES:
            return None
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, RecursionError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _split_words(text):
    return [word.strip() for word in re.split(r"[,\n]", text) if word.strip()]


def read_sidecars(path):
    """What Civitai Helper (`foo.civitai.info`) and the A1111 LoRA tab (`foo.json`) wrote next to the file:
    {triggers, strength, description, base_model, civitai, sampler settings, negative}."""
    out = {"triggers": [], "triggers_source": "", "strength": None, "description": "", "base_model": "",
           "civitai": {}, "settings": {}, "negative": ""}
    paths = sidecar_paths(path)
    info = _read_json(paths["civitai"])
    if info:
        words = info.get("trainedWords")
        if isinstance(words, list):
            out["triggers"] = [_text(w, MAX_TAG_CHARS) for w in words if _text(w, MAX_TAG_CHARS)][:MAX_TRIGGERS]
            out["triggers_source"] = "Civitai"
        out["base_model"] = _text(info.get("baseModel"), 100)
        model = info.get("model") if isinstance(info.get("model"), dict) else {}
        out["civitai"] = {k: v for k, v in (("model", _text(model.get("name"), 200)), ("version", _text(info.get("name"), 200)),
                                           ("type", _text(model.get("type"), 40))) if v}
        out["description"] = _plain(info.get("description") or model.get("description"), 600)
        for image in info.get("images") if isinstance(info.get("images"), list) else []:
            meta = image.get("meta") if isinstance(image, dict) and isinstance(image.get("meta"), dict) else None
            if meta:
                settings = {k: _text(meta.get(key), 60) for k, key in (("sampler", "sampler"), ("steps", "steps"), ("cfg", "cfgScale"), ("clip skip", "clipSkip")) if _text(meta.get(key), 60)}
                if settings:
                    out["settings"] = settings
                    break
    user = _read_json(paths["json"])
    if user:
        words = _split_words(_text(user.get("activation text"), 2000))
        if words and not out["triggers"]:
            out["triggers"], out["triggers_source"] = words[:MAX_TRIGGERS], "sidecar .json"
        weight = _number(user.get("preferred weight"))
        if weight:
            out["strength"] = weight
        out["negative"] = out["negative"] or _text(user.get("negative text"), 400)
        out["description"] = out["description"] or _plain(user.get("description") or user.get("notes"), 600)
        out["base_model"] = out["base_model"] or _text(user.get("sd version"), 100)
    return out


def find_preview(path):
    base = os.path.splitext(path)[0]
    for suffix in PREVIEW_SUFFIXES:
        for extension in PREVIEW_EXTENSIONS:
            candidate = base + suffix + extension
            if os.path.isfile(candidate):
                return candidate
    return None


# ---------------------------------------------------------------- notes ----

_NOTES_LOCK = threading.Lock()


def load_notes(path):
    """The user's own notes {name: {triggers, strength, text}} (an empty dict when there are none)."""
    data = _read_json(path) if path and os.path.isfile(path) else None
    return data if isinstance(data, dict) else {}


def clean_note(note):
    """A note from the editor, checked and bounded; ValueError names what is wrong."""
    if not isinstance(note, dict):
        raise ValueError("the note must be a JSON object")
    triggers = note.get("triggers", [])
    if isinstance(triggers, str):
        triggers = _split_words(triggers)
    if not isinstance(triggers, list) or len(triggers) > MAX_TRIGGERS:
        raise ValueError(f"triggers must be a list of at most {MAX_TRIGGERS} words")
    cleaned = []
    for word in triggers:
        word = _text(word, MAX_TAG_CHARS) if isinstance(word, (str, int, float)) else ""
        if word and word not in cleaned:
            cleaned.append(word)
    strength = note.get("strength")
    if strength in (None, ""):
        strength = None
    else:
        strength = _number(strength)
        if strength is None or not -100 <= strength <= 100:
            raise ValueError("strength must be a number between -100 and 100")
    text = note.get("text", "")
    if not isinstance(text, str) or len(text) > MAX_TEXT:
        raise ValueError(f"text must be a string of at most {MAX_TEXT} characters")
    return {"triggers": cleaned, "strength": strength, "text": text.strip()}


def save_note(path, name, note):
    """Store `note` for `name` (an empty note removes the entry). Atomic: a crash never leaves half a file."""
    note = clean_note(note)
    with _NOTES_LOCK:
        notes = load_notes(path)
        if note["triggers"] or note["strength"] is not None or note["text"]:
            notes[name] = note
        else:
            notes.pop(name, None)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        temporary = f"{path}.{os.getpid()}.{threading.get_ident()}.part"
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(notes, handle, ensure_ascii=False, indent=1)
            os.replace(temporary, path)
        finally:
            try:
                os.remove(temporary)
            except OSError:
                pass
    return note


# ----------------------------------------------------------------- info ----

def _header_cached(path):
    try:
        stat = os.stat(path)
    except OSError:
        return {}, [], None
    key = (path, stat.st_mtime_ns, stat.st_size)
    with _CACHE_LOCK:
        if key in _CACHE:
            return _CACHE[key] + (stat,)
    metadata, keys = read_header(path)
    family_keys = family_from_keys(keys)
    # tensor names are only needed for the family guess: keep the guess, not thousands of strings
    value = (metadata, family_keys)
    with _CACHE_LOCK:
        if len(_CACHE) >= MAX_CACHE:
            _CACHE.clear()
        _CACHE[key] = value
    return metadata, family_keys, stat


def lora_info(path, name, notes=None):
    """Everything known about one LoRA, as a JSON-able dict (see README: Lora Selector)."""
    metadata, keys_family, stat = _header_cached(path)
    side = read_sidecars(path)
    note = (notes or {}).get(name) if isinstance((notes or {}).get(name), dict) else {}
    family = detect_family(metadata, []) or keys_family or _family_from_text(side["base_model"])
    mine = [w for w in (note.get("triggers") or []) if isinstance(w, str)]
    triggers, source = (mine, "my notes") if mine else (side["triggers"], side["triggers_source"])
    strength = _number(note.get("strength")) if note.get("strength") is not None else side["strength"]
    base = os.path.basename(name)
    return {
        "name": name,
        "file": os.path.splitext(base)[0],
        "size": stat.st_size if stat else 0,
        "mtime": stat.st_mtime if stat else 0,
        "format": os.path.splitext(base)[1].lower().lstrip("."),
        "readable": bool(metadata) or base.lower().endswith(".safetensors"),
        "family": family,
        "base_model": side["base_model"],
        "triggers": triggers,
        "triggers_source": source,
        "frequent_tags": frequent_tags(metadata),
        "strength": strength,
        "strength_source": "my notes" if note.get("strength") is not None else ("sidecar" if side["strength"] else ""),
        "settings": side["settings"],
        "negative": side["negative"],
        "description": side["description"],
        "civitai": side["civitai"],
        "training": training_info(metadata),
        "notes": {"triggers": mine, "strength": _number(note.get("strength")), "text": _text(note.get("text"), MAX_TEXT) if isinstance(note.get("text"), str) else ""},
        "has_preview": find_preview(path) is not None,
    }


def summary(info):
    """The light version of `lora_info` for the list on the picker screen."""
    keys = ("name", "file", "size", "mtime", "format", "family", "strength", "has_preview")
    out = {key: info[key] for key in keys}
    # all of them: the picker's search looks through the trigger words (and the frequent training tags) too
    out["triggers"] = info["triggers"]
    out["frequent_tags"] = info["frequent_tags"]
    out["base_model"] = info["base_model"] or info["training"].get("trained on", "")
    return out
