import hashlib
import os

import folder_paths
import torch

from .. import imageload
from .selection import IMAGE_EXTENSIONS, PathError, join_inside, split_image_path


def resolve_image(value):
    """Absolute path of an input-folder-relative image, or a PathError / FileNotFoundError."""
    if not (value or "").strip():
        raise FileNotFoundError("no image selected - open the picker and choose one")
    subfolder, filename = split_image_path(value)
    if os.path.splitext(filename)[1].lower() not in IMAGE_EXTENSIONS:
        raise PathError(f"not an image file: {filename}")
    path = join_inside(folder_paths.get_input_directory(), subfolder, filename)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"image not found in the input folder: {value}")
    return path


class ImagePicker:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            # A plain string rather than a combo: the combo would have to list
            # every file (and subfolder) up front, and ComfyUI rejects a value
            # that isn't in it. The gallery on the node writes this path.
            "required": {"image": ("STRING", {"default": ""})},
        }

    RETURN_TYPES = ("IMAGE", "MASK", "STRING", "INT", "INT")
    RETURN_NAMES = ("IMAGE", "MASK", "filename", "width", "height")
    FUNCTION = "load_image"
    CATEGORY = "Bart's nodes/Image"

    def load_image(self, image):
        path = resolve_image(image)
        rgb, mask = imageload.load_frames(path)
        image_out = torch.from_numpy(rgb)
        mask_out = torch.from_numpy(mask)

        height, width = image_out.shape[1], image_out.shape[2]
        return {
            "ui": {"size": [f"{width}x{height}"]},
            "result": (image_out, mask_out, image.replace("\\", "/").strip(), width, height),
        }

    @classmethod
    def IS_CHANGED(cls, image=None):
        try:
            path = resolve_image(image)
        except (PathError, FileNotFoundError):
            return float("nan")
        digest = hashlib.sha256(image.encode("utf-8"))
        with open(path, "rb") as handle:
            digest.update(handle.read())
        return digest.hexdigest()

    @classmethod
    def VALIDATE_INPUTS(cls, image=None):
        # None = wired from another node, unknowable here
        if image is None:
            return True
        try:
            resolve_image(image)
        except (PathError, FileNotFoundError) as exc:
            return str(exc)
        return True
