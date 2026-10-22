import asyncio
import os
import random

import folder_paths
from aiohttp import web
from server import PromptServer

from .selection import list_images


def _has_nul(*values):
    """A NUL byte makes os.path raise ValueError, which would surface as a bare 500."""
    return any("\x00" in value for value in values)


@PromptServer.instance.routes.get("/random_image/input_dir")
async def get_input_dir(request):
    subfolder = request.rel_url.query.get("subfolder", "")
    if _has_nul(subfolder):
        return web.json_response({"error": "invalid 'subfolder' parameter"}, status=400)
    base = folder_paths.get_input_directory()
    full = os.path.join(base, subfolder) if subfolder else base
    return web.json_response({"directory": os.path.realpath(full)})


@PromptServer.instance.routes.get("/random_image/pick")
async def pick_random_image(request):
    directory = request.rel_url.query.get("dir", "")
    if not directory:
        return web.json_response({"error": "missing 'dir' parameter"}, status=400)
    if _has_nul(directory):
        return web.json_response({"error": "invalid 'dir' parameter"}, status=400)

    real_dir = os.path.realpath(directory)
    if not os.path.isdir(real_dir):
        return web.json_response({"error": f"not a directory: {directory}"}, status=400)

    # os.walk over a large/slow directory can take a while - run it off the
    # event loop so it doesn't stall every other request (including other
    # users' generation jobs) for the duration
    files = await asyncio.get_event_loop().run_in_executor(None, list_images, real_dir)
    if not files:
        return web.json_response({"error": "no images found"}, status=404)

    chosen = random.choice(files)
    return web.json_response({"filename": chosen})


@PromptServer.instance.routes.get("/random_image/list")
async def list_images_route(request):
    directory = request.rel_url.query.get("dir", "")
    if not directory:
        return web.json_response({"error": "missing 'dir' parameter"}, status=400)
    if _has_nul(directory):
        return web.json_response({"error": "invalid 'dir' parameter"}, status=400)

    real_dir = os.path.realpath(directory)
    if not os.path.isdir(real_dir):
        return web.json_response({"error": f"not a directory: {directory}"}, status=400)

    files = await asyncio.get_event_loop().run_in_executor(None, list_images, real_dir)
    return web.json_response({"files": files})


@PromptServer.instance.routes.get("/random_image/view")
async def view_image(request):
    directory = request.rel_url.query.get("dir", "")
    filename = request.rel_url.query.get("filename", "")
    if not directory or not filename:
        return web.json_response({"error": "missing 'dir' or 'filename' parameter"}, status=400)
    if _has_nul(directory, filename):
        return web.json_response({"error": "invalid 'dir' or 'filename' parameter"}, status=400)

    real_dir = os.path.realpath(directory)
    full_path = os.path.realpath(os.path.join(real_dir, filename))

    # reject any filename that resolves outside the requested directory
    try:
        inside = os.path.commonpath([real_dir, full_path]) == real_dir
    except ValueError:  # Windows: the two paths are on different drives
        inside = False
    if not inside:
        return web.json_response({"error": "invalid filename"}, status=400)

    if not os.path.isfile(full_path):
        return web.json_response({"error": "file not found"}, status=404)

    return web.FileResponse(full_path)
