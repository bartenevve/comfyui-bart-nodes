import contextlib
import hashlib
import inspect
import logging
import os

from . import files, model_info

logger = logging.getLogger("comfyui-bart-nodes")

WEIGHT_DTYPES = ["default", "fp8_e4m3fn", "fp8_e4m3fn_fast", "fp8_e5m2"]
DEVICES = ["default", "cpu"]
FALLBACK_CLIP_TYPES = ["stable_diffusion", "stable_cascade", "sd3", "stable_audio", "mochi", "ltxv", "pixart", "cosmos",
                       "lumina2", "wan", "hidream", "chroma", "ace", "omnigen2", "qwen_image", "hunyuan_image", "flux2"]
# the classes of the GGUF loader packs we can borrow (ComfyUI-GGUF and ComfyUI-SmartModelLoaders-MXD)
GGUF_UNET_CLASSES = ("UnetLoaderGGUF", "UNETLoaderUnified")
GGUF_CLIP_CLASSES = ("CLIPLoaderGGUF", "CLIPLoaderUnified")


def _clip_types():
    try:
        import comfy.sd

        return [t.name.lower() for t in comfy.sd.CLIPType]
    except Exception:  # not inside ComfyUI (the tests), or an enum this version does not have
        return FALLBACK_CLIP_TYPES


def _roots():
    import folder_paths

    return files.collect_roots(folder_paths.get_folder_paths)


def _find(model_id):
    """(absolute path, folder key) of a model id, or a FileNotFoundError that says what is wrong."""
    parts = files.split_id(model_id)
    if parts is None:
        raise FileNotFoundError("no model is selected: open the node and choose one" if not model_id else f"not a model id: {model_id!r}")
    path = files.resolve(model_id, _roots())
    if not path:
        raise FileNotFoundError(f"model not found in the model folders: {parts[1]}")
    return path, parts[0]


def _gguf_class(candidates):
    import nodes

    for cls in nodes.NODE_CLASS_MAPPINGS.values():
        if getattr(cls, "__name__", "") in candidates:
            return cls
    return None


def gguf_available(kind):
    try:
        return _gguf_class(GGUF_CLIP_CLASSES if kind == model_info.TEXT_ENCODER else GGUF_UNET_CLASSES) is not None
    except Exception:
        return False


@contextlib.contextmanager
def _borrowed_path(name, path):
    """Make folder_paths hand `path` out for `name` (whatever folder is asked), so a GGUF loader pack finds a file that
    lies outside the folders it knows."""
    import folder_paths

    originals = (folder_paths.get_full_path, folder_paths.get_full_path_or_raise)

    def get_full_path(folder, filename, *args, **kwargs):
        return path if filename == name else originals[0](folder, filename, *args, **kwargs)

    def get_full_path_or_raise(folder, filename, *args, **kwargs):
        return path if filename == name else originals[1](folder, filename, *args, **kwargs)

    folder_paths.get_full_path, folder_paths.get_full_path_or_raise = get_full_path, get_full_path_or_raise
    try:
        yield
    finally:
        folder_paths.get_full_path, folder_paths.get_full_path_or_raise = originals


def _load_gguf(path, kind, clip_type):
    wants_clip = kind == model_info.TEXT_ENCODER
    cls = _gguf_class(GGUF_CLIP_CLASSES if wants_clip else GGUF_UNET_CLASSES)
    if cls is None:
        raise RuntimeError(
            "this is a GGUF file and no GGUF loader is installed: install ComfyUI-GGUF (city96) or "
            "ComfyUI-SmartModelLoaders-MXD, then restart ComfyUI"
        )
    name = "bart_" + hashlib.sha1(path.encode("utf-8", "replace")).hexdigest()[:12] + ".gguf"
    loader = cls()
    with _borrowed_path(name, path):
        if wants_clip:
            return (None, loader.load_clip(name, clip_type)[0], None, None)
        return (loader.load_unet(name)[0], None, None, None)


def _model_options(weight_dtype):
    options = {}
    if weight_dtype not in ("fp8_e4m3fn", "fp8_e4m3fn_fast", "fp8_e5m2"):
        return options
    import torch

    if weight_dtype == "fp8_e4m3fn":
        options["dtype"] = torch.float8_e4m3fn
    elif weight_dtype == "fp8_e4m3fn_fast":
        options["dtype"] = torch.float8_e4m3fn
        options["fp8_optimizations"] = True
    elif weight_dtype == "fp8_e5m2":
        options["dtype"] = torch.float8_e5m2
    return options


