import hashlib
import os

import torch

from .imageload import load_frames
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
                # written by the frontend whenever the user changes the file by hand (see selection.py)
                "edit_serial": ("STRING", {"default": ""}),
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
        edit_serial="",
        unique_id=None,
    ):
        directory = os.path.realpath(directory)
        if not os.path.isdir(directory):
            raise NotADirectoryError(f"Not a directory: {directory}")

        files = list_images(directory)
        if not files:
            raise FileNotFoundError(f"No images found in directory: {directory}")

        chosen, next_filename = resolve_filenames(
            files, randomize_on_queue, sequential_on_queue, filename, unique_id, directory=directory, edit_serial=edit_serial
        )
        image_path = os.path.join(directory, chosen)

        rgb, mask = load_frames(image_path)
        image_out = torch.from_numpy(rgb)
        mask_out = torch.from_numpy(mask)

        # "ui" is pushed to the frontend as the onExecuted message.
        # `filename` seeds the widget for the NEXT run (advance-after-output);
        # `last_loaded` is what this run actually sent downstream, for preview.
        return {
            "ui": {"filename": [next_filename], "last_loaded": [chosen]},
            "result": (image_out, mask_out, chosen, directory),
        }

    @classmethod
    def IS_CHANGED(
        cls, directory="", randomize_on_queue=False, sequential_on_queue=False, filename="", last_loaded="",
        edit_serial="", unique_id=None
    ):
        # every parameter has a default: ComfyUI leaves a linked input out of the call, and a
        # missing argument would only log a warning and force a re-run (a value that arrives
        # over a link is covered by the cache key's upstream signature)
        if randomize_on_queue or sequential_on_queue:
            return float("nan")
        directory, filename = directory or "", filename or ""
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
