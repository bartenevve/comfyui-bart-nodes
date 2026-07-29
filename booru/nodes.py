import hashlib

import numpy as np
import torch
from PIL import Image, ImageOps, ImageSequence

from . import pick as picker
from . import sources


class LoadRandomBooruImage:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "source": (sources.SOURCE_NAMES, {"default": sources.DEFAULT_SOURCE}),
                "tags": ("STRING", {"default": "", "multiline": True}),
                "random_post": ("BOOLEAN", {"default": True}),
                "increment_on_queue": ("BOOLEAN", {"default": False}),
                "index": ("INT", {"default": 0, "min": 0, "max": sources.max_positions() - 1}),
            },
            "optional": {
                "last_post_id": ("STRING", {"default": ""}),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK", "STRING", "STRING", "STRING", "INT")
    RETURN_NAMES = ("IMAGE", "MASK", "post_id", "post_tags", "post_url", "index")
    FUNCTION = "load_image"
    CATEGORY = "image"

    def load_image(
        self,
        source,
        tags,
        random_post,
        increment_on_queue,
        index,
        last_post_id="",
        unique_id=None,
    ):
        result = picker.pick(
            source,
            tags,
            random_post=random_post,
            increment_on_queue=increment_on_queue,
            index=index,
            unique_id=unique_id,
        )

        image_out, mask_out = load_tensors(result["path"])

        # "ui" is pushed to the frontend as the onExecuted message.
        # `next_index` seeds the widget for the NEXT run (advance-after-output);
        # `post_id`/`index` are what this run actually sent downstream, for the
        # preview and the info line.
        return {
            "ui": {
                "next_index": [result["next_index"]],
                "post_id": [result["post_id"]],
                "index": [result["index"]],
                "total": [result["total"]],
            },
            "result": (
                image_out,
                mask_out,
                result["post_id"],
                result["tags"],
                result["page_url"],
                result["index"],
            ),
        }

    @classmethod
    def IS_CHANGED(
        cls, source, tags, random_post, increment_on_queue, index, last_post_id="", unique_id=None
    ):
        if random_post or increment_on_queue:
            return float("nan")
        # length-prefixed to avoid "a|b","c" vs "a","b|c" hashing identically
        payload = f"{len(source)}:{source}|{len(tags)}:{tags}|{index}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @classmethod
    def VALIDATE_INPUTS(
        cls, source, tags, random_post, increment_on_queue, index, last_post_id="", unique_id=None
    ):
        if random_post and increment_on_queue:
            return "random_post and increment_on_queue cannot both be enabled"
        if source not in sources.SOURCE_NAMES:
            return f"unknown booru source: {source}"
        return True


def load_tensors(path):
    """Decode a downloaded file into ComfyUI's (IMAGE, MASK) tensor pair."""
    img = Image.open(path)

    output_images = []
    output_masks = []
    for frame in ImageSequence.Iterator(img):
        frame = ImageOps.exif_transpose(frame)
        if frame.mode == "I":
            frame = frame.point(lambda i: i * (1 / 255))
        rgb_image = frame.convert("RGB")
        arr = np.array(rgb_image).astype(np.float32) / 255.0
        tensor = torch.from_numpy(arr)[None,]

        if "A" in frame.getbands():
            mask_arr = np.array(frame.getchannel("A")).astype(np.float32) / 255.0
            mask = 1.0 - torch.from_numpy(mask_arr)
        else:
            mask = torch.zeros((frame.height, frame.width), dtype=torch.float32)

        output_images.append(tensor)
        output_masks.append(mask.unsqueeze(0))

    if len(output_images) > 1:
        # animated GIFs from a booru vary in frame size once the first frame is
        # a full canvas and the rest are diffs; torch.cat would explode, so
        # only batch frames that genuinely share a shape
        first_shape = output_images[0].shape
        if all(t.shape == first_shape for t in output_images):
            return torch.cat(output_images, dim=0), torch.cat(output_masks, dim=0)
        return output_images[0], output_masks[0]

    return output_images[0], output_masks[0]
