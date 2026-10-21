import hashlib
import os

import folder_paths
import numpy as np
import torch
from PIL import Image, ImageOps, ImageSequence

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
        img = Image.open(path)

        output_images = []
        output_masks = []
        for frame in ImageSequence.Iterator(img):
            frame = ImageOps.exif_transpose(frame)
            if frame.mode == "I":
                frame = frame.point(lambda i: i * (1 / 255))
            rgb_image = frame.convert("RGB")
            output_images.append(torch.from_numpy(np.array(rgb_image).astype(np.float32) / 255.0)[None,])
            if "A" in frame.getbands():
                mask = 1.0 - torch.from_numpy(np.array(frame.getchannel("A")).astype(np.float32) / 255.0)
            else:
                mask = torch.zeros((frame.height, frame.width), dtype=torch.float32)
            output_masks.append(mask.unsqueeze(0))

        first_shape = output_images[0].shape
        if len(output_images) > 1 and all(t.shape == first_shape for t in output_images):
            image_out = torch.cat(output_images, dim=0)
            mask_out = torch.cat(output_masks, dim=0)
        else:
            # one image, or animation frames of differing sizes that can't batch
            image_out, mask_out = output_images[0], output_masks[0]

        height, width = image_out.shape[1], image_out.shape[2]
        return {
            "ui": {"size": [f"{width}x{height}"]},
            "result": (image_out, mask_out, image.replace("\\", "/").strip(), width, height),
        }

    @classmethod
    def IS_CHANGED(cls, image):
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
