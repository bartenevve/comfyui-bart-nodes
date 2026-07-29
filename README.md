# comfyui-random-image

Two LoadImage-alike nodes that pick *which* image to load for you, instead of making you point at one file:

| Node | Picks from | Manual / random / stepping |
| --- | --- | --- |
| **Load Random Image 🎲** (`LoadRandomImage`) | an **arbitrary directory** on disk (not just the managed `ComfyUI/input`) | filename dropdown / random / next in alphabetical order |
| **Load Random Booru Image 🎲** (`LoadRandomBooruImage`) | a **booru tag search** (currently Gelbooru) | position in results / random / next position |

Both live in category `image`, share the same UI conventions (mode checkboxes, 🎲 button, live preview that survives a workflow reload) and the same advance-after-output semantics.

## Install (manual / from archive)

1. Copy/extract the `comfyui-random-image` folder into `<ComfyUI>/custom_nodes/`
2. Restart ComfyUI

Dependencies — `torch`, `Pillow`, `aiohttp`, `numpy` — already ship with ComfyUI, no separate install needed. The booru node does its HTTP with the standard library (`urllib`), so it adds nothing either.

## Install via git

```bash
cd <ComfyUI>/custom_nodes
git clone <your_repo_URL> comfyui-random-image
```

Update:

```bash
cd <ComfyUI>/custom_nodes/comfyui-random-image
git pull
```

Restart ComfyUI after installing/updating.

---

## Load Random Image 🎲

- **`directory`** — absolute path to a folder of images (recursive, `.png/.jpg/.jpeg/.webp/.bmp/.gif`). A small counter under the preview shows how many matching files were found, refreshed whenever the directory changes.
- **Filename dropdown** — manually pick a specific file from the list
- **🎲 Randomize** — button that instantly picks a random file and updates the preview (no graph execution needed)
- **Drag & drop** an image straight onto the node — uploads it through ComfyUI's own `/upload/image`, switches `directory` to the managed input dir, and selects the uploaded file (mirrors core LoadImage's behavior)
- **`randomize_on_queue`** — random pick on **every** Queue Prompt (server-side, not just via the button). Whatever is currently shown/selected is ignored when this runs, so the preview hides itself while this is checked — there is nothing meaningful to show until an actual run happens.
- **`sequential_on_queue`** — next file in alphabetical order on every Queue Prompt, wrapping back to the start after the last file. Unlike randomize mode, the currently shown file IS exactly what the next run will output, so the preview stays visible here.

The two checkboxes are mutually exclusive in the UI, and the server also rejects the queue if both end up enabled at once (guards against a hand-edited workflow.json).

