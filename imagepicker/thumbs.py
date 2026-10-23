import os
import threading
import uuid

from PIL import Image

from .. import imageload


# A decoded image costs width x height x 3-4 bytes whatever its file size (a 150-megapixel all-black PNG
# is a few hundred KB on disk and about a gigabyte in memory), and the gallery asks for many at once.
MAX_PIXELS = 64_000_000


class ImageTooLarge(ValueError):
    pass


def make_thumb(source, target, size):
    """Write a WebP thumbnail of `source` (first frame, EXIF-rotated, at most size x size) to `target`.

    The file is written under a name nobody else can be using and renamed into
    place, so a half-written thumbnail is never served and two requests for the
    same thumbnail (a second tab, a reload while the first is still encoding)
    can't trip over each other's temporary file.
    """
    temporary = f"{target}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex[:8]}.part"
    try:
        with imageload.open_image(source) as img:
            if img.width * img.height > MAX_PIXELS:
                raise ImageTooLarge(f"{img.width}x{img.height} is over the {MAX_PIXELS // 1_000_000} megapixel preview limit")
            if img.format == "JPEG":
                img.draft("RGB", (size * 2, size * 2))  # decode at reduced scale: much faster for big photos
            img = imageload.eight_bit(imageload.upright(img))
            has_alpha = "A" in img.getbands() or "transparency" in img.info
            img = img.convert("RGBA" if has_alpha else "RGB")
            img.thumbnail((size, size), Image.Resampling.LANCZOS)
            img.save(temporary, "WEBP", quality=80, method=4)
        os.replace(temporary, target)
    finally:
        # after a successful rename there is nothing left to remove; after a failure this
        # keeps unreadable or oversized files from leaving .part litter in the cache folder
        try:
            os.remove(temporary)
        except OSError:
            pass
