import hashlib
import os

import numpy as np
import torch
from PIL import Image, ImageOps, ImageSequence

from .selection import list_images, resolve_filenames


class LoadRandomImage:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "directory": ("STRING", {"default": ""}),
                "randomize_on_queue": ("BOOLEAN", {"default": False}),
                "sequential_on_queue": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "filename": ("STRING", {"default": ""}),
                "last_loaded": ("STRING", {"default": ""}),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK", "STRING", "STRING")
    RETURN_NAMES = ("IMAGE", "MASK", "filename", "directory")
    FUNCTION = "load_image"
    CATEGORY = "Bart's nodes/Image"

    def load_image(
        self,
        directory,
        randomize_on_queue,
        sequential_on_queue,
        filename="",
        last_loaded="",
        unique_id=None,
    ):
        directory = os.path.realpath(directory)
        if not os.path.isdir(directory):
            raise NotADirectoryError(f"Not a directory: {directory}")

        files = list_images(directory)
        if not files:
            raise FileNotFoundError(f"No images found in directory: {directory}")

        chosen, next_filename = resolve_filenames(
            files, randomize_on_queue, sequential_on_queue, filename, unique_id, directory=directory
        )
        image_path = os.path.join(directory, chosen)

        img = Image.open(image_path)

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
            image_out = torch.cat(output_images, dim=0)
            mask_out = torch.cat(output_masks, dim=0)
        else:
            image_out = output_images[0]
            mask_out = output_masks[0]

        # "ui" is pushed to the frontend as the onExecuted message.
        # `filename` seeds the widget for the NEXT run (advance-after-output);
        # `last_loaded` is what this run actually sent downstream, for preview.
        return {
            "ui": {"filename": [next_filename], "last_loaded": [chosen]},
            "result": (image_out, mask_out, chosen, directory),
        }

    @classmethod
    def IS_CHANGED(
        cls, directory, randomize_on_queue, sequential_on_queue, filename="", last_loaded="", unique_id=None
    ):
        if randomize_on_queue or sequential_on_queue:
            return float("nan")
        # length-prefixed to avoid "a|b","c" vs "a","b|c" hashing identically
        return hashlib.sha256(f"{len(directory)}:{directory}|{filename}".encode("utf-8")).hexdigest()

    @classmethod
    def VALIDATE_INPUTS(
        cls, directory, randomize_on_queue, sequential_on_queue, filename="", last_loaded="", unique_id=None
    ):
        if randomize_on_queue and sequential_on_queue:
            return "randomize_on_queue and sequential_on_queue cannot both be enabled"
        if not directory:
            return "Directory path is empty"
        real_dir = os.path.realpath(directory)
        if not os.path.isdir(real_dir):
            return f"Not a valid directory: {directory}"
        return True
