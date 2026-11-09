"""Pure logic of the VoxCPM nodes (no torch, no voxcpm): presets, option checks, the prompt text and
the call's keyword arguments, and a dependency-free WAV writer for the reference audio."""
import wave

import numpy as np

# Hugging Face repositories the loader offers (the weights are Apache-2.0). VoxCPM2 is the only one
# with Voice Design and reference-audio cloning; 1.5 and 0.5B are continuation-only, zh/en.
PRESET_MODELS = ("openbmb/VoxCPM2", "openbmb/VoxCPM1.5", "openbmb/VoxCPM-0.5B")
DEVICES = ("auto", "cuda", "mps", "cpu")

# 2**53 - 1: the most a JS number (how the frontend stores widget values) holds exactly
MAX_SEED = 2**53 - 1
MAX_TEXT = 20000  # characters: far more than a model reads in one go, but a bound all the same
MAX_DESCRIPTION = 500

# what `generate()` is called with when the widget is left alone (the upstream defaults)
DEFAULTS = {
    "cfg_value": 2.0,
    "inference_timesteps": 10,
    "max_len": 4096,
    "normalize": False,
    "denoise": False,
    "retry_badcase": True,
    "retry_badcase_max_times": 3,
    "retry_badcase_ratio_threshold": 6.0,
}


class InputError(ValueError):
    """A widget value the model cannot use."""


def compose_text(text, voice_description=""):
    """The text VoxCPM2 is given: a voice description goes in parentheses in front of it.

    "(A young woman, gentle and sweet voice)Hello!" designs a voice (no reference audio) or steers the
    style of a cloned one ("(slightly faster, cheerful tone)..."). Parentheses inside the description
    would end it early, so they are dropped.
    """
    text = (text or "").strip()
    if not text:
        raise InputError("text is empty")
    if len(text) > MAX_TEXT:
        raise InputError(f"text is too long ({len(text)} characters, the limit is {MAX_TEXT})")
    description = " ".join((voice_description or "").replace("(", " ").replace(")", " ").split())
    if len(description) > MAX_DESCRIPTION:
        raise InputError(f"voice_description is too long ({len(description)} characters, the limit is {MAX_DESCRIPTION})")
    return f"({description}){text}" if description else text


def mode_name(has_reference, has_prompt, has_description):
    """What the run is, for the info output."""
    if has_prompt and has_reference:
        return "ultimate cloning (prompt + reference)"
    if has_prompt:
        return "continuation cloning (prompt audio + transcript)"
    if has_reference:
        return "controllable cloning (reference audio)" + (" with style" if has_description else "")
    return "voice design" if has_description else "text to speech"


def check_prompt(has_prompt_audio, prompt_text):
    """The prompt audio and its transcript go together (upstream raises deep inside otherwise)."""
    has_text = bool((prompt_text or "").strip())
    if has_prompt_audio and not has_text:
        raise InputError("prompt_audio needs prompt_text: the exact transcript of that audio")
    if has_text and not has_prompt_audio:
        raise InputError("prompt_text is only used together with prompt_audio: connect it, or clear the text")


def build_kwargs(text, seed, options, reference_path=None, prompt_path=None, prompt_text=None):
    """Keyword arguments of `VoxCPM.generate`, checked and typed; paths only when there is audio."""
    kwargs = {"text": text, "seed": int(seed)}
    values = {**DEFAULTS, **{k: v for k, v in options.items() if v is not None}}
    ranges = {
        "cfg_value": (0.1, 10.0, float),
        "inference_timesteps": (1, 100, int),
        "max_len": (16, 8192, int),
        "retry_badcase_max_times": (0, 10, int),
        "retry_badcase_ratio_threshold": (1.0, 20.0, float),
    }
    for name, (low, high, kind) in ranges.items():
        try:
            number = kind(values[name])
        except (TypeError, ValueError, OverflowError):
            raise InputError(f"{name} must be a number, got {values[name]!r}") from None
        if not low <= number <= high:
            raise InputError(f"{name} must be {low}..{high}, got {number}")
        kwargs[name] = number
    for name in ("normalize", "denoise", "retry_badcase"):
        kwargs[name] = bool(values[name])
    if reference_path:
        kwargs["reference_wav_path"] = reference_path
    if prompt_path:
        kwargs["prompt_wav_path"] = prompt_path
        kwargs["prompt_text"] = prompt_text.strip()
    return kwargs


def mono_float(waveform):
    """ComfyUI AUDIO waveform [batch, channels, samples] (or [channels, samples] / [samples]) -> 1-D float32.

    The first batch item, channels averaged: VoxCPM takes a mono reference.
    """
    array = np.asarray(waveform, dtype=np.float32)
    while array.ndim > 2:
        array = array[0]
    if array.ndim == 2:
        array = array.mean(axis=0)
    if array.size == 0:
        raise InputError("the audio input is empty")
    return np.nan_to_num(array, nan=0.0, posinf=0.0, neginf=0.0)


def write_wav(path, samples, sample_rate):
    """16-bit PCM mono WAV from float samples in [-1, 1] (clipped), stdlib only."""
    data = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    pcm = (data * 32767.0).astype("<i2")
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(sample_rate))
        handle.writeframes(pcm.tobytes())


def info_line(model_id, mode, samples, sample_rate, seed):
    seconds = samples / float(sample_rate) if sample_rate else 0.0
    return f"{mode} | {model_id} | {seconds:.1f} s at {int(sample_rate)} Hz | seed {int(seed)}"
