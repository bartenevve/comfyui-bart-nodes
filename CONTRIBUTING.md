# Adding a new node sub-package

This repo ships multiple ComfyUI nodes from one installed package (`LoadRandomImage`, `LoadRandomBooruImage`, `LoadRandom52Prompt`, ...). Each one lives in its own sub-package folder at the repo root. Follow this layout so a new node integrates cleanly — it's exactly the structure `booru/` and `prompts52/` already use.

## Folder layout

```
<subpkg>/
    __init__.py     # deliberately empty of imports - see below
    nodes.py         # the ComfyUI node class(es)
    routes.py        # aiohttp API routes for this node's frontend widgets
    selection.py     # optional: pure logic split out for dependency-free unit tests
    ...              # any other backend modules the node needs
js/<subpkg>.js        # frontend - MUST live here, not <subpkg>/js/
tests/test_<subpkg>_*.py
```

### `<subpkg>/__init__.py` stays empty

```python
"""<One-line description> (`<NodeClassName>`) - see ../README.md.

Deliberately empty of imports: the pack's top-level __init__.py pulls
`<subpkg>.nodes` and `<subpkg>.routes` in itself, so this package can be
imported (by the tests, for instance) without dragging torch/aiohttp along.
"""
```

Nothing in this file should `import torch`, `import aiohttp`, or anything else heavy. That's what lets `tests/` import `<subpkg>.selection` (or any pure module) directly, without a real ComfyUI environment, the same way `tests/test_selection.py` already does for the root package.

### `<subpkg>/nodes.py`

Match the conventions already established by the root `nodes.py`:

- `INPUT_TYPES()` classmethod; put anything that needs per-node identity (a sequential "advance to next" pointer, a running total, etc.) behind a `hidden: {"unique_id": "UNIQUE_ID"}` entry — see [Stateful/sequential behavior](#statefulsequential-behavior-race-safety) below.
- `RETURN_TYPES` / `RETURN_NAMES` / `FUNCTION` / `CATEGORY`.
- `IS_CHANGED` — if the node has any "changes every run" mode (random pick, auto-advance), return `float("nan")` for that mode so ComfyUI never caches a stale result; otherwise hash the actual inputs that determine output identity (see the "why hash `directory` too" note in the root `nodes.py`'s history — hashing only `filename` and not `directory` was a real bug there).
- `VALIDATE_INPUTS` — reject invalid input *combinations* here (e.g. two mutually-exclusive checkboxes both true), not just per-field checks. This runs server-side regardless of how the prompt was submitted (UI, a hand-edited workflow.json, or a raw API POST), so it's the actual enforcement point — don't rely on frontend JS alone for anything that must never reach execution.

### `<subpkg>/routes.py`

- Namespace every route path under a prefix unique to this node, e.g. `/random_booru/*`, `/random_prompts52/*`. `PromptServer.instance.routes` is a single global table shared by every installed custom node in the whole ComfyUI instance — a collision silently shadows or breaks someone else's route.
- Any blocking call (network fetch, `os.walk`, subprocess) **must** be offloaded off the event loop, or it stalls every other request ComfyUI is handling — including other users' generation jobs — for its whole duration:

  ```python
  async def _run(func, *args, **kwargs):
      loop = asyncio.get_event_loop()
      return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))
  ```

  (Both `booru/routes.py` and `prompts52/routes.py` define their own copy of this exact helper. If you're adding a fourth sub-package, consider whether it's finally worth factoring into a shared module instead of a fourth copy.)

- Validate every query param before using it (allowlist known values, `str.isdigit()`/range-check numeric ones, etc.) and return a clear `web.json_response({"error": ...}, status=4xx)` rather than letting an exception surface as a raw 500.
- If a route proxies a remote resource (an image, a file), take an *identifier* (a source name + post id, a known-good directory + filename) and resolve the actual URL/path server-side — never take a raw URL/path directly from the client. `booru/routes.py`'s `/random_booru/view` does this specifically so the node can't be turned into an open HTTP proxy for arbitrary hosts. This matters even though ComfyUI itself has no auth by default — an open-proxy primitive is a categorically worse exposure than "reads files ComfyUI's own process could already read."

### `js/<subpkg>.js`

`WEB_DIRECTORY` is declared **once**, in the root `__init__.py`, pointing at the single `js/` folder for the whole installed package. A sub-package's frontend file has to live directly under that same `js/` — `<subpkg>/js/foo.js` will never be served. Use `app.registerExtension({ name: "comfyui.<subpkg>", ... })` with a name distinct from the other nodes' extensions.

### Wiring into the root `__init__.py`

```python
from .nodes import LoadRandomImage
from .<subpkg>.nodes import <NodeClassName>
from . import routes  # noqa: F401  registers the aiohttp routes on import
from .<subpkg> import routes as <subpkg>_routes  # noqa: F401  same, for /<your_prefix>

NODE_CLASS_MAPPINGS = {
    "LoadRandomImage": LoadRandomImage,
    "<NodeClassName>": <NodeClassName>,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LoadRandomImage": "Load Random Image \U0001f3b2",
    "<NodeClassName>": "<Display Name> \U0001f3b2",
}
```

### Tests

Add `tests/test_<subpkg>_*.py` that import the sub-package's pure-logic modules directly (bypassing the root `__init__.py`, same trick `tests/test_selection.py` uses via `sys.path.insert`), so `python3 -m unittest discover -s tests` keeps working without a real ComfyUI/torch environment. Cover at minimum: input validation edge cases for every route parameter, and — if the node has any sequential/auto-advance mode — the same batch-queue race scenario the root `LoadRandomImage` had to be fixed for (see [Stateful/sequential behavior](#statefulsequential-behavior-race-safety)).

### `pyproject.toml` / `README.md`

Bump `version`, extend `description` to mention the new node, and add a README section for it (see the existing `## Load Random Booru Image` / `## Load Random Prompt (52prompts)` sections as the template — usage, any source-specific caveats, security notes if it talks to a third-party service).

## Stateful/sequential behavior: race safety

If your node has an "advance to the next X on every queue" mode, don't rely solely on a frontend widget value round-tripped through `onExecuted` — if several executions get queued before the first one's `onExecuted` fires (a batch count > 1, or just clicking Queue twice quickly), every one of them serializes the *same stale* widget value and you get duplicate/skipped output instead of a real advance.

The fix used in the root package's `selection.py` (`resolve_filenames`): keep an in-memory pointer keyed by `(unique_id, <whatever disambiguates the node's target>)`, seeded from the widget value on first use, authoritative afterward regardless of what stale value gets passed in on later calls. Guard the read-modify-write with a `threading.Lock`. See `selection.py`'s `_SEQUENTIAL_STATE`/`resolve_filenames` for the reference implementation, and its docstring for why the key includes more than just `unique_id`.

## Security posture

This pack's whole premise (arbitrary directories, external services) means its routes are more powerful than a typical custom node's. Two rules that already apply pack-wide and should extend to anything you add:

1. Any HTTP route is reachable by *anyone who can hit ComfyUI's port*, not just people using the graph UI — a bare `curl` is enough, no auth exists by default (in ComfyUI itself or in this pack). Don't add a route that turns ComfyUI into a proxy for arbitrary user-supplied URLs/paths (see the `/random_booru/view` note above).
2. Any request to a third-party host needs a timeout — a hung remote doesn't get to hold a worker thread (or the event loop, if not offloaded) forever.
