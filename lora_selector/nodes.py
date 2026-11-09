import hashlib
import inspect
import logging

from . import metadata
from .selection import (
    StackError,
    active,
    compatibility_warnings,
    family_from_class_name,
    names_text,
    parse_stack,
    trigger_words,
)

logger = logging.getLogger("comfyui-bart-nodes")


def _path_of(name):
    """The file of a LoRA name from the loras folders (ComfyUI refuses names that leave them)."""
    import folder_paths

    path = folder_paths.get_full_path("loras", name)
    if not path:
        raise FileNotFoundError(f"LoRA not found in the loras folders: {name}")
    return path


def _load_file(path):
    """(state dict, metadata or None) of a LoRA file; older ComfyUI versions do not return the metadata."""
    import comfy.utils

    if "return_metadata" in inspect.signature(comfy.utils.load_torch_file).parameters:
        return comfy.utils.load_torch_file(path, safe_load=True, return_metadata=True)
    return comfy.utils.load_torch_file(path, safe_load=True), None


def _apply(model, clip, lora, strength_model, strength_clip, metadata):
    import comfy.sd

    kwargs = {}
    if metadata and "lora_metadata" in inspect.signature(comfy.sd.load_lora_for_models).parameters:
        kwargs["lora_metadata"] = metadata
    return comfy.sd.load_lora_for_models(model, clip, lora, strength_model, strength_clip, **kwargs)


def _notes():
    """The user's own LoRA notes (triggers typed on the picker screen); empty when there are none."""
    try:
        import os

        import folder_paths

        return metadata.load_notes(os.path.join(folder_paths.get_user_directory(), "bart_lora_notes.json"))
    except Exception:  # triggers are a convenience: never worth failing a run
        return {}


def model_family(model):
    inner = getattr(model, "model", None)
    return family_from_class_name(type(inner).__name__) if inner is not None else ""


class LoraSelector:
    """Several LoRAs on one node: each switched on or off, each with its own strength."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL", {"tooltip": "The diffusion model the LoRAs are applied to."}),
                # the rows are drawn and edited by the frontend (js/lora_selector.js); this is where they are kept
                "loras": ("STRING", {"default": "[]", "multiline": False}),
            },
            "optional": {
                "clip": ("CLIP", {"tooltip": "Optional: the CLIP model the LoRAs are applied to as well."}),
                "apply_to_clip": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Off = the LoRAs go to the model only and the CLIP passes through untouched "
                               "(what most Flux / Wan / video LoRAs want).",
                }),
            },
        }

    RETURN_TYPES = ("MODEL", "CLIP", "STRING", "STRING")
    RETURN_NAMES = ("model", "clip", "lora_names", "trigger_words")
    OUTPUT_TOOLTIPS = (
        "The model with the switched-on LoRAs applied, in the order of the rows.",
        "The CLIP with them applied (the CLIP as it came in when apply_to_clip is off; nothing if none was connected).",
        "The names of the LoRAs that were applied, separated by commas.",
        "The trigger words of those LoRAs (your notes, Civitai, the A1111 .json), separated by commas.",
    )
    FUNCTION = "apply"
    CATEGORY = "Bart's nodes/Model"

    @classmethod
    def VALIDATE_INPUTS(cls, loras=None):
        # None = wired from another node, unknowable until execution
        if loras is None:
            return True
        try:
            stack = parse_stack(loras)
            for row in active(stack):
                _path_of(row["name"])
        except StackError as exc:
            return str(exc)
        except FileNotFoundError as exc:
            return str(exc)
        return True

    @classmethod
    def IS_CHANGED(cls, loras="[]", **_):
        # a LoRA file replaced under the same name must run the node again
        try:
            import os

            stack = active(parse_stack(loras))
            parts = [loras]
            for row in stack:
                stat = os.stat(_path_of(row["name"]))
                parts.append(f"{row['name']}|{stat.st_mtime_ns}|{stat.st_size}")
        except (StackError, FileNotFoundError, OSError):
            return float("nan")
        return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()

    def apply(self, model, loras="[]", clip=None, apply_to_clip=True):
        try:
            rows = active(parse_stack(loras))
        except StackError as exc:
            raise RuntimeError(f"Lora Selector: {exc}") from None
        warnings = []
        use_clip = clip is not None and apply_to_clip
        infos, families = [], {}
        notes = _notes() if rows else {}
        for row in rows:
            try:
                path = _path_of(row["name"])
            except FileNotFoundError as exc:
                raise RuntimeError(f"Lora Selector: {exc}. Switch the row off or pick another LoRA.") from None
            strength_model = row["strength_model"]
            strength_clip = strength_model if row["strength_clip"] is None else row["strength_clip"]
            lora, lora_metadata = _load_file(path)
            try:
                if use_clip:
                    try:
                        model, clip = _apply(model, clip, lora, strength_model, strength_clip, lora_metadata)
                    except Exception as exc:  # a CLIP the LoRA cannot be applied to (video models, ...): the model still gets it
                        logger.warning("Lora Selector: %s could not be applied to the CLIP (%s: %s); applied to the model only",
                                       row["name"], type(exc).__name__, exc)
                        warnings.append(f"{row['name']}: not applied to the CLIP ({type(exc).__name__}); the model has it")
                        model, _unused = _apply(model, None, lora, strength_model, 0.0, lora_metadata)
                else:
                    model, _unused = _apply(model, None, lora, strength_model, 0.0, lora_metadata)
            finally:
                del lora  # a big LoRA is not kept in memory while the next one loads
            try:
                info = metadata.lora_info(path, row["name"], notes)
                infos.append(info)
                families[row["name"]] = info["family"]
            except Exception:  # the extra information must never fail the run
                logger.exception("Lora Selector: could not read the information of %s", row["name"])
        warnings = compatibility_warnings(rows, families, model_family(model)) + warnings
        for line in warnings:
            logger.warning("Lora Selector: %s", line)
        result = (model, clip, names_text(rows), trigger_words(infos))
        return {"ui": {"notes": warnings}, "result": result}
