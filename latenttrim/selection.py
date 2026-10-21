# WAN's VAE compresses time 4x with a causal first frame: T latent frames decode
# to 4*T - 3 pixel frames (ComfyUI's own `upscale_ratio` for WAN is `a * 4 - 3`),
# so dropping L latent frames from the front drops exactly 4*L pixel frames - the
# "+1" keyframe cancels between the old and the new total.
TEMPORAL_RATIO = 4


def pixel_frames(latent_frames):
    """Pixel frames a WAN latent of `latent_frames` frames decodes to: (T - 1) * 4 + 1."""
    return max(0, latent_frames * TEMPORAL_RATIO - (TEMPORAL_RATIO - 1))


def latent_frames_to_trim(pixel_count):
    """Whole latent frames closest to `pixel_count` pixel frames (halves round up)."""
    count = max(0, int(pixel_count))
    return (count + TEMPORAL_RATIO // 2) // TEMPORAL_RATIO


def plan_trim(pixel_count, latent_frames):
    """(latent frames to cut, pixel frames that removes, pixel frames left).

    Raises ValueError when nothing would remain: the request is asking for the
    whole clip (or more), which is a mistake worth stopping on rather than
    passing an empty latent to the VAE.
    """
    cut = latent_frames_to_trim(pixel_count)
    if cut and cut >= latent_frames:
        raise ValueError(
            f"trim_start_frames ({int(pixel_count)} px frames = {cut} latent frames) is not smaller than the "
            f"{latent_frames} latent frames available ({pixel_frames(latent_frames)} px frames); nothing would remain."
        )
    return cut, cut * TEMPORAL_RATIO, pixel_frames(latent_frames - cut)
