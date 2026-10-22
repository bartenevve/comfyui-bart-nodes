"""Image decoding shared by every loader node of the pack (PIL, and numpy only when arrays are built).

Four nodes read image files (Load Random Image, Image Picker, Smart Load Image,
Load Random Booru Image) and the gallery makes thumbnails of the same files; they
all go through here so a file behaves the same way in each of them.
"""
import threading

from PIL import Image, ImageFile, ImageOps, ImageSequence

_LENIENT_LOCK = threading.Lock()

# 16-bit grayscale as PIL names it (PNG, TIFF)
_SIXTEEN_BIT_MODES = ("I;16", "I;16L", "I;16B", "I;16N")


def lenient(function, *args):
    """Call `function(*args)`; if PIL refuses a damaged file, retry once accepting truncated data.

    A JPEG whose download was cut off decodes fine up to the cut (the rest stays
    grey), and ComfyUI's own Load Image does the same - without this one such
    file in a big folder stops a random/sequential run with an OSError. The flag
    is process-wide, so the retry holds a lock and restores the previous value.
    """
    try:
        return function(*args)
    except (OSError, ValueError):  # truncated data, "broken PNG file" (PIL issues #4472, #2445)
        with _LENIENT_LOCK:
            previous = ImageFile.LOAD_TRUNCATED_IMAGES
            ImageFile.LOAD_TRUNCATED_IMAGES = True
            try:
                return function(*args)
            finally:
                ImageFile.LOAD_TRUNCATED_IMAGES = previous


def open_image(path):
    return lenient(Image.open, path)


def upright(frame):
    """The frame with its EXIF orientation applied (this is also where pixel data gets decoded)."""
    return lenient(ImageOps.exif_transpose, frame)


def eight_bit(frame):
    """16-bit grayscale (a depth map, a medical scan) scaled down to 8 bits.

    Converting such a frame straight to RGB only clips every value above 255,
    which turns almost the whole image white.
    """
    if frame.mode in _SIXTEEN_BIT_MODES or frame.mode == "I":
        return frame.point(lambda value: value * (1 / 256)).convert("L")
    return frame


def frame_arrays(frame):
    """(rgb, mask) float32 arrays for one frame: HxWx3 in 0..1, and HxW where 1 = transparent.

    The mask is `1 - alpha` like ComfyUI's Load Image and all zeros for an image
    without transparency. Palette images (GIF, PNG8) and images with a colour key
    carry their transparency outside an alpha band; it is honoured too.
    """
    import numpy as np

    frame = eight_bit(frame)
    if "transparency" in frame.info and "A" not in frame.getbands():
        frame = frame.convert("RGBA")
    rgb = np.array(frame.convert("RGB")).astype(np.float32) / 255.0
    if "A" in frame.getbands():
        mask = 1.0 - np.array(frame.getchannel("A")).astype(np.float32) / 255.0
    else:
        mask = np.zeros((frame.height, frame.width), dtype=np.float32)
    return rgb, mask


def load_frames(path, box=None):
    """Every frame of an image file as numpy arrays: rgb [N, H, W, 3] and mask [N, H, W].

    `box(width, height)` may return the (x, y, w, h) region to keep, asked per
    frame. A frame whose size differs from the first one is dropped (a batch
    needs one size), which is what ComfyUI's own Load Image does with
    animations.
    """
    import numpy as np

    rgbs, masks, size = [], [], None
    with open_image(path) as frames:  # closes the file even for animations, which PIL keeps open
        for frame in ImageSequence.Iterator(frames):
            frame = upright(frame)
            if box is not None:
                x, y, width, height = box(frame.width, frame.height)
                frame = frame.crop((x, y, x + width, y + height))
            if size is None:
                size = frame.size
            elif frame.size != size:
                continue
            rgb, mask = frame_arrays(frame)
            rgbs.append(rgb)
            masks.append(mask)
    return np.stack(rgbs), np.stack(masks)
