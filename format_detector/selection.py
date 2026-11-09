"""The arithmetic of Format Detector: which format fits an image, the size for a number of megapixels, the box to
cut out of the image. Pure Python, no torch."""
import math

# (width, height) of every format of the list. The order is the order of the dropdown and the tie-break of "auto".
FORMATS = {
    "16:9": (16, 9),
    "9:16": (9, 16),
    "4:3": (4, 3),
    "3:4": (3, 4),
    "1:1": (1, 1),
    "21:9": (21, 9),
    "9:21": (9, 21),
    "3:2": (3, 2),
    "2:3": (2, 3),
    "5:4": (5, 4),
    "4:5": (4, 5),
    "2:1": (2, 1),
    "1:2": (1, 2),
}
AUTO = "auto"
CUSTOM = "custom"
CHOICES = [AUTO, *FORMATS, CUSTOM]
DEFAULT_FORMAT = "16:9"  # H3's own default (1344 x 768): what "auto" falls back to without an image

MULTIPLE = 32  # MiniMax H3 works on a canvas whose sides are multiples of 32
H3_MAX_PIXELS = 768 * 1344  # and caps the area of that canvas
MIN_MEGAPIXELS = 0.05
MAX_MEGAPIXELS = 64.0


class FormatError(ValueError):
    """A setting that cannot be used."""


def parse_ratio(text):
    """(width, height) from a custom ratio: `16:10`, `16/10`, `16x10`, or a decimal such as `1.85`."""
    raw = (text or "").strip().lower().replace(" ", "")
    if not raw:
        raise FormatError("custom_ratio is empty: type a ratio such as 16:10 or 1.85")
    for sep in (":", "/", "x"):
        if sep in raw:
            left, _, right = raw.partition(sep)
            break
    else:
        left, right = raw, "1"
    try:
        first, second = float(left), float(right)
    except ValueError:
        raise FormatError(f"custom_ratio {text!r} is not a ratio such as 16:10 or 1.85") from None
    if not (math.isfinite(first) and math.isfinite(second)) or first <= 0 or second <= 0:
        raise FormatError(f"custom_ratio {text!r} must be made of positive numbers")
    ratio = first / second
    if not 0.05 <= ratio <= 20:
        raise FormatError(f"custom_ratio {text!r} is too extreme (use a ratio between 1:20 and 20:1)")
    return first, second


def closest_format(width, height):
    """The format of the list whose proportions are nearest to width x height (nearest in the logarithm of the
    ratio, so 2:1 and 1:2 are equally far from 1:1). Ties go to the earlier one in the list."""
    if width <= 0 or height <= 0:
        raise FormatError("the image has no size")
    target = math.log(width / height)
    best, best_distance = None, None
    for name, (w, h) in FORMATS.items():
        distance = abs(math.log(w / h) - target)
        if best_distance is None or distance < best_distance - 1e-12:
            best, best_distance = name, distance
    return best


def snap(value, multiple=MULTIPLE):
    """`value` rounded to the nearest multiple (never below one multiple)."""
    return max(multiple, int(round(value / multiple)) * multiple)


AREA_WEIGHT = 0.35  # how much a missed area counts against a missed proportion when choosing the sides
AREA_WINDOW = (0.7, 1.4)  # the sides may differ this much in area from what was asked: a 32-pixel grid is coarse


def size_for(ratio_w, ratio_h, megapixels, limit_h3=False):
    """(width, height, note): sides, multiples of 32, for `megapixels` at the ratio.

    Of the pairs of multiples of 32 around the asked area, the one that keeps the proportions best (and the area
    near) is taken, so 16:9 at 1 MP gives H3's own 1344 x 768 rather than a 1344 x 736 that has drifted to 1.83:1.
    With `limit_h3` the area stays within H3's 768 x 1344 canvas; `note` says when that changed anything.
    """
    try:
        megapixels = float(megapixels)
    except (TypeError, ValueError):
        raise FormatError(f"megapixels must be a number, got {megapixels!r}") from None
    if not math.isfinite(megapixels) or not MIN_MEGAPIXELS <= megapixels <= MAX_MEGAPIXELS:
        raise FormatError(f"megapixels must be between {MIN_MEGAPIXELS} and {MAX_MEGAPIXELS:g}, got {megapixels:g}")
    note = ""
    area = megapixels * 1_000_000
    cap = H3_MAX_PIXELS if limit_h3 else None
    if cap is not None and area > cap:
        note = f"limited to MiniMax H3's canvas ({cap / 1e6:.2f} MP instead of {megapixels:g} MP)"
        area = cap
    ratio = ratio_w / ratio_h
    low, high = AREA_WINDOW[0] * area, AREA_WINDOW[1] * area
    if cap is not None:
        high = min(high, cap)
    best, best_cost = None, None
    top = int(math.sqrt(high / ratio) // MULTIPLE) + 2
    for steps in range(1, top + 1):
        height = steps * MULTIPLE
        for width in {max(MULTIPLE, int(ratio * height // MULTIPLE) * MULTIPLE), snap(ratio * height) + 0,
                      (int(ratio * height // MULTIPLE) + 1) * MULTIPLE}:
            pixels = width * height
            if not low <= pixels <= high:
                continue
            cost = abs(math.log(width / height / ratio)) + AREA_WEIGHT * abs(math.log(pixels / area))
            if best_cost is None or cost < best_cost - 1e-12 or (abs(cost - best_cost) <= 1e-12 and (width, height) < best):
                best, best_cost = (width, height), cost
    if best is None:  # a tiny area (the grid has no pair near it) or an extreme ratio: the plain rounding
        width, height = snap(ratio * math.sqrt(area / ratio)), snap(math.sqrt(area / ratio))
        while cap is not None and width * height > cap and max(width, height) > MULTIPLE:
            if width >= height:
                width -= MULTIPLE
            else:
                height -= MULTIPLE
        best = (width, height)
    return best[0], best[1], note


def crop_box(source_width, source_height, target_width, target_height):
    """(x, y, width, height) of the centred part of the source that has the target's proportions.

    It is the largest such part: the frame is filled without bars and without stretching, and only the surplus on
    the sides (or top and bottom) is cut away, equally on both.
    """
    if min(source_width, source_height, target_width, target_height) <= 0:
        raise FormatError("sizes must be positive")
    target = target_width / target_height
    if source_width / source_height > target:  # wider than the target: cut the sides
        width = min(source_width, max(1, round(source_height * target)))
        height = source_height
    else:  # taller: cut the top and bottom
        width = source_width
        height = min(source_height, max(1, round(source_width / target)))
    return (source_width - width) // 2, (source_height - height) // 2, width, height


def cropped_share(source_width, source_height, box):
    """The part of the source's area that the box throws away, 0..1."""
    return 1 - (box[2] * box[3]) / (source_width * source_height)


def describe(chosen, how, source, size, box, note):
    """The `info` text: the format and why, the size, and (with an image) how much of it was cropped."""
    parts = [f"{chosen}" + (f" ({how})" if how else ""), f"{size[0]}x{size[1]} = {size[0] * size[1] / 1e6:.2f} MP"]
    if source and box:
        parts.append(f"from {source[0]}x{source[1]}, {cropped_share(source[0], source[1], box) * 100:.0f}% cropped")
    text = " | ".join(parts)
    return f"{text}\n{note}" if note else text
