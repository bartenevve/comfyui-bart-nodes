import logging

import torch

from .selection import TEMPORAL_RATIO, plan_trim

logger = logging.getLogger("comfyui-bart-nodes")


class WanLatentTrim:
    """Cut frames from the START of a WAN video latent, before the VAE decode.

    The count is in *pixel* frames and converted to whole latent frames
    (4 pixel frames each), so a request that isn't a multiple of 4 is snapped
    to the nearest latent boundary; `removed_frames` reports what really went.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "samples": ("LATENT",),
                "trim_start_frames": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 16384,
                        "step": 1,
                        "tooltip": (
                            "Pixel frames to remove from the start. Converted to latent frames as "
                            f"round(N / {TEMPORAL_RATIO}); multiples of {TEMPORAL_RATIO} are exact."
                        ),
                    },
                ),
            },
        }

    # the two INT outputs are appended after the original LATENT, so a link made
    # to `samples` keeps its slot
    RETURN_TYPES = ("LATENT", "INT", "INT")
    RETURN_NAMES = ("samples", "removed_frames", "frames_left")
    FUNCTION = "trim"
    CATEGORY = "Bart's nodes/Latent"
    DESCRIPTION = (
        "Cut frames from the start of a WAN video latent before VAE decode. The count is in pixel frames, "
        "converted to latent frames (4x temporal compression) and snapped to the nearest latent boundary."
    )

    def trim(self, samples, trim_start_frames):
        latent = samples.copy()
        tensor = latent["samples"]

        if tensor.dim() != 5:
            raise ValueError(
                f"WanLatentTrim expects a 5D video latent [B, C, T, H, W], got shape {tuple(tensor.shape)} "
                f"({tensor.dim()}D). This node is for WAN video latents, not image latents."
            )

        num_frames = tensor.shape[2]
        cut, removed, left = plan_trim(trim_start_frames, num_frames)
        if cut == 0:
            return (latent, 0, left)

        latent["samples"] = tensor[:, :, cut:, :, :].contiguous()

        # a per-frame mask has to lose the same frames or it no longer lines up
        mask = latent.get("noise_mask")
        if isinstance(mask, torch.Tensor) and mask.dim() == 5 and mask.shape[2] == num_frames:
            latent["noise_mask"] = mask[:, :, cut:, :, :].contiguous()

        logger.info(
            "WanLatentTrim: removed %d latent frame(s) (%d px frames) from the start; T %d -> %d",
            cut, removed, num_frames, num_frames - cut,
        )
        return (latent, removed, left)