def load_model(path, kind, weight_dtype="default", clip_type="stable_diffusion", device="default"):
    """(model, clip, vae, clip_vision) of a file, with None for what it does not hold."""
    import comfy.sd
    import comfy.utils
    import folder_paths

    embeddings = folder_paths.get_folder_paths("embeddings")
    if path.lower().endswith(".gguf"):
        return _load_gguf(path, kind, clip_type)
    if kind == model_info.CHECKPOINT:
        result = comfy.sd.load_checkpoint_guess_config(
            path, output_vae=True, output_clip=True, embedding_directory=embeddings, model_options=_model_options(weight_dtype))
        return (result[0], result[1], result[2], None)
    if kind == model_info.DIFFUSION:
        return (comfy.sd.load_diffusion_model(path, model_options=_model_options(weight_dtype)), None, None, None)
    if kind == model_info.TEXT_ENCODER:
        options = {}
        if device == "cpu":
            import torch

            options["load_device"] = options["offload_device"] = torch.device("cpu")
        enum = getattr(comfy.sd, "CLIPType", None)
        type_ = getattr(enum, clip_type.upper(), getattr(enum, "STABLE_DIFFUSION", None)) if enum else None
        kwargs = {"ckpt_paths": [path], "embedding_directory": embeddings, "model_options": options}
        if type_ is not None:
            kwargs["clip_type"] = type_
        return (None, comfy.sd.load_clip(**kwargs), None, None)
    if kind == model_info.VAE:
        if "return_metadata" in inspect.signature(comfy.utils.load_torch_file).parameters:
            sd, metadata = comfy.utils.load_torch_file(path, return_metadata=True)
            vae = comfy.sd.VAE(sd=sd, metadata=metadata)
        else:
            vae = comfy.sd.VAE(sd=comfy.utils.load_torch_file(path))
        vae.throw_exception_if_invalid()
        return (None, None, vae, None)
    if kind == model_info.CLIP_VISION:
        import comfy.clip_vision

        vision = comfy.clip_vision.load(path)
        if vision is None:
            raise RuntimeError("this file does not contain a valid CLIP vision model")
        return (None, None, None, vision)
    raise RuntimeError(
        "the kind of this file could not be told (it is not a checkpoint, diffusion model, text encoder, VAE or CLIP vision "
        "model that this node recognises): load it with the matching ComfyUI loader"
    )


class ModelSelector:
    """Loads any model from the model folders, whatever its format, and gives out what the file holds."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # the chosen file ("folder::relative/path"); the frontend draws the chooser and keeps it here
                "model": ("STRING", {"default": "", "multiline": False}),
            },
            "optional": {
                "weight_dtype": (WEIGHT_DTYPES, {"default": "default", "advanced": True,
                                                 "tooltip": "For checkpoints and diffusion models: load the weights as fp8."}),
                "clip_type": (_clip_types(), {"default": "stable_diffusion", "advanced": True,
                                              "tooltip": "For a text encoder file: what it is meant for (see Load CLIP's recipes)."}),
                "device": (DEVICES, {"default": "default", "advanced": True,
                                     "tooltip": "For a text encoder file: cpu keeps it off the GPU."}),
            },
        }

    RETURN_TYPES = ("MODEL", "CLIP", "VAE", "CLIP_VISION", "STRING")
    RETURN_NAMES = ("model", "clip", "vae", "clip_vision", "name")
    OUTPUT_TOOLTIPS = (
        "The diffusion model (from a checkpoint or a diffusion model file; nothing from other files).",
        "The CLIP / text encoder (from a checkpoint or a text encoder file).",
        "The VAE (from a checkpoint or a VAE file).",
        "The CLIP vision model (from a CLIP vision file).",
        "The name of the model: the file's name without its extension.",
    )
    FUNCTION = "load"
    CATEGORY = "Bart's nodes/Model"

    @classmethod
    def VALIDATE_INPUTS(cls, model=None):
        # None = wired from another node, unknowable until execution
        if model is None:
            return True
        try:
            path, key = _find(model)
            kind = model_info.cached_info(path, key)["kind"]
            if path.lower().endswith(".gguf") and not gguf_available(kind):
                return ("this is a GGUF file and no GGUF loader is installed: install ComfyUI-GGUF (city96) or "
                        "ComfyUI-SmartModelLoaders-MXD")
        except FileNotFoundError as exc:
            return str(exc)
        return True

    @classmethod
    def IS_CHANGED(cls, model="", **_):
        # a file replaced under the same name must load again
        try:
            path, _key = _find(model)
            stat = os.stat(path)
        except (FileNotFoundError, OSError):
            return float("nan")
        return hashlib.sha256(f"{model}|{stat.st_mtime_ns}|{stat.st_size}".encode("utf-8")).hexdigest()

    def load(self, model, weight_dtype="default", clip_type="stable_diffusion", device="default"):
        try:
            path, key = _find(model)
        except FileNotFoundError as exc:
            raise RuntimeError(f"Model Selector: {exc}") from None
        info = model_info.cached_info(path, key)
        try:
            model_out, clip, vae, vision = load_model(path, info["kind"], weight_dtype, clip_type, device)
        except RuntimeError as exc:
            raise RuntimeError(f"Model Selector: {exc}") from None
        except Exception as exc:
            if any(cls.__name__ == "InterruptProcessingException" for cls in type(exc).__mro__):
                raise  # ComfyUI's Interrupt button: it must reach the executor untouched
            # ComfyUI's own loaders raise all sorts of things for a damaged or unsupported file: say which file and what
            raise RuntimeError(f"Model Selector: could not load {info['file']} as a {info['kind']}: {exc}".rstrip()) from exc
        return (model_out, clip, vae, vision, info["stem"])
