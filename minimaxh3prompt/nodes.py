import hashlib

from . import runner
from .selection import (
    ASPECTS,
    FPS,
    MAX_SEED,
    MODES,
    NUMERIC,
    VARIANTS,
    InputError,
    clip_durations,
    frame_size,
    split_timed_clips,
)

_WIDGETS = (
    "ollama_url", "model", "request", "duration", "aspect", "mode", "variant", "seed",
    "triggers", "dialogue", "text", "image", "start", "end", "shots", "refs",
    "temperature", "num_ctx", "num_predict", "retries", "timeout", "think", "append_no_think", "short_side",
)


class MiniMaxH3Prompt:
    @classmethod
    def INPUT_TYPES(cls):
        def number(name):
            default, low, high = NUMERIC[name]
            return ("INT", {"default": default, "min": low, "max": high})

        return {
            "required": {
                "ollama_url": ("STRING", {"default": "http://localhost:11434"}),
                "model": ("STRING", {"default": "qwen3:4b-instruct"}),
                "request": ("STRING", {"default": "", "multiline": True}),
                "duration": number("duration"),
                "aspect": (ASPECTS, {"default": "16:9"}),
                "mode": (MODES, {"default": "T2VA"}),
                "variant": (VARIANTS, {"default": "auto"}),
                "seed": number("seed"),
            },
            "optional": {
                "triggers": ("STRING", {"default": ""}),
                "dialogue": ("STRING", {"default": "", "multiline": True}),
                "text": ("STRING", {"default": ""}),
                "image": ("STRING", {"default": ""}),
                "start": ("STRING", {"default": ""}),
                "end": ("STRING", {"default": ""}),
                "shots": number("shots"),
                "refs": ("STRING", {"default": "", "multiline": True}),
                "temperature": ("FLOAT", {"default": 0.3, "min": 0.0, "max": 2.0, "step": 0.05}),
                "num_ctx": number("num_ctx"),
                "num_predict": number("num_predict"),
                "retries": number("retries"),
                "timeout": number("timeout"),
                "think": ("BOOLEAN", {"default": False}),
                # Qwen3's soft switch; thinking models like qwen3-vl ignore the API-level think=false
                "append_no_think": ("BOOLEAN", {"default": True}),
                # The result lives in a widget so it is saved with the workflow,
                # can be edited by hand, and is what the node outputs whenever
                # it is not empty. `generated_key` is the frontend's snapshot of
                # the inputs it was made from (for the "inputs changed" hint).
                "generated": ("STRING", {"default": "", "multiline": True}),
                "generated_key": ("STRING", {"default": ""}),
                # last on purpose: widgets_values are positional, so appending
                # keeps workflows saved before this widget existed loading right
                "short_side": number("short_side"),
            },
        }

    # new outputs are appended: links are saved by slot index, so inserting one
    # in the middle would silently rewire existing workflows
    RETURN_TYPES = ("STRING", "STRING", "INT", "INT", "INT", "INT", "INT")
    RETURN_NAMES = ("prompt", "report", "duration", "frames", "width", "height", "seed")
    # prompt, duration and frames are lists with one entry per clip (a single
    # entry for everything but `story`), so a video node fed by them runs once
    # per clip with that clip's own length; width, height and seed are shared
    OUTPUT_IS_LIST = (True, False, True, True, False, False, False)
    FUNCTION = "run"
    CATEGORY = "Bart's nodes/Text"

    def run(self, ollama_url, model, request, duration, aspect, mode, variant, seed, generated="", generated_key="", **optional):
        width, height = frame_size(aspect, optional.get("short_side") or NUMERIC["short_side"][0])

        def outputs(clips, report, durations):
            frames = [d * FPS for d in durations]
            return (clips, report, durations, frames, width, height, seed)

        timed = split_timed_clips(generated)
        if timed:
            # saved text wins, including hand edits; the Generate button is the
            # only thing that replaces it
            clips = [clip for clip, _ in timed]
            report = f"reused the saved text ({len(clips)} clip{'s' if len(clips) != 1 else ''}), nothing generated"
            return {"ui": {"report": [report]}, "result": outputs(clips, report, clip_durations(timed, duration))}

        values = dict(
            ollama_url=ollama_url, model=model, request=request, duration=duration, aspect=aspect,
            mode=mode, variant=variant, seed=seed, **optional,
        )
        try:
            result = runner.generate(values)
        except (InputError, runner.H3Error) as exc:
            raise RuntimeError(f"MiniMax H3 prompt: {exc}") from None
        return {
            "ui": {"generated": [result["text"]], "report": [result["report"]]},
            "result": outputs(result["clips"], result["report"], result["durations"]),
        }

    @classmethod
    def IS_CHANGED(cls, generated="", **inputs):
        # saved text present: output depends on it alone. Absent: every input
        # (seed included) decides what gets generated.
        if generated.strip():
            return hashlib.sha256(generated.encode("utf-8")).hexdigest()
        payload = "|".join(f"{key}={inputs[key]!r}" for key in sorted(inputs) if key != "generated_key")
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def VALIDATE_INPUTS(cls, generated=None, **inputs):
        # None / missing = wired from another node, unknowable here
        if generated is None or generated.strip():
            return True
        needed = ("ollama_url", "model", "request", "duration", "aspect", "mode", "variant", "seed")
        if any(inputs.get(name) is None for name in needed):
            return True
        values = {name: inputs[name] for name in _WIDGETS if inputs.get(name) is not None}
        try:
            options = runner.coerce_options(values)
            if not options["request"].strip():
                return "request is empty (type a request, or press Generate and keep the saved text)"
            runner.build_request(options)
        except InputError as exc:
            return str(exc)
        return True


__all__ = ["MiniMaxH3Prompt", "MAX_SEED"]
