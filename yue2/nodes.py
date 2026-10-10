import os
import tempfile

import torch
import torchaudio

from .selection import build_generate_kwargs, read_first_file

MODEL_ID = "m-a-p/YuE2-3B"
VAE_CHOICES = ["YuE2-Vae", "YuE2-Vae-legacy"]
COT_CHOICES = ["full", "melody", "off"]
# 2**53 - 1: the most a JS number (how the frontend stores widget values)
# holds exactly - a larger seed typed into the widget would be silently rounded.
MAX_SEED = 2**53 - 1

# Loading the pipeline pulls ~7GB of weights onto the GPU; ComfyUI may
# re-execute a loader node (a downstream change, a cache miss) far more
# often than the weights actually need reloading, so the pipeline is kept
# here keyed by (vae, device) rather than reloaded on every call.
_PIPELINE_CACHE = {}


def _get_pipeline(vae, device):
    key = (vae, device)
    if key not in _PIPELINE_CACHE:
        # imported lazily: the `yue2` package is an optional, non-PyPI
        # dependency (see README) - only nodes that actually run inference
        # need it, and importing it here keeps that requirement out of the
        # module import path so __init__.py can degrade gracefully instead
        # of failing to import this whole sub-package.
        try:
            from yue2 import YuE2Pipeline
        except ImportError as exc:
            raise RuntimeError(
                "the `yue2` package is not installed. It is not on PyPI: download "
                "yue2_infer-*.whl from https://huggingface.co/m-a-p/YuE2-3B/tree/main and "
                "`pip install` that file into ComfyUI's Python environment (see the README's "
                "YuE2 section)."
            ) from exc

        _PIPELINE_CACHE[key] = YuE2Pipeline.from_pretrained(MODEL_ID, device=device, vae=vae)
    return _PIPELINE_CACHE[key]


def _load_audio(path):
    waveform, sample_rate = torchaudio.load(path)
    return {"waveform": waveform.unsqueeze(0), "sample_rate": sample_rate}


class YuE2ModelLoader:
    """Loads the YuE2-3B pipeline once and hands it to the other nodes.

    Model weights are CC BY-NC 4.0 (non-commercial use only) - see README.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "vae": (VAE_CHOICES, {"default": VAE_CHOICES[0]}),
                "device": ("STRING", {"default": "cuda"}),
            },
        }

    RETURN_TYPES = ("YUE2_PIPELINE",)
    RETURN_NAMES = ("pipeline",)
    FUNCTION = "load"
    CATEGORY = "audio/yue2"

    def load(self, vae, device):
        return (_get_pipeline(vae, device),)


class YuE2Plan:
    """Score-only planning pass (no audio render) - feeds YuE2Generate's
    `abc` input for the agentic-editing loop: plan, hand-edit or otherwise
    revise the returned ABC text, generate against the revised version.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "pipeline": ("YUE2_PIPELINE",),
                "style": ("STRING", {"default": "", "multiline": True}),
                "lyrics": ("STRING", {"default": "", "multiline": True}),
                "seed": ("INT", {"default": 0, "min": 0, "max": MAX_SEED}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("abc",)
    FUNCTION = "plan"
    CATEGORY = "audio/yue2"

    def plan(self, pipeline, style, lyrics, seed):
        with tempfile.TemporaryDirectory() as tmp:
            plan = pipeline.plan(style=style, lyrics=lyrics, cot="full", seed=seed)
            plan.save(tmp)
            return (read_first_file(tmp, "*.abc"),)


class YuE2Generate:
    """Renders a song. With `abc` left blank this is a fresh generation in
    the given `cot` mode; with `abc` supplied (from YuE2Plan, a previous
    YuE2Generate run, or a transcription obtained some other way) it renders
    against that score instead - this is what both "cover" (transcribe an
    existing recording to ABC externally, feed it in with cot="melody") and
    "edit" (revise a previous run's `abc` output, feed the revision back in)
    come down to; yue2 doesn't have separate cover/edit entry points, just
    this one call with different arguments.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "pipeline": ("YUE2_PIPELINE",),
                "style": ("STRING", {"default": "", "multiline": True}),
                "lyrics": ("STRING", {"default": "", "multiline": True}),
                "cot": (COT_CHOICES, {"default": COT_CHOICES[0]}),
                "seed": ("INT", {"default": 0, "min": 0, "max": MAX_SEED}),
            },
            "optional": {
                "abc": ("STRING", {"default": "", "multiline": True}),
            },
        }

    RETURN_TYPES = ("AUDIO", "STRING")
    RETURN_NAMES = ("audio", "abc")
    FUNCTION = "generate"
    CATEGORY = "audio/yue2"

    def generate(self, pipeline, style, lyrics, cot, seed, abc=""):
        kwargs = build_generate_kwargs(style, lyrics, cot, seed, abc)

        with tempfile.TemporaryDirectory() as tmp:
            song = pipeline(**kwargs)
            audio_path = os.path.join(tmp, "song.flac")
            song.save(audio_path)
            song.save_artifacts(tmp)
            audio = _load_audio(audio_path)
            try:
                abc_out = read_first_file(tmp, "*.abc")
            except FileNotFoundError:
                abc_out = abc

        return (audio, abc_out)


NODE_CLASS_MAPPINGS = {
    "YuE2ModelLoader": YuE2ModelLoader,
    "YuE2Plan": YuE2Plan,
    "YuE2Generate": YuE2Generate,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "YuE2ModelLoader": "YuE2 Model Loader \U0001f3b5",
    "YuE2Plan": "YuE2 Plan Score \U0001f3b5",
    "YuE2Generate": "YuE2 Generate Song \U0001f3b5",
}
