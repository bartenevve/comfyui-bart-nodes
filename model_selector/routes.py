import asyncio
import functools
import logging

import folder_paths
from aiohttp import web
from server import PromptServer

from . import files, model_info
from .nodes import gguf_available

logger = logging.getLogger("comfyui-bart-nodes")

# how many headers are read at once: they are small, but a few thousand files are a few thousand opens
_SLOTS = asyncio.Semaphore(4)


async def _run(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))


def _roots():
    return files.collect_roots(folder_paths.get_folder_paths)


def _list():
    roots = _roots()
    out = []
    for item in files.scan(roots):
        info = model_info.cached_info(item["path"], item["key"], item["rel"])
        info["id"] = item["id"]
        info["rel"] = item["rel"]
        out.append(model_info.summary(info))
    return out


def _info(model_id):
    roots = _roots()
    path = files.resolve(model_id, roots)
    if not path:
        return None
    key, rel = files.split_id(model_id)
    info = model_info.cached_info(path, key, rel)
    info["id"] = model_id
    info["rel"] = rel
    info["can_load"] = not path.lower().endswith(".gguf") or gguf_available(info["kind"])
    # where it lies, without the machine's folder layout: the folder key and the path inside it
    info["location"] = f"{key}/{rel}"
    return info


@PromptServer.instance.routes.get("/model_selector/list")
async def list_models(request):
    """Every model file of the model folders with what is known about it, lightly: the cards of the picker screen."""
    try:
        async with _SLOTS:
            models = await _run(_list)
    except OSError as exc:
        return web.json_response({"error": f"cannot read the model folders: {exc.strerror}"}, status=500)
    return web.json_response({"models": models, "truncated": len(models) >= files.MAX_FILES})


@PromptServer.instance.routes.get("/model_selector/info")
async def model_info_route(request):
    info = await _run(_info, request.rel_url.query.get("id", ""))
    if info is None:
        return web.json_response({"error": "model not found"}, status=404)
    return web.json_response(info)
