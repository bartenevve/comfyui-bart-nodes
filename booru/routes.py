import asyncio
import functools

from aiohttp import web
from server import PromptServer

from . import pick as picker
from . import sources


async def _run(func, *args, **kwargs):
    """Run a blocking scrape/download off the event loop.

    A booru request can take seconds (throttle + remote latency); doing it
    inline would stall every other ComfyUI request, including other users'
    generation jobs, for that whole time.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))


@PromptServer.instance.routes.get("/random_booru/sources")
async def get_sources(request):
    return web.json_response({"sources": sources.SOURCE_NAMES, "default": sources.DEFAULT_SOURCE})


@PromptServer.instance.routes.get("/random_booru/count")
async def get_count(request):
    source = request.rel_url.query.get("source", sources.DEFAULT_SOURCE)
    tags = request.rel_url.query.get("tags", "")
    if source not in sources.SOURCE_NAMES:
        return web.json_response({"error": f"unknown source: {source}"}, status=400)
    try:
        total = await _run(sources.get_source(source).count, tags.strip())
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=502)
    return web.json_response({"total": total})


@PromptServer.instance.routes.get("/random_booru/pick")
async def pick_post(request):
    query = request.rel_url.query
    source = query.get("source", sources.DEFAULT_SOURCE)
    tags = query.get("tags", "")
    mode = query.get("mode", "random")
    if source not in sources.SOURCE_NAMES:
        return web.json_response({"error": f"unknown source: {source}"}, status=400)

    try:
        index = int(query.get("index", "0"))
    except ValueError:
        return web.json_response({"error": "index must be an integer"}, status=400)
    if index < 0:
        return web.json_response({"error": "index must be >= 0"}, status=400)

    try:
        # download=False: the frontend asks /view for the bytes right after
        # this, and that path caches - no reason to pay for the download twice
        # or to make the button wait on a multi-MB file
        result = await _run(
            picker.pick,
            source,
            tags,
            random_post=(mode == "random"),
            increment_on_queue=False,
            index=index,
            download=False,
        )
    except picker.NoPostsError as exc:
        return web.json_response({"error": str(exc)}, status=404)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=502)

    result.pop("path", None)
    result.pop("file_url", None)  # internal; /view resolves it server-side
    return web.json_response(result)


@PromptServer.instance.routes.get("/random_booru/view")
async def view_post(request):
    """Proxy a post's image through ComfyUI.

    Takes source + post_id rather than a URL, so the host that actually gets
    fetched is always one this node knows about - a raw `url` parameter here
    would turn ComfyUI into an open proxy.
    """
    source = request.rel_url.query.get("source", sources.DEFAULT_SOURCE)
    post_id = request.rel_url.query.get("post_id", "")
    if source not in sources.SOURCE_NAMES:
        return web.json_response({"error": f"unknown source: {source}"}, status=400)
    if not post_id.isdigit():
        return web.json_response({"error": "post_id must be numeric"}, status=400)

    try:
        path = await _run(picker.fetch_post_file, source, post_id)
    except picker.UnsupportedPostError as exc:
        return web.json_response({"error": str(exc)}, status=415)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=502)

    return web.FileResponse(path)