**Sequential semantics:** a given run outputs the file **currently** selected (the one already shown in the preview), and the advance to the next one happens **after** — preparing the starting point for the next run. The advance is tracked in server memory per node `unique_id` + `directory`, which also protects against a batch-queue race (several runs queued before the first one finishes don't end up loading the same file repeatedly).

The node's preview shows what **actually** got loaded on the last run (survives saving/reopening the workflow), not what's queued up next — except while `randomize_on_queue` is checked, where it's hidden regardless, since that value is about to be discarded anyway.

**Outputs:** `IMAGE`, `MASK`, `filename` (the file that was actually loaded this run), `directory` (the resolved absolute directory path this run used).

---

## Load Random Booru Image 🎲

Pulls a post from a booru image board by tag search — randomly or by position in the result list — and outputs it as an `IMAGE`/`MASK` pair.

| Widget | Meaning |
| --- | --- |
| `source` | Which booru to query. Only `gelbooru` for now; the list comes from the source registry, so adding a backend adds an entry. |
| `tags` | Space-separated Gelbooru tag query, exactly what you would type in the site's search box (`1girl blue_eyes rating:general`, `cat -comic`, `sort:score`). Empty = the whole site, newest first. |
| `random_post` | Pick a random position in the result list on **every** Queue Prompt (server-side). |
| `increment_on_queue` | Advance to the next position on every Queue Prompt, wrapping at the end of the result list. |
| `index` | Position in the result list, 0-based, newest post first — used when neither checkbox is on, and as the starting point for `increment_on_queue`. |
| 🎲 **Random** | Frontend button: picks a random post right now, writes its position into `index` and shows it in the preview. No graph execution needed. |
| ↧ **Load index** | Fetches whatever position `index` currently holds into the preview. The spinner itself doesn't fetch — each step would be a request to a remote site. |
| preview | Last post that was actually loaded (or the last one a button fetched), plus an info line `#post_id · position / total · rating`. Proxied through ComfyUI, so the browser never talks to the booru directly. |

Same mutual exclusion and same advance-after-output rule as the directory node: a run outputs the post at the position **currently** shown, and the advance happens **after** it, seeding the next run. The pointer lives in server memory keyed by node `unique_id` + source + tags, so a batch count > 1 really walks the list instead of replaying the same snapshotted `index`. `random_post` hides the preview (the shown post is about to be discarded by a fresh pick); `increment_on_queue` keeps it.

**Outputs:** `IMAGE`, `MASK`, `post_id`, `post_tags` (the post's own tag string), `post_url` (link to the post page), `index` (the position actually used this run).

### Content rating

Gelbooru's "safe images only" switch is a per-account/session setting; anonymous requests already return every rating. The node additionally sends the `fringeBenefits=yup` cookie, which is the site's legacy explicit-content opt-in, so **all ratings are always included** — that is the intended behavior here, filter with tags (`rating:general`, `-rating:explicit`, …) if you want less.

### How the Gelbooru backend works

There is no usable anonymous JSON API: `index.php?page=dapi&s=post&q=index&json=1` answers **401 Unauthorized** without an `api_key`/`user_id` pair. So the backend scrapes the ordinary search page instead:

- **Listing** — `index.php?page=post&s=list&tags=<query>&pid=<offset>`. `pid` is a *post offset*, not a page number, and a page holds exactly **42** thumbnails (`&limit=` is ignored). Position `i` therefore lives on `pid = (i // 42) * 42`, at slot `i % 42`.
- **Total count** — taken from the paginator's "last page" link, then refined by fetching that last page and counting its thumbnails, so the count is exact whenever the last page is reachable. Cached for 60 s per (source, tags) so a button press and the following execution don't re-fetch it.
- **File URL** — the listing only carries thumbnails, so the post page (`index.php?page=post&s=view&id=<id>`) is fetched and the original file URL is read out of it (`https://imgN.gelbooru.com/images/…`), falling back to the sample image if no original is exposed.
- **Download** — `https://imgN.gelbooru.com/...` returns **302 → the post page** unless a `Referer: https://gelbooru.com/` header is sent, i.e. hotlinking is blocked; the backend sends it. Downloaded files are cached on disk under ComfyUI's temp directory (`random_booru/`), keyed by a hash of the URL, so a preview and the following execution download the image once.
- **Politeness** — requests to a given host are serialized with a minimum interval between them (0.6 s), so a batch queue can't turn into a request flood.

### Depth limit

Anonymous deep pagination is capped by Gelbooru: `pid=19992` still returns 42 posts, `pid=20034` returns none. The backend therefore exposes at most **20034 positions** (`index` 0…20033) regardless of how many posts a tag actually has, and a random pick never goes past that. Narrow the search with tags if you need to reach further into a large result set.

### Result list is not stable

Positions are relative to Gelbooru's default ordering (newest first), so new uploads matching your tags shift everything down. `index=5` is "the 6th newest match right now", not a permanent handle on a post — `post_id` is. Add `sort:id:asc` to `tags` if you want an ordering that only grows at the end.

Non-image posts (`.mp4`/`.webm`) can't be decoded: in random mode the node retries with a different position (a few attempts), in fixed/increment mode it raises an error naming the post.

### Adding another booru

`booru/sources/base.py` defines the interface (`Post` + `BooruSource`: `count()`, `page()`, `resolve_file_url()`), `booru/sources/gelbooru.py` implements it, `booru/sources/__init__.py` maps names to classes — dropping a module in there and registering it makes it appear in the `source` combo, no node or frontend change needed.

---

## ⚠️ Security

**Directory node.** The `/random_image/list`, `/random_image/pick` and `/random_image/view` routes accept a `dir` parameter with **no restriction whatsoever** — anyone who can reach ComfyUI's HTTP port (not necessarily through the graph/UI at all — a bare GET request is enough) can list and read the contents of arbitrary files on disk that the ComfyUI process has access to. This is a deliberate tradeoff for the node's core feature (loading from any folder), not a bug that an allowlist should close.

**Booru node.** It makes **outbound requests to a third-party image board** from the ComfyUI host, and any prompt containing it does so on execution — the booru sees your server's IP and your tag queries. The `/random_booru/*` routes take `source` + `tags` + `index`/`post_id`, never a raw URL, so the host that gets fetched is always derived from the selected source and these endpoints cannot be pointed at an arbitrary target (no SSRF). They are still unauthenticated like everything else here: anyone reaching the port can make your server fetch booru pages and fill the temp cache. Downloaded content is arbitrary third-party imagery, entirely unfiltered by rating (see above), and cached copies stay in ComfyUI's temp directory until it is cleaned.

**If ComfyUI is exposed on a LAN or the internet** (not just `127.0.0.1`), keep this in mind and restrict access at the network level (VPN, an authenticating reverse proxy, firewall) rather than assuming ComfyUI or these nodes restrict anything on their own. This isn't unique to this pack either — ComfyUI itself ships with no authentication on any of its endpoints by default.

## Tests

The pure logic — file selection, booru position selection, and the Gelbooru HTML parsers (against inline fixtures, no network) — is covered by unit tests:

```bash
python3 -m unittest discover -s tests -v
```

## Files

```
selection.py            pure logic for the directory node: list_images(), resolve_filenames()
nodes.py                LoadRandomImage: tensors/masks/EXIF handling
routes.py               /random_image/pick, /list, /view, /input_dir
booru/
  selection.py          pure position logic: resolve_index() (random / fixed / increment)
  pick.py               position -> post -> local file, incl. retry on non-image posts
  fetch.py              urllib GET with UA/cookie/referer, per-host throttle, disk cache
  nodes.py              LoadRandomBooruImage
  routes.py             /random_booru/pick, /count, /view, /sources
  sources/base.py       Post dataclass + BooruSource interface
  sources/gelbooru.py   Gelbooru scraper: listing / count / post-page parsing
  sources/__init__.py   name -> backend registry
js/random_image.js      frontend: file dropdown, randomize button, drag & drop, preview
js/random_booru.js      frontend: 🎲/↧ buttons, preview, info line, last_post_id persistence
__init__.py             registration of both nodes (NODE_CLASS_MAPPINGS) and WEB_DIRECTORY
tests/                  unit tests (_pack.py imports pack submodules without torch)
```

## Known limitations

- Sequential/increment advancement is kept in the ComfyUI process's memory (resets on restart, then simply continues from the last value persisted in the workflow) and isn't synchronized across multiple parallel ComfyUI workers/processes, if you happen to run that (uncommon) setup.
- The booru node can only address the first 20034 positions of a search, and those positions shift as new posts are uploaded (see above).
