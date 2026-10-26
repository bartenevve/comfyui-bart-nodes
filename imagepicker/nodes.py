import hashlib
import os

import folder_paths
import torch

from .. import imageload
from .selection import (
    IMAGE_EXTENSIONS,
    MODES,
    PathError,
    choose_image,
    clean_subfolder,
    join_inside,
    list_pool,
    split_image_path,
)

MAX_SEED = 0x7FFFFFFF  # the frontend's seed widget: bigger values lose precision in JavaScript


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
            # appended after `image` on purpose: widgets_values are positional, so workflows saved before
            # these existed keep loading (they get mode = fixed)
            "optional": {
                "mode": (list(MODES), {"default": "fixed"}),
                # the pool of random / sequential: an input-folder-relative folder ("" = the input folder itself)
                "folder": ("STRING", {"default": ""}),
                "include_subfolders": ("BOOLEAN", {"default": False}),
                "seed": ("INT", {"default": 0, "min": 0, "max": MAX_SEED, "control_after_generate": True}),
                # fresh on every hand edit of `image` (written by the frontend): see selection.resolve_filenames
                "edit_serial": ("STRING", {"default": ""}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("IMAGE", "MASK", "STRING", "INT", "INT", "STRING")
    RETURN_NAMES = ("IMAGE", "MASK", "filename", "width", "height", "folder")
    FUNCTION = "load_image"
    CATEGORY = "Bart's nodes/Image"

    @staticmethod
    def _pool(mode, folder, include_subfolders):
        """The images a random / sequential run chooses from (raises on a bad or empty folder)."""
        try:
            files, _ = list_pool(folder_paths.get_input_directory(), folder, bool(include_subfolders))
        except NotADirectoryError:
            raise FileNotFoundError(f"folder not found in the input folder: {folder or '(input folder)'}") from None
        if not files:
            raise FileNotFoundError(f"no images in the {mode} folder: {clean_subfolder(folder) or '(input folder)'}")
        return files

    def load_image(self, image, mode="fixed", folder="", include_subfolders=False, seed=0, edit_serial="", unique_id=None):
        mode = mode if mode in MODES else "fixed"
        next_image = None
        if mode == "fixed":
            value = image
        else:
            pool = self._pool(mode, folder, include_subfolders)
            pool_key = f"image_picker|{clean_subfolder(folder)}|{int(bool(include_subfolders))}"
            value, next_image = choose_image(
                pool, mode, (image or "").replace("\\", "/").strip(), seed, unique_id, pool_key, edit_serial or ""
            )
        path = resolve_image(value)
        rgb, mask = imageload.load_frames(path)
        image_out = torch.from_numpy(rgb)
        mask_out = torch.from_numpy(mask)

        height, width = image_out.shape[1], image_out.shape[2]
        loaded = value.replace("\\", "/").strip()
        ui = {"size": [f"{width}x{height}"], "loaded": [loaded]}
        if next_image is not None:
            ui["next"] = [next_image]  # sequential: the file the NEXT run starts from, pushed into the widget
        return {"ui": ui, "result": (image_out, mask_out, loaded, width, height, loaded.rpartition("/")[0])}

    @classmethod
    def IS_CHANGED(cls, image=None, mode="fixed", folder="", include_subfolders=False, seed=0, **_):
        if mode == "sequential":
            return float("nan")  # stateful: every run moves on
        try:
            if mode == "random":
                image, _next = choose_image(cls._pool(mode, folder, include_subfolders), "random", image, seed)
            path = resolve_image(image)
        except (PathError, FileNotFoundError, OSError, TypeError, ValueError):
            return float("nan")
        digest = hashlib.sha256(image.encode("utf-8"))
        with open(path, "rb") as handle:
            digest.update(handle.read())
        return digest.hexdigest()

    @classmethod
    def VALIDATE_INPUTS(cls, image=None, mode=None, folder=None):
        # None = wired from another node, unknowable here. Only the fixed mode needs a loadable `image`:
        # random ignores it, sequential falls back to the first file of the folder when it is outside the pool.
        if mode in ("random", "sequential"):
            try:
                clean_subfolder(folder)
            except PathError as exc:
                return str(exc)
            return True
        if image is None:
            return True
        try:
            resolve_image(image)
        except (PathError, FileNotFoundError) as exc:
            return str(exc)
        return True
        try:
            resolve_image(image)
        except (PathError, FileNotFoundError) as exc:
            return str(exc)
        return True
