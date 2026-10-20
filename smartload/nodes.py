import hashlib
import os

import folder_paths
import numpy as np
import torch
from PIL import Image, ImageOps, ImageSequence

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
        img = Image.open(image_path)

        output_images = []
        output_masks = []
        for frame in ImageSequence.Iterator(img):
            frame = ImageOps.exif_transpose(frame)
            if frame.mode == "I":
                frame = frame.point(lambda i: i * (1 / 255))

            x, y, width, height = clamp_box(crop_x, crop_y, crop_width, crop_height, frame.width, frame.height)
            frame = frame.crop((x, y, x + width, y + height))

            rgb_image = frame.convert("RGB")
            arr = np.array(rgb_image).astype(np.float32) / 255.0
            output_images.append(torch.from_numpy(arr)[None,])

            if "A" in frame.getbands():
                mask_arr = np.array(frame.getchannel("A")).astype(np.float32) / 255.0
                mask = 1.0 - torch.from_numpy(mask_arr)
            else:
                mask = torch.zeros((frame.height, frame.width), dtype=torch.float32)
            output_masks.append(mask.unsqueeze(0))

        first_shape = output_images[0].shape
        if len(output_images) > 1 and all(t.shape == first_shape for t in output_images):
            image_out = torch.cat(output_images, dim=0)
            mask_out = torch.cat(output_masks, dim=0)
        else:
            # a single image, or animation frames of differing sizes (batching
            # those would fail): keep the first
            image_out, mask_out = output_images[0], output_masks[0]

        height_out, width_out = image_out.shape[1], image_out.shape[2]
        return {
            "ui": {"size": [f"{width_out}x{height_out}"]},
            "result": (image_out, mask_out, width_out, height_out, os.path.basename(image_path)),
        }

    @classmethod
    def IS_CHANGED(cls, image, crop_x, crop_y, crop_width, crop_height, aspect_lock="free", snap_to="1"):
        digest = hashlib.sha256()
        with open(folder_paths.get_annotated_filepath(image), "rb") as handle:
            digest.update(handle.read())
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
