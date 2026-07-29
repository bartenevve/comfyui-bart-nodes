from .nodes import LoadRandomImage
from .booru.nodes import LoadRandomBooruImage
from . import routes  # noqa: F401  registers the aiohttp routes on import
from .booru import routes as booru_routes  # noqa: F401  same, for /random_booru

NODE_CLASS_MAPPINGS = {
    "LoadRandomImage": LoadRandomImage,
    "LoadRandomBooruImage": LoadRandomBooruImage,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LoadRandomImage": "Load Random Image \U0001f3b2",
    "LoadRandomBooruImage": "Load Random Booru Image \U0001f3b2",
}

WEB_DIRECTORY = "./js"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
