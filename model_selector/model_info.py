"""What can be learned about a model file without loading it: the safetensors header (tensor names, shapes and
types, training metadata) or the GGUF header, and from them the kind of file (a full checkpoint, a diffusion
model, a text encoder, a VAE, a CLIP vision model), the model family, the precision and the parameter count.
Pure Python: no torch, no ComfyUI. Nothing here executes or unpickles anything - only headers are read."""
import json
import os
import re
import struct
import threading

MAX_HEADER_BYTES = 64 * 1024 * 1024  # a big checkpoint's header is a few MB; refuse anything absurd
MAX_KEYS_SCANNED = 60000
GGUF_MAGIC = b"GGUF"
MAX_GGUF_KEYS = 256

SAFE_EXTENSIONS = (".safetensors", ".sft")
PICKLE_EXTENSIONS = (".ckpt", ".pt", ".pth", ".bin")
MODEL_EXTENSIONS = SAFE_EXTENSIONS + PICKLE_EXTENSIONS + (".gguf",)

CHECKPOINT, DIFFUSION, TEXT_ENCODER, VAE, CLIP_VISION, UNKNOWN = (
    "checkpoint", "diffusion model", "text encoder", "VAE", "CLIP vision", "unknown")
KINDS = (CHECKPOINT, DIFFUSION, TEXT_ENCODER, VAE, CLIP_VISION)

# what each kind of file hands to the rest of the graph
OUTPUTS = {
    CHECKPOINT: ["MODEL", "CLIP", "VAE"],
    DIFFUSION: ["MODEL"],
    TEXT_ENCODER: ["CLIP"],
    VAE: ["VAE"],
    CLIP_VISION: ["CLIP_VISION"],
    UNKNOWN: [],
}

# the kind a ComfyUI model folder implies (used when the file itself says nothing)
FOLDER_KINDS = {
    "checkpoints": CHECKPOINT,
    "diffusion_models": DIFFUSION, "unet": DIFFUSION, "unet_gguf": DIFFUSION,
    "text_encoders": TEXT_ENCODER, "clip": TEXT_ENCODER, "clip_gguf": TEXT_ENCODER,
    "vae": VAE,
    "clip_vision": CLIP_VISION,
}

_BYTES = {"F64": 8, "F32": 4, "F16": 2, "BF16": 2, "F8_E4M3": 1, "F8_E5M2": 1, "F8_E8M0": 1, "I64": 8, "I32": 4, "I16": 2,
          "I8": 1, "U8": 1, "U16": 2, "U32": 4, "U64": 8, "BOOL": 1}
_PRECISION = {"F32": "fp32", "F16": "fp16", "BF16": "bf16", "F8_E4M3": "fp8", "F8_E5M2": "fp8", "F8_E8M0": "fp8",
              "I8": "int8", "U8": "int8", "F64": "fp64"}

_CACHE = {}
_CACHE_LOCK = threading.Lock()
MAX_CACHE = 4096


# ---------------------------------------------------------------- headers ----

def read_safetensors(path):
    """(metadata of strings, {tensor name: (dtype, shape)}) of a .safetensors file; ({}, {}) when it is not one.

    Only the JSON header is read, bounded in size. Anything damaged, absurd or not safetensors yields nothing.
    """
    try:
        with open(path, "rb") as handle:
            raw = handle.read(8)
            if len(raw) != 8:
                return {}, {}
            (length,) = struct.unpack("<Q", raw)
            if length <= 0 or length > MAX_HEADER_BYTES:
                return {}, {}
            header = json.loads(handle.read(length))
    except (OSError, ValueError, struct.error, RecursionError, MemoryError):
        return {}, {}
    if not isinstance(header, dict):
        return {}, {}
    metadata = header.get("__metadata__")
    metadata = {str(k): v for k, v in metadata.items() if isinstance(v, str)} if isinstance(metadata, dict) else {}
    tensors = {}
    for name, entry in header.items():
        if name == "__metadata__" or len(tensors) >= MAX_KEYS_SCANNED:
            continue
        if isinstance(entry, dict) and isinstance(entry.get("dtype"), str) and isinstance(entry.get("shape"), list):
            shape = tuple(int(d) for d in entry["shape"] if isinstance(d, int) and not isinstance(d, bool) and d >= 0)
            tensors[name] = (entry["dtype"], shape)
    return metadata, tensors


