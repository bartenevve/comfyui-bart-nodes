import asyncio
import functools
import logging
import os

import folder_paths
from aiohttp import web
from server import PromptServer

from ..imagepicker.selection import thumb_cache_name, thumb_size
from ..imagepicker.thumbs import ImageTooLarge, make_thumb
from . import metadata

logger = logging.getLogger("comfyui-bart-nodes")

MAX_LORAS_LISTED = 5000
MAX_BODY_BYTES = 64 * 1024

# at most this many preview images are decoded at once, however many cards the screen asks for
_THUMB_SLOTS = asyncio.Semaphore(3)


async def _run(func, *args, **kwargs):
    """Blocking disk / PIL work off the event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))


def _names():
    """The LoRA names ComfyUI lists, with forward slashes; the only names the routes will touch."""
    return [name.replace("\\", "/") for name in folder_paths.get_filename_list("loras")]


def _resolve(name, allowed=None):
    """(canonical name, absolute path) of a LoRA by the name the frontend sends, or None."""
    if not isinstance(name, str) or "\x00" in name or name not in (allowed if allowed is not None else set(_names())):
        return None
    for candidate in (name, name.replace("/", os.sep)):
        path = folder_paths.get_full_path("loras", candidate)
        if path:
            return name, path
    return None


def _notes_path():
    return os.path.join(folder_paths.get_user_directory(), "bart_lora_notes.json")


def _thumb_dir():
    path = os.path.join(folder_paths.get_temp_directory(), "lora_selector_thumbs")
    os.makedirs(path, exist_ok=True)
    return path


def _list():
    notes = metadata.load_notes(_notes_path())
    names = _names()
    allowed = set(names)
    out = []
    for name in names[:MAX_LORAS_LISTED]:
        found = _resolve(name, allowed)
        if found:
            out.append(metadata.summary(metadata.lora_info(found[1], found[0], notes)))
    return out


def _info(name):
    found = _resolve(name)
    if not found:
        return None
    return metadata.lora_info(found[1], found[0], metadata.load_notes(_notes_path()))


@PromptServer.instance.routes.get("/lora_selector/list")
async def list_loras(request):
    """Every LoRA with what is known about it, lightly: the cards of the picker screen."""
    try:
        loras = await _run(_list)
    except OSError as exc:
        return web.json_response({"error": f"cannot read the loras folder: {exc.strerror}"}, status=500)
    return web.json_response({"loras": loras, "truncated": len(_names()) > MAX_LORAS_LISTED})


@PromptServer.instance.routes.get("/lora_selector/info")
async def lora_info(request):
    name = request.rel_url.query.get("name", "")
    info = await _run(_info, name)
    if info is None:
        return web.json_response({"error": "LoRA not found"}, status=404)
    return web.json_response(info)


@PromptServer.instance.routes.get("/lora_selector/preview")
async def preview(request):
    query = request.rel_url.query
    found = _resolve(query.get("name", ""))
    if not found:
        return web.json_response({"error": "LoRA not found"}, status=404)
    source = metadata.find_preview(found[1])
    if not source:
        return web.json_response({"error": "no preview image"}, status=404)
    try:
        stat = os.stat(source)
    except OSError:
        return web.json_response({"error": "no preview image"}, status=404)
    size = thumb_size(query.get("size"))
    target = os.path.join(_thumb_dir(), thumb_cache_name("lora:" + found[0], stat.st_mtime_ns, stat.st_size, size))
    if not os.path.isfile(target):
        try:
            async with _THUMB_SLOTS:
                await _run(make_thumb, source, target, size)
        except ImageTooLarge as exc:
            return web.json_response({"error": str(exc)}, status=413)
        except Exception as exc:  # a corrupt preview: the card shows a placeholder
            return web.json_response({"error": f"cannot read image: {type(exc).__name__}"}, status=415)
    return web.FileResponse(target, headers={"Cache-Control": "private, no-cache"})


@PromptServer.instance.routes.post("/lora_selector/notes")
async def save_notes(request):
    """The user's own triggers / strength / text for one LoRA (body: {name, triggers, strength, text})."""
    # a plain cross-site form post cannot send application/json, and a JSON one needs a CORS preflight
    if request.content_type != "application/json":
        return web.json_response({"error": "send application/json"}, status=415)
    if request.content_length is not None and request.content_length > MAX_BODY_BYTES:
        return web.json_response({"error": "request body is too large"}, status=413)
    try:
        body = await request.json()
    except (ValueError, LookupError, RecursionError):
        return web.json_response({"error": "body must be a JSON object"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "body must be a JSON object"}, status=400)
    found = _resolve(body.get("name"))
    if not found:
        return web.json_response({"error": "LoRA not found"}, status=404)
    try:
        note = await _run(metadata.save_note, _notes_path(), found[0], body)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except OSError as exc:
        logger.exception("comfyui-bart-nodes: saving the LoRA notes failed")
        return web.json_response({"error": f"cannot save the notes: {exc.strerror}"}, status=500)
    return web.json_response({"saved": note})
