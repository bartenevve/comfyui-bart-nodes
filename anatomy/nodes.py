import base64
import io

import numpy as np
import torch
from PIL import Image

from . import ollama
from .selection import (
    CHECKS,
    build_prompt,
    decide,
    format_report,
    indices_string,
    parse_verdict,
    report_json,
    selected_keys,
    split_indices,
    VerdictError,
)

EMPTY_BRANCH_MODES = ["blocker", "placeholder"]
VERDICT_ATTEMPTS = 2


def _tensor_to_b64(image, max_side):
    """One IMAGE slice [H, W, C] float 0..1 -> base64 JPEG, longest side <= max_side."""
    array = (image.detach().cpu().numpy() * 255.0).clip(0, 255).astype(np.uint8)
    pil = Image.fromarray(array[..., :3])
    longest = max(pil.size)
    if longest > max_side:
        scale = max_side / longest
        pil = pil.resize((max(1, round(pil.width * scale)), max(1, round(pil.height * scale))), Image.LANCZOS)
    buffer = io.BytesIO()
    pil.save(buffer, format="JPEG", quality=92)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _progress_bar(total):
    try:
        from comfy.utils import ProgressBar

        return ProgressBar(total)
    except Exception:
        return None


def _check_interrupted():
    try:
        from comfy.model_management import throw_exception_if_processing_interrupted

        throw_exception_if_processing_interrupted()
    except ImportError:
        pass


def _empty_branch(mode, height, width):
    if mode == "placeholder":
        return torch.zeros((1, height, width, 3), dtype=torch.float32)
    try:
        from comfy_execution.graph import ExecutionBlocker
    except ImportError as exc:
        raise RuntimeError(
            "empty_branch=blocker needs a ComfyUI version with ExecutionBlocker "
            "(comfy_execution.graph); switch empty_branch to placeholder"
        ) from exc
    return ExecutionBlocker(None)


class AnatomyDefectFilter:
    """Splits an image batch into passed / failed by asking an Ollama vision
    model whether each image has the selected anatomy defects.

    Needs a chat-capable vision model (qwen3-vl, llama3.2-vision, gemma3, ...);
    a plain embedding model cannot answer "does this hand have six fingers".
    """

    @classmethod
    def INPUT_TYPES(cls):
        checks = {key: ("BOOLEAN", {"default": key in ("extra_limbs", "bad_fingers", "smeared_limbs", "impossible_pose")}) for key in CHECKS}
        return {
            "required": {
                "images": ("IMAGE",),
                "ollama_url": ("STRING", {"default": "http://localhost:11434"}),
                "model": ("STRING", {"default": "qwen3-vl:8b"}),
                **checks,
                "custom_criterion": ("STRING", {"default": "", "multiline": True}),
                "confidence_threshold": ("FLOAT", {"default": 0.6, "min": 0.0, "max": 1.0, "step": 0.05}),
                "max_side": ("INT", {"default": 768, "min": 128, "max": 4096, "step": 64}),
                "timeout": ("INT", {"default": 120, "min": 5, "max": 3600}),
                "num_ctx": ("INT", {"default": 4096, "min": 2048, "max": 32768, "step": 512}),
                # Ollama reads the seed as a signed 64-bit int; keep well inside that
                "seed": ("INT", {"default": 0, "min": 0, "max": 0x7FFFFFFF}),
                "empty_branch": (EMPTY_BRANCH_MODES, {"default": EMPTY_BRANCH_MODES[0]}),
            },
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("passed", "failed", "report", "report_json", "passed_indices", "failed_indices")
    FUNCTION = "filter"
    CATEGORY = "image/quality"

    def filter(
        self,
        images,
        ollama_url,
        model,
        custom_criterion,
        confidence_threshold,
        max_side,
        timeout,
        num_ctx,
        seed,
        empty_branch,
        **checks,
    ):
        keys = selected_keys({key for key in CHECKS if checks.get(key)}, custom_criterion)
        prompt = build_prompt(keys, custom_criterion)

        count, height, width = images.shape[0], images.shape[1], images.shape[2]
        progress = _progress_bar(count)
        results = []
        for index in range(count):
            _check_interrupted()
            image_b64 = _tensor_to_b64(images[index], max_side)
            verdict = self._ask(ollama_url, model, prompt, image_b64, keys, timeout, num_ctx, seed, index)
            passed, failed_checks = decide(verdict, confidence_threshold)
            results.append(
                {"index": index, "passed": passed, "failed_checks": failed_checks, "checks": verdict}
            )
            if progress is not None:
                progress.update(1)

        passed_idx, failed_idx = split_indices([item["passed"] for item in results])
        passed_images = (
            images[torch.tensor(passed_idx, dtype=torch.long)]
            if passed_idx
            else _empty_branch(empty_branch, height, width)
        )
        failed_images = (
            images[torch.tensor(failed_idx, dtype=torch.long)]
            if failed_idx
            else _empty_branch(empty_branch, height, width)
        )

        return (
            passed_images,
            failed_images,
            format_report(results),
            report_json(results),
            indices_string(passed_idx),
            indices_string(failed_idx),
        )

    @staticmethod
    def _ask(url, model, prompt, image_b64, keys, timeout, num_ctx, seed, index):
        last_error = None
        for attempt in range(VERDICT_ATTEMPTS):
            # a different seed on the retry: same seed + same image would
            # just reproduce the same unparsable answer
            answer = ollama.chat(url, model, prompt, image_b64, timeout=timeout, seed=seed + attempt, num_ctx=num_ctx)
            try:
                return parse_verdict(answer, keys)
            except VerdictError as exc:
                last_error = exc
        raise RuntimeError(
            f"image #{index}: {model!r} did not return a usable verdict after "
            f"{VERDICT_ATTEMPTS} attempts ({last_error}). Try a larger/other vision model."
        )

    @classmethod
    def VALIDATE_INPUTS(
        cls,
        ollama_url=None,
        model=None,
        custom_criterion=None,
        extra_limbs=None,
        missing_limbs=None,
        bad_fingers=None,
        smeared_limbs=None,
        impossible_pose=None,
        face_deformation=None,
        merged_bodies=None,
    ):
        # Parameters are listed explicitly rather than **kwargs (a catch-all
        # makes ComfyUI skip its own type/range validation for every other
        # input too) and default to None: an input wired from another node has
        # no value at validation time, and what can't be known isn't checked.
        # Keep in step with selection.CHECKS.
        checks = {key: value for key, value in locals().items() if key in CHECKS}
        if ollama_url is not None:
            try:
                ollama.normalize_url(ollama_url)
            except ollama.OllamaError as exc:
                return str(exc)
        if model is not None and not model.strip():
            return "model is empty"
        if custom_criterion is not None and all(value is not None for value in checks.values()):
            if not selected_keys({key for key, value in checks.items() if value}, custom_criterion):
                return "enable at least one defect check or fill in custom_criterion"
        return True