# GGUF value types: how many bytes a fixed-size one takes (strings and arrays are variable)
_GGUF_FIXED = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
_GGUF_STRUCT = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
_GGUF_FILE_TYPES = {0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 7: "Q8_0", 8: "Q5_0", 9: "Q5_1", 10: "Q2_K", 11: "Q3_K_S",
                    12: "Q3_K_M", 13: "Q3_K_L", 14: "Q4_K_S", 15: "Q4_K_M", 16: "Q5_K_S", 17: "Q5_K_M", 18: "Q6_K",
                    19: "IQ2_XXS", 20: "IQ2_XS", 21: "Q2_K_S", 22: "IQ3_XS", 23: "IQ3_XXS", 24: "IQ1_S", 25: "IQ4_NL",
                    26: "IQ3_S", 27: "IQ3_M", 28: "IQ2_S", 29: "IQ2_M", 30: "IQ4_XS", 31: "IQ1_M", 32: "BF16"}


def read_gguf(path):
    """{"version", "tensors", general.* facts...} from the start of a GGUF file, or {} when it is not one.

    Reads the key/value block up to the first key that is not `general.*` (the facts come first), never more than a
    bounded number of keys, and skips arrays instead of reading them.
    """
    out = {}
    try:
        with open(path, "rb") as handle:
            if handle.read(4) != GGUF_MAGIC:
                return {}
            version, tensors, kvs = struct.unpack("<IQQ", handle.read(20))
            out.update(version=version, tensors=tensors)

            def read_string():
                (length,) = struct.unpack("<Q", handle.read(8))
                if length > 1 << 20:
                    raise ValueError("string too long")
                return handle.read(length).decode("utf-8", errors="replace")

            def read_value(kind):
                if kind == 8:
                    return read_string()
                if kind in _GGUF_STRUCT:
                    return struct.unpack(_GGUF_STRUCT[kind], handle.read(_GGUF_FIXED[kind]))[0]
                if kind == 9:  # an array: skipped
                    (item,) = struct.unpack("<I", handle.read(4))
                    (count,) = struct.unpack("<Q", handle.read(8))
                    if item in _GGUF_FIXED:
                        handle.seek(count * _GGUF_FIXED[item], 1)
                    elif item == 8:
                        for _ in range(min(count, 5_000_000)):
                            (length,) = struct.unpack("<Q", handle.read(8))
                            handle.seek(length, 1)
                    else:
                        raise ValueError("unknown array type")
                    return None
                raise ValueError("unknown value type")

            for _ in range(min(kvs, MAX_GGUF_KEYS)):
                key = read_string()
                (kind,) = struct.unpack("<I", handle.read(4))
                value = read_value(kind)
                if not key.startswith("general."):
                    break
                if value is not None:
                    out[key] = value
    except (OSError, ValueError, struct.error, UnicodeError):
        pass
    return out if "version" in out else {}


# ------------------------------------------------------------- key analysis ----

_PREFIX = r"(?:[A-Za-z_]\w*\.){0,2}"
_UNET = re.compile(
    # not under a VAE's own roots: `decoder.up_blocks` is a VAE, `up_blocks` of a diffusers UNet is not
    r"(?:^|\n)(?!(?:encoder|decoder|vae|first_stage_model|quant_conv|post_quant_conv)\.)" + _PREFIX
    + r"(?:diffusion_model\.|double_blocks\.|single_blocks\.|joint_blocks\.|input_blocks\.|output_blocks\.|middle_block\.|"
      r"down_blocks\.|up_blocks\.|mid_block\.|transformer_blocks\.|patch_embedding\.|x_embedder\.|img_in\.|time_embed\.|"
      r"time_in\.|time_text_embed\.|adaln_single\.|double_stream_blocks\.|cap_embedder\.|final_layer\.)")
