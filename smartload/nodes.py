import hashlib
import os

import folder_paths
import torch

from .. import imageload
from .selection import ASPECT_LOCKS, MAX_PIXELS, SNAPS, clamp_box


class SmartLoadImage:
    @classmethod
    def INPUT_TYPES(cls):
        input_dir = folder_paths.get_input_directory()
        files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f))]
        files = folder_paths.filter_files_content_types(files, ["image"])
        crop = ("INT", {"default": 0, "min": 0, "max": MAX_PIXELS})
        return {
            "required": {
                "image": (sorted(files),),
                # pixels of the ORIGINAL image; width or height 0 = keep everything
                "crop_x": crop,
                "crop_y": crop,
                "crop_width": crop,
                "crop_height": crop,
            },
            "optional": {
                # helpers for the on-node crop editor (the numbers above are what counts)
                "aspect_lock": (ASPECT_LOCKS, {"default": "free"}),
                "snap_to": ([str(step) for step in SNAPS], {"default": "1"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK", "INT", "INT", "STRING")
    RETURN_NAMES = ("IMAGE", "MASK", "width", "height", "filename")
    FUNCTION = "load_image"
    CATEGORY = "Bart's nodes/Image"

    def load_image(self, image, crop_x, crop_y, crop_width, crop_height, aspect_lock="free", snap_to="1"):
        image_path = folder_paths.get_annotated_filepath(image)
        rgb, mask = imageload.load_frames(
            image_path, box=lambda width, height: clamp_box(crop_x, crop_y, crop_width, crop_height, width, height)
        )
        image_out = torch.from_numpy(rgb)
        mask_out = torch.from_numpy(mask)

        height_out, width_out = image_out.shape[1], image_out.shape[2]
        return {
            "ui": {"size": [f"{width_out}x{height_out}"]},
            "result": (image_out, mask_out, width_out, height_out, os.path.basename(image_path)),
        }

    @classmethod
    def IS_CHANGED(cls, image=None, crop_x=0, crop_y=0, crop_width=0, crop_height=0, aspect_lock="free", snap_to="1"):
        digest = hashlib.sha256()
        try:
            with open(folder_paths.get_annotated_filepath(image), "rb") as handle:
                digest.update(handle.read())
        except Exception:  # no file to hash (unset, linked, missing): VALIDATE_INPUTS reports it
            return float("nan")
        digest.update(f"|{crop_x},{crop_y},{crop_width},{crop_height}".encode("utf-8"))
        return digest.hexdigest()

    @classmethod
    def VALIDATE_INPUTS(cls, image=None):
        # only `image` is named so ComfyUI keeps validating the other inputs itself;
        # None = wired from another node, unknowable here
        if image is None:
            return True
        if not folder_paths.exists_annotated_filepath(image):
            return f"Invalid image file: {image}"
        return True
