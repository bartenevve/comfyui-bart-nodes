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
- `RETURN_TYPES` / `RETURN_NAMES` / `FUNCTION` / `CATEGORY`. Category is `Bart's nodes/<Image|Text|Audio>` and the display name starts with `Bart's `, so every node of the pack is found by searching "bart" and sits in one menu folder.
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

  (Both `booru/routes.py` and `prompts52/routes.py` define their own copy of this exact helper. If you're adding another sub-package that needs it, consider whether it's finally worth factoring into a shared module instead of a third copy.)

- Validate every query param before using it (allowlist known values, `str.isdigit()`/range-check numeric ones, etc.) and return a clear `web.json_response({"error": ...}, status=4xx)` rather than letting an exception surface as a raw 500.
- If a route proxies a remote resource (an image, a file), take an *identifier* (a source name + post id, a known-good directory + filename) and resolve the actual URL/path server-side — never take a raw URL/path directly from the client. `booru/routes.py`'s `/random_booru/view` does this at the route level, but **the guard is only as good as every step that resolves the identifier into a URL**: `booru/sources/gelbooru.py` reads the file URL out of third-party HTML, so it checks every candidate's host (`is_gelbooru_url`; new sources use the shared `base.url_on_domain`) when parsing *and* again in `download()` right before the request — this was once a real gap (two of three fallback regexes accepted any host), a reminder that "never take a raw URL from the client" isn't sufficient if something downstream can still be tricked into producing one. This matters even though ComfyUI itself has no auth by default — an open-proxy primitive is a categorically worse exposure than "reads files ComfyUI's own process could already read."

### `js/<subpkg>.js`

`WEB_DIRECTORY` is declared **once**, in the root `__init__.py`, pointing at the single `js/` folder for the whole installed package. A sub-package's frontend file has to live directly under that same `js/` — `<subpkg>/js/foo.js` will never be served. Use `app.registerExtension({ name: "comfyui.<subpkg>", ... })` with a name distinct from the other nodes' extensions.

### Wiring into the root `__init__.py`

Each node family's import is wrapped in its own `try/except` and adds directly to the shared `NODE_CLASS_MAPPINGS`/`NODE_DISPLAY_NAME_MAPPINGS` dicts, so one sub-package's import failure (a missing optional dependency, a broken environment) only disables that node — it never takes the rest of the pack down with it. This matters even for a sub-package with no unusual dependencies today; you don't control what a future dependency bump breaks. Add a new block following the existing ones:

```python
try:
    from .<subpkg>.nodes import <NodeClassName>
    from .<subpkg> import routes as <subpkg>_routes  # noqa: F401  registers /<your_prefix>

    NODE_CLASS_MAPPINGS["<NodeClassName>"] = <NodeClassName>
    NODE_DISPLAY_NAME_MAPPINGS["<NodeClassName>"] = "Bart's <Display Name> \U0001f3b2"
except Exception:
    logger.exception("comfyui-bart-nodes: <NodeClassName> failed to load, skipping it")
```

Omit the `routes` import/registration entirely if your sub-package has no aiohttp routes (a node that's just local compute, no frontend browsing/preview UX, doesn't need one — see `yue2/`).

