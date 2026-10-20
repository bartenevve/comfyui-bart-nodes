import logging

logger = logging.getLogger(__name__)

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

# Each sub-package is isolated: one failing import (a missing optional
# dependency, a broken environment) disables just that node instead of
# taking the whole pack down - see CONTRIBUTING.md.

try:
    from .nodes import LoadRandomImage
    from . import routes  # noqa: F401  registers the aiohttp routes on import

    NODE_CLASS_MAPPINGS["LoadRandomImage"] = LoadRandomImage
    NODE_DISPLAY_NAME_MAPPINGS["LoadRandomImage"] = "Bart's Load Random Image \U0001f3b2"
except Exception:
    logger.exception("comfyui-bart-nodes: LoadRandomImage failed to load, skipping it")

try:
    from .booru.nodes import LoadRandomBooruImage
    from .booru import routes as booru_routes  # noqa: F401  registers /random_booru

    NODE_CLASS_MAPPINGS["LoadRandomBooruImage"] = LoadRandomBooruImage
    NODE_DISPLAY_NAME_MAPPINGS["LoadRandomBooruImage"] = "Bart's Load Random Booru Image \U0001f3b2"
except Exception:
    logger.exception("comfyui-bart-nodes: LoadRandomBooruImage failed to load, skipping it")

try:
    from .prompts52.nodes import LoadRandom52Prompt
    from .prompts52 import routes as prompts52_routes  # noqa: F401  registers /random_prompts52

    NODE_CLASS_MAPPINGS["LoadRandom52Prompt"] = LoadRandom52Prompt
    NODE_DISPLAY_NAME_MAPPINGS["LoadRandom52Prompt"] = "Bart's Load Random Prompt (52prompts) \U0001f3b2"
except Exception:
    logger.exception("comfyui-bart-nodes: LoadRandom52Prompt failed to load, skipping it")

try:
    from .yue2.nodes import YuE2Generate, YuE2ModelLoader, YuE2Plan

    NODE_CLASS_MAPPINGS["YuE2ModelLoader"] = YuE2ModelLoader
    NODE_CLASS_MAPPINGS["YuE2Plan"] = YuE2Plan
    NODE_CLASS_MAPPINGS["YuE2Generate"] = YuE2Generate
    NODE_DISPLAY_NAME_MAPPINGS["YuE2ModelLoader"] = "Bart's YuE2 Model Loader \U0001f3b5"
    NODE_DISPLAY_NAME_MAPPINGS["YuE2Plan"] = "Bart's YuE2 Plan Score \U0001f3b5"
    NODE_DISPLAY_NAME_MAPPINGS["YuE2Generate"] = "Bart's YuE2 Generate Song \U0001f3b5"
except Exception:
    logger.exception("comfyui-bart-nodes: YuE2 nodes failed to load, skipping them")

try:
    from .anatomy.nodes import AnatomyDefectFilter

    NODE_CLASS_MAPPINGS["AnatomyDefectFilter"] = AnatomyDefectFilter
    NODE_DISPLAY_NAME_MAPPINGS["AnatomyDefectFilter"] = "Bart's Anatomy Defect Filter (Ollama) \U0001f50d"
except Exception:
    logger.exception("comfyui-bart-nodes: AnatomyDefectFilter failed to load, skipping it")

try:
    from .minimaxh3prompt.nodes import MiniMaxH3Prompt
    from .minimaxh3prompt import routes as minimaxh3prompt_routes  # noqa: F401  registers /minimax_h3

    NODE_CLASS_MAPPINGS["MiniMaxH3Prompt"] = MiniMaxH3Prompt
    NODE_DISPLAY_NAME_MAPPINGS["MiniMaxH3Prompt"] = "Bart's MiniMax H3 Prompt (Ollama) \U0001f3ac"
except Exception:
    logger.exception("comfyui-bart-nodes: MiniMaxH3Prompt failed to load, skipping it")

WEB_DIRECTORY = "./js"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
