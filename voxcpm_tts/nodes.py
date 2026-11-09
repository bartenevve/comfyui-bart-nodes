import os
import tempfile

import numpy as np
import torch

from .selection import (
    DEFAULTS,
    DEVICES,
    MAX_SEED,
    PRESET_MODELS,
    InputError,
    build_kwargs,
    check_prompt,
    compose_text,
    info_line,
    mode_name,
    mono_float,
    write_wav,
)

LOCAL_PREFIX = "local: "

# A VoxCPM checkpoint is 1-5 GB and loading it (plus a torch.compile warm-up) takes far longer than a
# generation, while ComfyUI may re-run a loader node more often than the weights need reloading, so the
# model is kept here keyed by everything that changes how it is loaded.
_MODEL_CACHE = {}


def _models_dir():
    """ComfyUI's models/voxcpm folder (checkpoints downloaded or copied there show up in the loader)."""
    try:
        import folder_paths

        return os.path.join(folder_paths.models_dir, "voxcpm")
    except ImportError:
        return None


def _local_models():
    base = _models_dir()
    if not base or not os.path.isdir(base):
        return []
    try:
        names = sorted(name for name in os.listdir(base) if os.path.isfile(os.path.join(base, name, "config.json")))
    except OSError:
        return []
    return [LOCAL_PREFIX + name for name in names]


def _resolve(choice):
    """Hugging Face repo id, or the directory of a local checkpoint."""
    if choice.startswith(LOCAL_PREFIX):
        name = choice[len(LOCAL_PREFIX):]
        base = _models_dir()
        path = os.path.join(base, name) if base else ""
        # a dropdown value comes from the saved workflow: never let it leave models/voxcpm
        if not name or os.path.basename(name) != name or not os.path.isdir(path):
            raise RuntimeError(f"VoxCPM: the local checkpoint {name!r} is not in {base}")
        return path
    return choice


def _get_model(choice, device, optimize, load_denoiser, local_files_only):
    key = (choice, device, bool(optimize), bool(load_denoiser), bool(local_files_only))
    if key not in _MODEL_CACHE:
        # imported lazily: `voxcpm` is a heavy optional dependency (its own pins on gradio, datasets,
        # funasr, ...). Only a node that really loads a model needs it, and keeping the import here lets
        # the pack's __init__ register these nodes even when it is not installed.
        try:
            from voxcpm import VoxCPM
        except ImportError as exc:
            raise RuntimeError(
                "the `voxcpm` package is not installed: `pip install voxcpm` into ComfyUI's Python "
                "environment (Python 3.10-3.12; see the README's VoxCPM section for the pins it brings)."
            ) from exc
        loaded = VoxCPM.from_pretrained(
            _resolve(choice),
            load_denoiser=bool(load_denoiser),
            optimize=bool(optimize),
            device=None if device == "auto" else device,
            local_files_only=bool(local_files_only),
        )
        try:
            loaded.bart_model_id = choice  # for the info output: the object itself does not say which checkpoint it is
        except AttributeError:
            pass
        _MODEL_CACHE[key] = loaded
    return _MODEL_CACHE[key]


def _save_audio(audio, directory, label):
    """A ComfyUI AUDIO input as a WAV file for VoxCPM (which only takes paths); None when not connected."""
    if audio is None:
        return None
    try:
        samples = mono_float(audio["waveform"].detach().cpu().numpy())
        rate = int(audio["sample_rate"])
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise RuntimeError(f"VoxCPM: {label} is not a usable AUDIO input ({exc})") from None
    path = os.path.join(directory, label + ".wav")
    write_wav(path, samples, rate)
    return path


def _to_comfy_audio(wav, sample_rate):
    """VoxCPM's 1-D float32 array -> ComfyUI AUDIO [1, 1, T]."""
    array = np.ascontiguousarray(np.asarray(wav, dtype=np.float32).reshape(-1))
    return {"waveform": torch.from_numpy(array).reshape(1, 1, -1), "sample_rate": int(sample_rate)}


