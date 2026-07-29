import hashlib
import random

from . import runner
from .catalog import DEFAULT_GENERATOR, GENERATOR_LABELS

MAX_SEED = 0xFFFFFFFFFFFFFFFF


class LoadRandom52Prompt:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "generator": (GENERATOR_LABELS, {"default": DEFAULT_GENERATOR}),
                "randomize": ("BOOLEAN", {"default": True}),
                "seed": ("INT", {"default": 0, "min": 0, "max": MAX_SEED}),
            },
            "optional": {
                # Which of these the chosen generator actually reads depends on
                # the generator; the frontend hides the ones it ignores.
                "input_1": ("STRING", {"default": ""}),
                "input_2": ("STRING", {"default": ""}),
                "input_3": ("STRING", {"default": ""}),
                "choice_list": ("STRING", {"default": "", "multiline": True}),
                "last_prompt": ("STRING", {"default": "", "multiline": True}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "INT")
    RETURN_NAMES = ("prompt", "generator", "seed")
    FUNCTION = "generate"
    CATEGORY = "text"

    def generate(
        self,
        generator,
        randomize,
        seed,
        input_1="",
        input_2="",
        input_3="",
        choice_list="",
        last_prompt="",
    ):
        # A fresh seed is drawn rather than left implicit even in randomize
        # mode, so the run that produced a prompt worth keeping can be repeated
        # by turning randomize off - the seed the node reports is the one that
        # actually made this prompt.
        used_seed = random.randrange(MAX_SEED + 1) if randomize else int(seed)

        prompt = runner.generate(
            generator,
            values={
                "input_1": input_1,
                "input_2": input_2,
                "input_3": input_3,
                "choice_list": choice_list,
            },
            seed=used_seed,
        )

        return {
            "ui": {"prompt": [prompt], "seed": [used_seed]},
            "result": (prompt, generator, used_seed),
        }

    @classmethod
    def IS_CHANGED(
        cls,
        generator,
        randomize,
        seed,
        input_1="",
        input_2="",
        input_3="",
        choice_list="",
        last_prompt="",
    ):
        if randomize:
            return float("nan")
        # length-prefixed so ("a", "b") and ("a|b", "") cannot hash alike
        parts = (generator, str(seed), input_1, input_2, input_3, choice_list)
        payload = "|".join(f"{len(part)}:{part}" for part in parts)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
