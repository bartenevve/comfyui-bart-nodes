# the frontend's aspect-lock dropdown and snap grid; the server never uses
# them to crop (the crop_* numbers are authoritative), they only have to exist
# as widgets so they are saved with the workflow
ASPECT_LOCKS = ["free", "original", "1:1", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16", "21:9", "9:21"]
SNAPS = [1, 8, 16, 32, 64]

# crop widget ceiling: far beyond any real image, small enough to stay an int a JS number holds
MAX_PIXELS = 65535


def clamp_box(x, y, width, height, image_width, image_height):
    """(x, y, width, height) of the region to keep, always inside the image.

    A zero width or height means "no crop" and returns the whole image. A box
    that sticks out is cut at the image edge instead of failing, so a saved
    crop still works if the file was replaced by a smaller one.
    """
    if width <= 0 or height <= 0:
        return 0, 0, image_width, image_height
    x = min(max(x, 0), image_width - 1)
    y = min(max(y, 0), image_height - 1)
    return x, y, min(width, image_width - x), min(height, image_height - y)