_VAE_IN_CKPT = re.compile(r"(?:^|\n)(?:first_stage_model\.|vae\.)")
_VAE_STANDALONE = re.compile(r"(?:^|\n)(?:encoder|decoder)\.(?:conv_in|conv1|down|up|mid|downsamples|upsamples|middle)")
_TEXT = re.compile(
    r"(?:^|\n)(?:cond_stage_model\.|conditioner\.embedders\.|text_encoders\.|text_model\.|transformer\.text_model\.|"
    r"encoder\.block\.|shared\.weight|model\.layers\.\d+\.|model\.embed_tokens|text_projection|transformer\.resblocks\.|"
    r"lm_head\.|embed_tokens\.|text_encoder\.|decoder\.block\.)")
_VISION = re.compile(r"(?:^|\n)(?:vision_model\.|visual\.|vision_tower\.|image_encoder\.)")


def roles_of(keys):
    """Which parts a file holds, from its tensor names: {"unet", "vae", "text", "vision"}."""
    joined = "\n".join(keys[:MAX_KEYS_SCANNED])
    roles = set()
    if _UNET.search(joined):
        roles.add("unet")
    if _VAE_IN_CKPT.search(joined):
        roles.add("vae")
    elif _VAE_STANDALONE.search(joined) and "unet" not in roles and not _TEXT.search(joined):
        roles.add("vae")
    if _TEXT.search(joined):
        roles.add("text")
    if _VISION.search(joined):
        roles.add("vision")
    return roles


def kind_from_roles(roles):
    if "unet" in roles and ({"vae", "text"} & roles):
        return CHECKPOINT
    if "unet" in roles:
        return DIFFUSION
    if "text" in roles and "vae" not in roles:
        return TEXT_ENCODER
    if "vae" in roles and "text" not in roles:
        return VAE
    if "vision" in roles:
        return CLIP_VISION
    return UNKNOWN


def _family_from_text(text):
    low = (text or "").lower()
    if not low:
        return ""
    for needle, family in (
        ("pony", "SDXL (Pony)"), ("illustrious", "SDXL"), ("sdxl", "SDXL"), ("stable-diffusion-xl", "SDXL"),
        ("sd_xl", "SDXL"), ("flux", "Flux"), ("sd3", "SD 3"), ("stable-diffusion-3", "SD 3"),
        ("qwen-image", "Qwen Image"), ("qwen_image", "Qwen Image"), ("z-image", "Z-Image"), ("z_image", "Z-Image"),
        ("zimage", "Z-Image"), ("hunyuan", "Hunyuan"), ("wan", "Wan"), ("ltx", "LTX"), ("hidream", "HiDream"),
        ("cosmos", "Cosmos"), ("lumina", "Lumina"), ("stable-diffusion-v2", "SD 2.x"), ("sd_v2", "SD 2.x"),
        ("stable-diffusion-v1", "SD 1.x"), ("sd_v1", "SD 1.x"), ("sd15", "SD 1.x"), ("sd1.5", "SD 1.x"), ("v1-5", "SD 1.x"),
    ):
        if needle in low:
            if len(needle) > 3 or re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z])", low):
                return family
    return ""


