import asyncio
import errno
import functools
import os

import folder_paths
from aiohttp import web
from server import PromptServer

from .selection import PathError, clean_subfolder, is_image_name, join_inside, list_directory, thumb_cache_name, thumb_size
from .thumbs import make_thumb


async def _run(func, *args, **kwargs):
    """Run blocking disk/PIL work off the event loop (a big folder scan or a
    thumbnail decode must not stall every other ComfyUI request)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))


def _thumb_dir():
    path = os.path.join(folder_paths.get_temp_directory(), "image_picker_thumbs")
    os.makedirs(path, exist_ok=True)
    return path


@PromptServer.instance.routes.get("/image_picker/list")
async def list_folder(request):
    try:
        subfolder = clean_subfolder(request.rel_url.query.get("subfolder", ""))
        result = await _run(list_directory, folder_paths.get_input_directory(), subfolder)
    except PathError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except (FileNotFoundError, NotADirectoryError):
        return web.json_response({"error": "folder not found"}, status=404)
    except OSError as exc:
        # a name the file system itself refuses (too long, bad characters, a symlink loop) is the
        # caller's mistake, not a server fault
        refused = exc.errno in (errno.ENAMETOOLONG, errno.ELOOP, errno.EINVAL)
        return web.json_response({"error": f"cannot read folder: {exc.strerror}"}, status=400 if refused else 500)
    return web.json_response(result)


@PromptServer.instance.routes.get("/image_picker/thumb")
async def thumbnail(request):
    query = request.rel_url.query
    try:
        subfolder = clean_subfolder(query.get("subfolder", ""))
        filename = query.get("filename", "")
        base = folder_paths.get_input_directory()
        source = join_inside(base, subfolder, filename)
    except PathError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    if not is_image_name(filename):
        return web.json_response({"error": "not an image file"}, status=400)
    try:
        stat = os.stat(source)
    except OSError:
        return web.json_response({"error": "file not found"}, status=404)

    size = thumb_size(query.get("size"))
    relative = f"{subfolder}/{filename}" if subfolder else filename
    target = os.path.join(_thumb_dir(), thumb_cache_name(relative, stat.st_mtime_ns, stat.st_size, size))
    if not os.path.isfile(target):
        try:
            await _run(make_thumb, source, target, size)
        except Exception as exc:  # corrupt / unsupported file: the gallery shows a placeholder
            return web.json_response({"error": f"cannot read image: {type(exc).__name__}"}, status=415)
    return web.FileResponse(target, headers={"Cache-Control": "private, max-age=3600"})
