VAE_REPOS = {
    "YuE2-Vae": "m-a-p/YuE2-Vae",
    "YuE2-Vae-legacy": "m-a-p/YuE2-Vae-legacy",
}


def vae_repo(choice):
    """HF repo id for a VAE dropdown value (from_pretrained wants the full id)."""
    try:
        return VAE_REPOS[choice]
    except KeyError:
        raise ValueError(f"unknown VAE {choice!r}, expected one of {sorted(VAE_REPOS)}") from None


def backend_for(device_type):
    """yue2's default backend captures CUDA graphs; everything else needs eager."""
    return "torch" if device_type == "cuda" else "torch-eager"


def generate_error(cot, abc):
    """Why this cot/abc pair would be rejected by yue2, or None if it is fine.

    yue2 raises deep inside the run for both cases; knowing up front lets the
    node fail when the graph is queued, not after the model has loaded.
    """
    if abc and abc.strip() and cot == "off":
        return "an external abc score needs cot=melody or cot=full (cot=off skips the score)"
    return None


def build_generate_kwargs(style, lyrics, cot, seed, abc=""):
    """Assembles the pipeline() call's kwargs - `abc` is only passed at all
    when it has content, since yue2's fresh-generation path is triggered by
    its absence, and it rejects a blank string.
    """
    kwargs = {"style": style, "lyrics": lyrics, "cot": cot, "seed": seed}
    if abc and abc.strip():
        kwargs["abc"] = abc
    return kwargs
