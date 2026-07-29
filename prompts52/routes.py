import asyncio
import functools
import random

from aiohttp import web
from server import PromptServer

from . import catalog
from . import runner
from .nodes import MAX_SEED


async def _run(func, *args, **kwargs):
    """Run a blocking fetch off the event loop.

    A cold generator costs two HTTP round trips; doing them inline would stall
    every other ComfyUI request, including other users' generation jobs, for
    that whole time.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))


@PromptServer.instance.routes.get("/random_prompts52/generators")
async def get_generators(request):
    return web.json_response(
        {
            "generators": [catalog.describe(item) for item in catalog.GENERATORS],
            "default": catalog.DEFAULT_GENERATOR,
        }
    )


@PromptServer.instance.routes.get("/random_prompts52/pick")
async def pick_prompt(request):
    query = request.rel_url.query
    label = query.get("generator", catalog.DEFAULT_GENERATOR)
    try:
        catalog.get_generator(label)
    except KeyError as exc:
        return web.json_response({"error": str(exc)}, status=400)

    raw_seed = query.get("seed", "")
    if raw_seed == "":
        seed = random.randrange(MAX_SEED + 1)
    else:
        try:
            seed = int(raw_seed)
        except ValueError:
            return web.json_response({"error": "seed must be an integer"}, status=400)
        if not 0 <= seed <= MAX_SEED:
            return web.json_response({"error": f"seed must be 0..{MAX_SEED}"}, status=400)

    values = {name: query.get(name, "") for name in catalog.WIDGET_NAMES}

    try:
        prompt = await _run(runner.generate, label, values=values, seed=seed)
    except runner.GeneratorError as exc:
        return web.json_response({"error": str(exc)}, status=422)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=502)

    return web.json_response({"prompt": prompt, "generator": label, "seed": seed})