def family_from_keys(keys, kind):
    """A guess of the model family from the tensor names (empty when it cannot tell)."""
    joined = "\n".join(keys[:MAX_KEYS_SCANNED])
    has = lambda text: text in joined  # noqa: E731 - a tiny local helper
    if kind in (CHECKPOINT, DIFFUSION):
        if has("txt_in.individual_token_refiner") or has("txt_in.c_embedder"):
            return "Hunyuan"
        if has("joint_blocks."):
            return "SD 3"
        if has("double_blocks.") and has("single_blocks."):
            return "Flux"
        if has("patch_embedding") and has("text_embedding"):
            return "Wan"
        if has("cap_embedder"):
            return "Z-Image / Lumina"
        if has("double_stream_blocks."):
            return "HiDream"
        if has("adaln_single") and has("transformer_blocks."):
            return "LTX"
        if has("transformer_blocks.") and has("time_text_embed") and (has("txt_in") or has("txt_norm")):
            return "Qwen Image"
        if has("conditioner.embedders.1") or has("text_encoder_2") or (has("label_emb") and has("input_blocks.")) or has("add_embedding"):
            return "SDXL"
        if has("cond_stage_model.model."):
            return "SD 2.x"
        if has("cond_stage_model.transformer.text_model") or (has("input_blocks.") and has("diffusion_model.")):
            return "SD 1.x"
        return ""
    if kind == TEXT_ENCODER:
        if has("encoder.block.") and has("shared.weight"):
            return "T5 / UMT5"
        if has("model.layers.") and has("embed_tokens"):
            return "LLM (Qwen / Llama / Gemma)"
        if has("text_model."):
            return "CLIP"
    return ""


_GGUF_TEXT = {"clip", "t5", "t5encoder", "umt5", "llama", "qwen2", "qwen2vl", "qwen3", "qwen3vl", "gemma", "gemma2",
              "gemma3", "mistral", "mistral3", "gpt-oss", "phi3"}
_GGUF_FAMILY = {"flux": "Flux", "sd1": "SD 1.x", "sdxl": "SDXL", "sd3": "SD 3", "aura": "AuraFlow", "hidream": "HiDream",
                "cosmos": "Cosmos", "ltxv": "LTX", "hyvid": "Hunyuan", "wan": "Wan", "lumina2": "Z-Image / Lumina",
                "qwen_image": "Qwen Image", "qwen-image": "Qwen Image"}


def precision_of(tensors):
    """A label such as `fp16`, `bf16`, `fp8` or `fp8 + bf16` from the bytes each tensor type takes, and the
    number of parameters."""
    weight, params = {}, 0
    for dtype, shape in tensors.values():
        count = 1
        for dim in shape:
            count *= dim
        params += count
        weight[dtype] = weight.get(dtype, 0) + count * _BYTES.get(dtype, 2)
    if not weight:
        return "", 0
    total = sum(weight.values()) or 1
    ranked = sorted(weight.items(), key=lambda item: -item[1])
    labels = []
    for dtype, size in ranked:
        label = _PRECISION.get(dtype, dtype.lower())
        if label not in labels and (not labels or size / total >= 0.15):
            labels.append(label)
    return " + ".join(labels[:2]), params


def count_text(params):
    """12_345_678_901 -> `12.3B`; 123_456_789 -> `123M`."""
    if params >= 1e9:
        return f"{params / 1e9:.1f}B"
    if params >= 1e6:
        return f"{params / 1e6:.0f}M"
    if params >= 1e3:
        return f"{params / 1e3:.0f}K"
    return str(params) if params else ""


def quant_from_name(name):
    match = re.search(r"(?<![A-Za-z0-9])((?:IQ|Q)\d(?:_[A-Z0-9]+)*|BF16|FP16|F16|FP8|F8|FP32|F32)(?![A-Za-z0-9])", name, re.I)
    return match.group(1).upper() if match else ""


_TRAINING = (
    ("trained on", "ss_sd_model_name"), ("network dim", "ss_network_dim"), ("resolution", "ss_resolution"),
    ("epochs", "ss_epoch"), ("images", "ss_num_train_images"),
)
_SPEC = (("title", "modelspec.title"), ("author", "modelspec.author"), ("description", "modelspec.description"),
         ("architecture", "modelspec.architecture"), ("date", "modelspec.date"), ("license", "modelspec.license"))


def _clean(value, limit=400):
    return " ".join(str(value).split())[:limit] if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ""


def _extras(metadata):
    out = {}
    for label, key in _SPEC + _TRAINING:
        value = _clean(metadata.get(key, ""))
        if value and value.lower() not in ("none", "null"):
            out[label] = value
    return out


# --------------------------------------------------------------------- info ----

