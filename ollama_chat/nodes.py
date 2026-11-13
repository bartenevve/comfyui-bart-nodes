import base64
import hashlib
import io

from . import client


def encode_images(images, max_side=client.DEFAULT_IMAGE_MAX_SIDE, quality=92):
    """ComfyUI IMAGE ([batch, height, width, channels], floats 0..1) -> (base64 JPEGs, "WxH" labels).

    Each frame of the batch is one image for the model. A frame whose long side is over `max_side`
    is scaled down first (vision models shrink big photos themselves; sending them whole only makes
    the request huge).
    """
    import numpy as np
    from PIL import Image

    array = images.detach().cpu().numpy() if hasattr(images, "detach") else np.asarray(images)
    if array.ndim == 3:  # a single frame
        array = array[None]
    if array.ndim != 4 or array.shape[0] == 0:
        raise ValueError(f"expected an IMAGE batch [batch, height, width, channels], got shape {tuple(array.shape)}")
    encoded, labels = [], []
    for frame in array:
        pixels = (np.clip(np.nan_to_num(frame), 0.0, 1.0) * 255.0 + 0.5).astype("uint8")
        if pixels.shape[-1] == 1:
            pixels = np.repeat(pixels, 3, axis=-1)
        image = Image.fromarray(pixels[..., :3], "RGB")
        longest = max(image.size)
        if longest > max_side:
            scale = max_side / longest
            image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality)
        encoded.append(base64.b64encode(buffer.getvalue()).decode("ascii"))
        labels.append(f"{image.width}x{image.height}")
    return encoded, labels


class BartEasyOllama:
    """The plainest possible Ollama call: address, model, prompt, optional images, a JSON of options."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "address": ("STRING", {"default": client.DEFAULT_ADDRESS}),
                "model": ("STRING", {"default": ""}),
                "prompt": ("STRING", {"default": "", "multiline": True}),
            },
            "optional": {
                "images": ("IMAGE",),
                "settings": ("STRING", {"default": client.DEFAULT_SETTINGS, "multiline": True}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("text", "debug")
    FUNCTION = "chat"
    CATEGORY = "Bart's nodes/Text"

    @classmethod
    def IS_CHANGED(cls, settings=client.DEFAULT_SETTINGS, **_):
        # A random seed (none, or negative) means every queue should be a new answer; a fixed one gives the
        # same answer for the same inputs, which ComfyUI may then reuse. (A linked, unknown `settings` is
        # treated as random: better one request too many than a stale answer.)
        try:
            options, _top, _node = client.parse_settings(settings)
        except client.SettingsError:
            return float("nan")
        if client.is_random_seed(options):
            return float("nan")
        return hashlib.sha256(settings.encode("utf-8")).hexdigest()

    @classmethod
    def VALIDATE_INPUTS(cls, address=None, model=None, prompt=None, settings=None):
        # None = wired from another node, unknowable until execution
        try:
            if address is not None:
                client.normalize_address(address)
            if model is not None and not model.strip():
                return "model is empty"
            if prompt is not None and not prompt.strip():
                return "prompt is empty"
            if settings is not None:
                _, _, node = client.parse_settings(settings)
                client.node_number(node, "timeout", client.DEFAULT_TIMEOUT, 1)
                client.node_number(node, "image_max_side", client.DEFAULT_IMAGE_MAX_SIDE, 16)
        except client.SettingsError as exc:
            return str(exc)
        return True

    def chat(self, address, model, prompt, images=None, settings=client.DEFAULT_SETTINGS):
        prelude = []
        encoded = []
        if images is not None:
            try:
                _, _, node = client.parse_settings(settings)
                max_side = client.node_number(node, "image_max_side", client.DEFAULT_IMAGE_MAX_SIDE, 16)
                encoded, labels = encode_images(images, int(max_side))
                prelude.append("images sent: " + ", ".join(labels))
            except (client.SettingsError, ValueError, TypeError, AttributeError) as exc:
                return ("", f"ERROR: the images could not be prepared: {exc}")
        text, debug = client.run(address, model, prompt, encoded, settings)
        return (text, "\n".join(prelude + [debug]) if prelude else debug)
