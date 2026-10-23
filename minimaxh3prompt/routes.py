import asyncio
import concurrent.futures
import functools
import logging
import random

from aiohttp import web
from server import PromptServer

from . import runner
from .selection import MAX_SEED, InputError

logger = logging.getLogger("comfyui-bart-nodes")

# Generations are long (seconds to minutes of waiting on a model, up to retries x timeout), so they get
# a small pool of their own instead of the event loop's shared default executor: a few stuck requests
# must not starve every other route that runs blocking work there. More than MAX_IN_FLIGHT waiting
# at once is turned away rather than queued without limit.
_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="minimax_h3")
MAX_IN_FLIGHT = 4
MAX_BODY_BYTES = 256 * 1024
_in_flight = 0


async def _run(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_POOL, functools.partial(func, *args, **kwargs))


def _error(message, status):
    return web.json_response({"error": message}, status=status)


@PromptServer.instance.routes.post("/minimax_h3/generate")
async def generate(request):
    """The node's Generate button: same code path as running the node.

    Takes the widget values as a JSON object. The only outbound request it can
    cause is Ollama's `/api/chat` (under the given http/https address), and
    only the parsed prompt text goes back - never the raw response.
    """
    global _in_flight

    # A cross-site page can send a text/plain POST without any CORS preflight, and aiohttp would
    # parse it as JSON all the same. Insisting on application/json forces the preflight (which fails).
    if request.content_type != "application/json":
        return _error("send the widget values as application/json", 415)
    if request.content_length is not None and request.content_length > MAX_BODY_BYTES:
        return _error("request body is too large", 413)

    try:
        values = await request.json()
    except (ValueError, LookupError, RecursionError):  # not JSON, an unknown charset, absurdly deep nesting
        return _error("body must be a JSON object", 400)
    if not isinstance(values, dict):
        return _error("body must be a JSON object", 400)

    values = dict(values)
    if values.get("seed") in (None, ""):
        values["seed"] = random.randrange(MAX_SEED + 1)

    if _in_flight >= MAX_IN_FLIGHT:
        return _error("too many generations are already running, try again when one has finished", 429)
    _in_flight += 1
    try:
        result = await _run(runner.generate, values)
    except InputError as exc:
        return _error(str(exc), 400)
    except runner.H3Error as exc:
        return _error(str(exc), 502)
    except Exception:
        # whatever else went wrong stays in the server log; its text may echo what a remote peer sent
        logger.exception("comfyui-bart-nodes: /minimax_h3/generate failed")
        return _error("internal error, see the ComfyUI log", 500)
    finally:
        _in_flight -= 1

    return web.json_response(
        {
            "generated": result["text"],
            "report": result["report"],
            "variant": result["variant"],
            "clips": len(result["clips"]),
            "seed": values["seed"],
        }
    )
