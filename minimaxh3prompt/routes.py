import asyncio
import functools
import random

from aiohttp import web
from server import PromptServer

from . import runner
from .selection import MAX_SEED, InputError


async def _run(func, *args, **kwargs):
    """Run the blocking Ollama round trips off the event loop.

    One generation is several seconds to minutes of waiting on the model;
    inline it would stall every other ComfyUI request for that whole time.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))


@PromptServer.instance.routes.post("/minimax_h3/generate")
async def generate(request):
    """The node's Generate button: same code path as running the node.

    Takes the widget values as a JSON object. The only outbound request it can
    cause is Ollama's `/api/chat` on the URL given (http/https only), and only
    the parsed prompt text goes back - never the raw response.
    """
    try:
        values = await request.json()
    except ValueError:
        return web.json_response({"error": "body must be a JSON object"}, status=400)
    if not isinstance(values, dict):
        return web.json_response({"error": "body must be a JSON object"}, status=400)

    values = dict(values)
    if values.get("seed") in (None, ""):
        values["seed"] = random.randrange(MAX_SEED + 1)

    try:
        result = await _run(runner.generate, values)
    except InputError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except runner.H3Error as exc:
        return web.json_response({"error": str(exc)}, status=502)
    except Exception as exc:
        return web.json_response({"error": f"{type(exc).__name__}: {exc}"}, status=500)

    return web.json_response(
        {
            "generated": result["text"],
            "report": result["report"],
            "variant": result["variant"],
            "clips": len(result["clips"]),
            "seed": values["seed"],
        }
    )