def inspect_file(path, folder_key="", name=None):
    """Everything known about one model file as a JSON-able dict (see README: Model Selector)."""
    name = name or os.path.basename(path)
    base = os.path.basename(path)
    stem, extension = os.path.splitext(base)
    extension = extension.lower()
    try:
        stat = os.stat(path)
    except OSError:
        stat = None
    info = {"file": base, "stem": stem, "format": extension.lstrip("."), "size": stat.st_size if stat else 0,
            "mtime": stat.st_mtime if stat else 0, "folder": folder_key, "kind": UNKNOWN, "kind_source": "",
            "family": "", "precision": "", "params": 0, "params_text": "", "tensors": 0, "quant": "", "extras": {},
            "readable": False, "needs": ""}
    hint = FOLDER_KINDS.get(folder_key, UNKNOWN)
    if extension == ".gguf":
        facts = read_gguf(path)
        info["readable"] = "general.architecture" in facts
        info["needs"] = "a GGUF loader pack installed (ComfyUI-GGUF or ComfyUI-SmartModelLoaders-MXD)"
        arch = str(facts.get("general.architecture", "")).lower()
        info["tensors"] = int(facts.get("tensors", 0) or 0)
        file_type = facts.get("general.file_type")
        info["quant"] = _GGUF_FILE_TYPES.get(file_type, "") if isinstance(file_type, int) else ""
        info["quant"] = info["quant"] or quant_from_name(stem)
        info["precision"] = info["quant"]
        if arch:
            info["kind"], info["kind_source"] = (TEXT_ENCODER if arch in _GGUF_TEXT else DIFFUSION), "content"
            info["family"] = _GGUF_FAMILY.get(arch, "" if arch in _GGUF_TEXT else arch)
            info["extras"]["architecture"] = arch
        for label, key in (("title", "general.name"), ("author", "general.author"), ("size", "general.size_label"),
                           ("license", "general.license")):
            value = _clean(facts.get(key, ""))
            if value:
                info["extras"][label] = value
    elif extension in SAFE_EXTENSIONS:
        metadata, tensors = read_safetensors(path)
        info["readable"] = bool(tensors)
        info["tensors"] = len(tensors)
        info["precision"], info["params"] = precision_of(tensors)
        keys = list(tensors)
        roles = roles_of(keys)
        kind = kind_from_roles(roles)
        if kind != UNKNOWN:
            info["kind"], info["kind_source"] = kind, "content"
        info["family"] = (_family_from_text(metadata.get("modelspec.architecture", ""))
                          or _family_from_text(metadata.get("ss_base_model_version", ""))
                          or family_from_keys(keys, info["kind"]))
        info["extras"] = _extras(metadata)
        info["roles"] = sorted(roles)
    else:
        info["needs"] = "nothing extra. A pickle file: loaded the way ComfyUI loads it; its contents are not read here, so the kind comes from its folder"
    if info["kind"] == UNKNOWN and hint != UNKNOWN:
        info["kind"], info["kind_source"] = hint, "folder"
    if not info["family"]:
        info["family"] = _family_from_text(stem)
    info["params_text"] = count_text(info["params"])
    info["outputs"] = list(OUTPUTS[info["kind"]])
    info["name"] = name
    return info


def cached_info(path, folder_key="", name=None):
    try:
        stat = os.stat(path)
    except OSError:
        return inspect_file(path, folder_key, name)
    key = (path, stat.st_mtime_ns, stat.st_size, folder_key, name)
    with _CACHE_LOCK:
        if key in _CACHE:
            return dict(_CACHE[key])
    info = inspect_file(path, folder_key, name)
    with _CACHE_LOCK:
        if len(_CACHE) >= MAX_CACHE:
            _CACHE.clear()
        _CACHE[key] = info
    return dict(info)


def summary(info):
    """The light version for the list on the picker screen."""
    keys = ("id", "name", "file", "stem", "size", "mtime", "format", "folder", "kind", "family", "precision", "params_text",
            "quant", "outputs")
    return {key: info.get(key, "") for key in keys}