If your dependencies are unusually heavy or non-standard (not on PyPI, needs a specific accelerator, etc.), keep the actual `import` of that dependency *inside* the function that uses it (see `yue2/nodes.py`'s `_get_pipeline()`), not at module level. That way the node class itself still registers and shows up in ComfyUI's node list even when the dependency isn't installed — the user gets a clear error only when they actually try to run it, instead of the node silently not existing.

### Tests

Add `tests/test_<subpkg>_*.py` that import the sub-package's pure-logic modules directly (bypassing the root `__init__.py`, same trick `tests/test_selection.py` uses via `sys.path.insert`), so `python3 -m unittest discover -s tests` keeps working without a real ComfyUI/torch environment. Cover at minimum: input validation edge cases for every route parameter, and — if the node has any sequential/auto-advance mode — the same batch-queue race scenario the root `LoadRandomImage` had to be fixed for (see [Stateful/sequential behavior](#statefulsequential-behavior-race-safety)).

### `pyproject.toml`, version, examples and `README.md`

Every change to the pack bumps `version` in `pyproject.toml` (the registry refuses a version it already has; a new node is a minor bump, a fix a patch). A new node also needs:

- a mention in `description`;
- an example workflow `example_workflows/NN_<name>.json` (build it in a real ComfyUI, save it, and load it back before committing) **and** a place in `12_all_nodes.json`, the graph that holds every node in groups;
- a README section, written from the template below, plus a row in "Nodes at a glance", the example table, the Security table and the Files tree.

#### README section template

Every node section looks the same, so a reader can find the same thing in the same place. Headings carry no emoji (they make the anchors fragile); the display name with its emoji lives in the overview table.

```markdown
## <Display name without the "Bart's" prefix>

<One sentence: what it does and for whom. Bold the one thing that sets it apart.>

| | |
| --- | --- |
| **Class · category** | `ClassName` · `Bart's nodes/<Image|Text|Audio>` |
| **Example workflow** | [`NN_name.json`](example_workflows/NN_name.json) |
| **Needs** | what must be installed or running (or "nothing beyond ComfyUI") |
| **Network** | outbound requests, to whom, how throttled (or "none") |
| **HTTP routes** | routes this node adds and what they accept (or "none") |
| **Verified** | what was actually run, and what was **not** |

### Widgets
| Widget | Meaning |      <- buttons and the preview are rows here too

### Outputs
| Output | Type | Meaning |      <- new outputs are appended, never inserted (links are saved by slot index)

### How it works
<the mechanism that is not obvious from the widget table: state, caching, protocols, limits of a backend>

### Notes and limits
- <known limits, gotchas, and anything that can surprise the user>
```

Keep the claims in **Verified** honest: say "not verified on a physical phone" rather than leaving the gap implicit.

## Stateful/sequential behavior: race safety

If your node has an "advance to the next X on every queue" mode, don't rely solely on a frontend widget value round-tripped through `onExecuted` — if several executions get queued before the first one's `onExecuted` fires (a batch count > 1, or just clicking Queue twice quickly), every one of them serializes the *same stale* widget value and you get duplicate/skipped output instead of a real advance.

The fix used in the root package's `selection.py` (`resolve_filenames`): keep an in-memory entry keyed by `(unique_id, <whatever disambiguates the node's target>)` holding `(pointer, last_widget_value_seen)`. A call arriving with the *same* widget value as last time is a queued-before-sync snapshot, so follow the pointer; a call arriving with a *different* value means the widget moved (manual pick, frontend sync, reloaded workflow), so the widget wins and the pointer is reseeded from it. A pointer that is authoritative unconditionally looks fine in a single-queue test but silently overrides the user's own selection the moment they change the widget between runs (this was a real bug, found by driving the real UI). Guard the read-modify-write with a `threading.Lock`. See `selection.py`'s `_SEQUENTIAL_STATE`/`resolve_filenames` for the reference implementation, and its docstring for why the key includes more than just `unique_id`.

## Security posture

This pack's whole premise (arbitrary directories, external services) means its routes are more powerful than a typical custom node's. Two rules that already apply pack-wide and should extend to anything you add:

1. Any HTTP route is reachable by *anyone who can hit ComfyUI's port*, not just people using the graph UI — a bare `curl` is enough, no auth exists by default (in ComfyUI itself or in this pack). Don't add a route that turns ComfyUI into a proxy for arbitrary user-supplied URLs/paths (see the `/random_booru/view` note above).
2. Any request to a third-party host needs a timeout — a hung remote doesn't get to hold a worker thread (or the event loop, if not offloaded) forever.
