import hashlib

import torch

from .. import imageload
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
                # written by the frontend whenever the user changes the position by hand (see selection.py)
                "edit_serial": ("STRING", {"default": ""}),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK", "STRING", "STRING", "STRING", "INT")
    RETURN_NAMES = ("IMAGE", "MASK", "post_id", "post_tags", "post_url", "index")
    FUNCTION = "load_image"
    CATEGORY = "Bart's nodes/Image"

    def load_image(
        self,
        source,
        tags,
        random_post,
        increment_on_queue,
        index,
        last_post_id="",
        edit_serial="",
        unique_id=None,
    ):
        result = picker.pick(
            source,
            tags,
            random_post=random_post,
            increment_on_queue=increment_on_queue,
            index=index,
            unique_id=unique_id,
            edit_serial=edit_serial,
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
        cls, source="", tags="", random_post=False, increment_on_queue=False, index=0, last_post_id="",
        edit_serial="", unique_id=None
    ):
        # defaults everywhere: ComfyUI leaves a linked input out of the call (see LoadRandomImage)
        if random_post or increment_on_queue:
            return float("nan")
        source, tags = source or "", tags or ""
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
    rgb, mask = imageload.load_frames(path)
    return torch.from_numpy(rgb), torch.from_numpy(mask)
