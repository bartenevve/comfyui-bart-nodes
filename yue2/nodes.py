import numpy as np
import torch

from .selection import VAE_REPOS, backend_for, build_generate_kwargs, generate_error, vae_repo

MODEL_ID = "m-a-p/YuE2-3B"
VAE_CHOICES = list(VAE_REPOS)
COT_CHOICES = ["full", "melody", "off"]
# 2**53 - 1: the most a JS number (how the frontend stores widget values)
# holds exactly - a larger seed typed into the widget would be silently rounded.
MAX_SEED = 2**53 - 1

# Loading the pipeline pulls ~7GB of weights; ComfyUI may re-execute a loader
# node (a downstream change, a cache miss) far more often than the weights
# actually need reloading, so the pipeline is kept here keyed by (vae, device)
# rather than reloaded on every call.
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

        resolved = device
        if device == "auto":
            resolved = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
        _PIPELINE_CACHE[key] = YuE2Pipeline.from_pretrained(
            MODEL_ID,
            vae=vae_repo(vae),
            device=device,
            backend=backend_for(torch.device(resolved).type),
        )
    return _PIPELINE_CACHE[key]


def _cancelled():
    try:
        from comfy.model_management import processing_interrupted

        return processing_interrupted()
    except ImportError:
        return False


def _run_interruptible(call, *args, **kwargs):
    """Run a yue2 call so the Cancel button stops it.

    yue2 polls `cancelled()` between tokens and raises InterruptedError;
    ComfyUI expects its own exception type to treat that as a user interrupt
    rather than a node failure.
    """
    try:
        return call(*args, cancelled=_cancelled, **kwargs)
    except InterruptedError:
        try:
            from comfy.model_management import InterruptProcessingException
        except ImportError:
            raise
        raise InterruptProcessingException() from None


def _to_comfy_audio(audio, sample_rate):
    """yue2's [samples, channels] (or mono [samples]) array -> ComfyUI AUDIO [1, C, T]."""
    array = np.asarray(audio, dtype=np.float32)
    if array.ndim == 1:
        array = array[:, None]
    waveform = torch.from_numpy(np.ascontiguousarray(array.T)).unsqueeze(0)
    return {"waveform": waveform, "sample_rate": int(sample_rate)}


class YuE2ModelLoader:
    """Loads the YuE2-3B pipeline once and hands it to the other nodes.

    Model weights are CC BY-NC 4.0 (non-commercial use only) - see README.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "vae": (VAE_CHOICES, {"default": VAE_CHOICES[0]}),
                # "auto" = CUDA if there is one, else Apple MPS, else CPU
                "device": ("STRING", {"default": "auto"}),
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
        plan = _run_interruptible(pipeline.plan, style=style, lyrics=lyrics, cot="full", seed=seed)
        return (plan.abc or "",)


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

    @classmethod
    def VALIDATE_INPUTS(cls, cot=None, abc=None):
        # None = wired from another node, unknowable until execution
        if cot is None or abc is None:
            return True
        return generate_error(cot, abc) or True

    def generate(self, pipeline, style, lyrics, cot, seed, abc=""):
        kwargs = build_generate_kwargs(style, lyrics, cot, seed, abc)
        song = _run_interruptible(pipeline, **kwargs)
        # with cot=off there is no score; hand back what came in so a chained
        # node still gets a string
        return (_to_comfy_audio(song.audio, song.sample_rate), song.abc or abc or "")
