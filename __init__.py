from .nodes import LoadRandomImage
from .booru.nodes import LoadRandomBooruImage
from .prompts52.nodes import LoadRandom52Prompt
from . import routes  # noqa: F401  registers the aiohttp routes on import
from .booru import routes as booru_routes  # noqa: F401  same, for /random_booru
from .prompts52 import routes as prompts52_routes  # noqa: F401  same, for /random_prompts52

NODE_CLASS_MAPPINGS = {
    "LoadRandomImage": LoadRandomImage,
    "LoadRandomBooruImage": LoadRandomBooruImage,
    "LoadRandom52Prompt": LoadRandom52Prompt,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LoadRandomImage": "Load Random Image \U0001f3b2",
    "LoadRandomBooruImage": "Load Random Booru Image \U0001f3b2",
    "LoadRandom52Prompt": "Load Random Prompt (52prompts) \U0001f3b2",
}

WEB_DIRECTORY = "./js"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