class VoxCPMModelLoader:
    """Loads a VoxCPM checkpoint once and hands it to VoxCPMGenerate."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # presets download from Hugging Face on first use; "local: x" = models/voxcpm/x
                "model": (list(PRESET_MODELS) + _local_models(), {"default": PRESET_MODELS[0]}),
                # "auto" = CUDA if there is one, else Apple MPS, else CPU
                "device": (list(DEVICES), {"default": "auto"}),
            },
            "optional": {
                # torch.compile plus a warm-up run: faster on CUDA, slow to start and fragile elsewhere
                "optimize": ("BOOLEAN", {"default": False}),
                # the ZipEnhancer noise suppressor (a separate ModelScope download) for `denoise`
                "load_denoiser": ("BOOLEAN", {"default": False}),
                "local_files_only": ("BOOLEAN", {"default": False}),
            },
        }

    RETURN_TYPES = ("VOXCPM_MODEL",)
    RETURN_NAMES = ("model",)
    FUNCTION = "load"
    CATEGORY = "Bart's nodes/Audio"

    def load(self, model, device, optimize=False, load_denoiser=False, local_files_only=False):
        return (_get_model(model, device, optimize, load_denoiser, local_files_only),)


class VoxCPMGenerate:
    """Speaks `text`: plain, in a designed voice, or in a cloned one."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("VOXCPM_MODEL",),
                "text": ("STRING", {"default": "", "multiline": True}),
                "seed": ("INT", {"default": 0, "min": 0, "max": MAX_SEED, "control_after_generate": True}),
            },
            "optional": {
                "voice_description": ("STRING", {"default": "", "multiline": True}),
                "reference_audio": ("AUDIO",),
                "prompt_audio": ("AUDIO",),
                "prompt_text": ("STRING", {"default": "", "multiline": True}),
                "cfg_value": ("FLOAT", {"default": DEFAULTS["cfg_value"], "min": 0.1, "max": 10.0, "step": 0.1}),
                "inference_timesteps": ("INT", {"default": DEFAULTS["inference_timesteps"], "min": 1, "max": 100}),
                "normalize": ("BOOLEAN", {"default": DEFAULTS["normalize"]}),
                "denoise": ("BOOLEAN", {"default": DEFAULTS["denoise"]}),
                "max_len": ("INT", {"default": DEFAULTS["max_len"], "min": 16, "max": 8192}),
                "retry_badcase": ("BOOLEAN", {"default": DEFAULTS["retry_badcase"]}),
                "retry_badcase_max_times": ("INT", {"default": DEFAULTS["retry_badcase_max_times"], "min": 0, "max": 10}),
                "retry_badcase_ratio_threshold": (
                    "FLOAT",
                    {"default": DEFAULTS["retry_badcase_ratio_threshold"], "min": 1.0, "max": 20.0, "step": 0.5},
                ),
            },
        }

    RETURN_TYPES = ("AUDIO", "STRING")
    RETURN_NAMES = ("audio", "info")
    FUNCTION = "generate"
    CATEGORY = "Bart's nodes/Audio"

    @classmethod
    def VALIDATE_INPUTS(cls, text=None, voice_description=None):
        # None = wired from another node, unknowable until execution
        if text is None:
            return True
        try:
            compose_text(text, voice_description or "")
        except InputError as exc:
            return str(exc)
        return True

    def generate(self, model, text, seed, voice_description="", reference_audio=None, prompt_audio=None,
                 prompt_text="", **options):
        try:
            full_text = compose_text(text, voice_description)
            check_prompt(prompt_audio is not None, prompt_text)
            with tempfile.TemporaryDirectory(prefix="voxcpm_") as directory:
                reference_path = _save_audio(reference_audio, directory, "reference_audio")
                prompt_path = _save_audio(prompt_audio, directory, "prompt_audio")
                kwargs = build_kwargs(full_text, seed, options, reference_path, prompt_path, prompt_text)
                try:
                    wav = model.generate(**kwargs)
                except (ValueError, FileNotFoundError) as exc:
                    # upstream's own checks ("reference_wav_path is only supported with VoxCPM2 models", ...)
                    raise RuntimeError(f"VoxCPM: {exc}") from None
        except InputError as exc:
            raise RuntimeError(f"VoxCPM: {exc}") from None

        sample_rate = int(model.tts_model.sample_rate)
        audio = _to_comfy_audio(wav, sample_rate)
        mode = mode_name(reference_audio is not None, prompt_audio is not None, bool((voice_description or "").strip()))
        info = info_line(getattr(model, "bart_model_id", "VoxCPM"), mode, audio["waveform"].shape[-1], sample_rate, seed)
        return (audio, info)
