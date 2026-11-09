from .selection import (
    AUTO,
    CHOICES,
    CUSTOM,
    DEFAULT_FORMAT,
    FORMATS,
    H3_MAX_PIXELS,
    FormatError,
    closest_format,
    crop_box,
    describe,
    parse_ratio,
    size_for,
)

# 1.03 MP is MiniMax H3's own canvas (768 x 1344 = 1,032,192 pixels): 16:9 comes out as 1344 x 768
DEFAULT_MEGAPIXELS = 1.03


def fit_image(images, width, height):
    """ComfyUI IMAGE [batch, h, w, channels] -> the centred part with the target's proportions, scaled to width x height.

    Cropped first (the largest centred box with the target proportions), then scaled with an anti-aliased bicubic,
    so there are no bars and no stretching. Returns (image, crop box, source size).
    """
    import torch
    import torch.nn.functional as functional

    if images.ndim == 3:
        images = images[None]
    if images.ndim != 4 or images.shape[0] == 0:
        raise FormatError(f"expected an IMAGE batch [batch, height, width, channels], got shape {tuple(images.shape)}")
    source_height, source_width = int(images.shape[1]), int(images.shape[2])
    x, y, box_width, box_height = crop_box(source_width, source_height, width, height)
    part = images[:, y:y + box_height, x:x + box_width, :]
    if (box_width, box_height) != (width, height):
        samples = part.movedim(-1, 1).to(torch.float32)
        samples = functional.interpolate(samples, size=(height, width), mode="bicubic", antialias=True, align_corners=False)
        part = samples.clamp_(0.0, 1.0).movedim(1, -1).contiguous()
    return part, (x, y, box_width, box_height), (source_width, source_height)


class FormatDetector:
    """A video format, the sides for a number of megapixels, and the image cropped and scaled to fill it."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "format": (CHOICES, {
                    "default": AUTO,
                    "tooltip": "A format from the list; auto = the one nearest to the proportions of the image "
                               "(16:9 when there is no image); custom = the ratio typed below.",
                }),
                "megapixels": ("FLOAT", {
                    "default": DEFAULT_MEGAPIXELS, "min": 0.05, "max": 64.0, "step": 0.01,
                    "tooltip": "The size of the frame in megapixels. 1.03 is MiniMax H3's own canvas (1344 x 768).",
                }),
                "limit_h3": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Keep the frame within MiniMax H3's canvas of 768 x 1344 pixels (1.03 MP): a larger "
                               "megapixel value is cut down to it, and the info output says so.",
                }),
            },
            "optional": {
                "image": ("IMAGE", {"tooltip": "Optional. Cut to the format around its centre and scaled to fill it."}),
                "custom_ratio": ("STRING", {
                    "default": "16:10",
                    "tooltip": "Used only when format is custom: 16:10, 16/10 or a decimal such as 1.85 (width / height).",
                }),
            },
        }

    RETURN_TYPES = ("INT", "INT", "IMAGE", "STRING", "FLOAT", "STRING")
    RETURN_NAMES = ("width", "height", "image", "aspect", "ratio", "info")
    OUTPUT_TOOLTIPS = (
        "The width of the frame, a multiple of 32.",
        "The height of the frame, a multiple of 32.",
        "The input image cut around its centre to the format and scaled to width x height (nothing when no image was given).",
        "The format that was used, such as 16:9 (for a custom ratio the ratio as typed).",
        "width / height of that format.",
        "What was decided: the format, the size, how much of the image was cropped, and a note when H3's limit changed the size.",
    )
    FUNCTION = "detect"
    CATEGORY = "Bart's nodes/Image"

    @classmethod
    def VALIDATE_INPUTS(cls, format=None, custom_ratio=None, megapixels=None):
        # None = wired from another node, unknowable until execution
        try:
            if format == CUSTOM and custom_ratio is not None:
                parse_ratio(custom_ratio)
            if megapixels is not None:
                size_for(1, 1, megapixels)
        except FormatError as exc:
            return str(exc)
        return True

    def detect(self, format, megapixels, limit_h3=True, image=None, custom_ratio="16:10"):
        try:
            how, source = "", None
            if image is not None:
                shape = tuple(image.shape)
                source = (int(shape[-2]), int(shape[-3])) if len(shape) >= 3 else None
            if format == CUSTOM:
                ratio_w, ratio_h = parse_ratio(custom_ratio)
                chosen, how = f"{ratio_w:g}:{ratio_h:g}", "custom"
            else:
                if format == AUTO:
                    if source:
                        chosen = closest_format(*source)
                        how = f"auto: the image is {source[0] / source[1]:.2f}:1"
                    else:
                        chosen, how = DEFAULT_FORMAT, "auto: no image, so the default"
                else:
                    chosen = format
                ratio_w, ratio_h = FORMATS[chosen]
            width, height, note = size_for(ratio_w, ratio_h, megapixels, limit_h3)
            fitted, box = None, None
            if image is not None:
                fitted, box, source = fit_image(image, width, height)
            info = describe(chosen, how, source if image is not None else None, (width, height), box, note)
        except FormatError as exc:
            raise RuntimeError(f"Format Detector: {exc}") from None
        return (width, height, fitted, chosen, float(ratio_w / ratio_h), info)


__all__ = ["FormatDetector", "fit_image", "DEFAULT_MEGAPIXELS", "H3_MAX_PIXELS"]
