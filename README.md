# comfyui-bart-nodes

Nodes that pick *what* to load for you, instead of making you point at one thing:

| Node | Picks from | Manual / random / stepping |
| --- | --- | --- |
| **Load Random Image 🎲** (`LoadRandomImage`) | an **arbitrary directory** on disk (not just the managed `ComfyUI/input`) | filename dropdown / random / next in alphabetical order |
| **Load Random Booru Image 🎲** (`LoadRandomBooruImage`) | a **booru tag search** (currently Gelbooru) | position in results / random / next position |
| **Load Random Prompt (52prompts) 🎲** (`LoadRandom52Prompt`) | one of the 20 **text prompt generators** on [52prompts.com](https://52prompts.com/), chosen from a dropdown | seed / random each run |

The two image nodes live in category `image`, the prompt node in `text`. All three share the same UI conventions (🎲 button that works without executing the graph, preview that survives a workflow reload).

The pack also has two differently-shaped groups of nodes: **Anatomy Defect Filter (Ollama) 🔍** (category `image/quality`, [below](#anatomy-defect-filter-ollama-)) sorts images into passed/failed using an Ollama vision model, and **YuE2 Model Loader / Plan Score / Generate Song 🎵** (category `audio/yue2`) wraps [m-a-p/YuE2-3B](https://huggingface.co/m-a-p/YuE2-3B) for actual music *generation*, not picking from something that already exists — see [its own section](#yue2-music-generation-) below, it has real GPU/dependency requirements the other four nodes don't.

## Install (manual / from archive)

1. Copy/extract the `comfyui-bart-nodes` folder into `<ComfyUI>/custom_nodes/`
2. Restart ComfyUI

Dependencies for the four picker nodes — `torch`, `Pillow`, `aiohttp`, `numpy` — already ship with ComfyUI, no separate install needed; the booru node does its HTTP with the standard library (`urllib`), so it adds nothing either. **YuE2 needs extra manual setup** — see its own section — but a missing YuE2 dependency only disables the YuE2 nodes, not the rest of the pack (each node family's import is isolated in `__init__.py`; see `CONTRIBUTING.md`).

## Install via git

```bash
cd <ComfyUI>/custom_nodes
git clone <your_repo_URL> comfyui-bart-nodes
```

Update:

```bash
cd <ComfyUI>/custom_nodes/comfyui-bart-nodes
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

**Sequential semantics:** a given run outputs the file **currently** selected (the one already shown in the preview), and the advance to the next one happens **after** — preparing the starting point for the next run. The advance is tracked in server memory per node `unique_id` + `directory`, together with the `filename` the previous run was given. That protects against a batch-queue race (several runs queued before the first one finishes all carry the same stale `filename`; they follow the pointer instead of loading the same file repeatedly) while still honoring the widget: if `filename` differs from last time — you picked another file, rolled the dice, or reloaded a workflow — the file shown in the widget is the one that loads.

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

Same mutual exclusion, advance-after-output timing, and batch-race protection as the directory node (see [Load Random Image](#load-random-image-) above) — the pointer here is keyed by `unique_id` + source + tags instead of `unique_id` + directory. `random_post` hides the preview (about to be discarded by a fresh pick); `increment_on_queue` keeps it.

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

Non-image posts (`.mp4`/`.webm`) can't be decoded: in random and increment mode the node skips to another position (a random one / the next in line, a few attempts), in fixed mode — where you named an exact position — it raises an error naming the post.

### Adding another booru

`booru/sources/base.py` defines the interface (`Post` + `BooruSource`: `count()`, `page()`, `resolve_file_url()`), `booru/sources/gelbooru.py` implements it, `booru/sources/__init__.py` maps names to classes — dropping a module in there and registering it makes it appear in the `source` combo, no node or frontend change needed.

---

## Load Random Prompt (52prompts) 🎲

Outputs a random **text** prompt from one of the generators in 52prompts.com's *Generators* menu — writing prompts, scenarios, character sheets, locations, hobbies, zodiac rolls and so on — as a `STRING` you can wire straight into a CLIP Text Encode.

| Widget | Meaning |
| --- | --- |
| `generator` | Which generator to use. Dropdown of all 20, named after the site's own menu entries (`Prompts`, `Scenarios - Two Person`, `Teen Characters`, `Monster Characters`, `Mermaids`, `Zodiac Signs`, …). |
| `randomize` | Draw a fresh prompt on **every** Queue Prompt. The seed that produced it is written back into `seed`, so a result worth keeping can be reproduced by turning this off. |
| `seed` | Used when `randomize` is off: the same seed + generator + inputs gives the same prompt, for as long as the site's word lists stay put. |
| `input_1` … `input_3`, `choice_list` | Only shown for the generators that ask for something. The scenario generators take character names (blank = the generator's own placeholder), the cast one takes a list of names, `Objects`/`Random Choice` take a count. The frontend hides and relabels these per generator, so you never see a field the selected generator ignores. |
| 🎲 **Generate** | Picks a prompt right now, with a fresh seed. No graph execution needed. |
| ↧ **Load seed** | Same, but for whatever `seed` currently holds. |
| preview | The prompt this node last output (persisted with the workflow), plus an info line naming the generator and seed. |

**Outputs:** `prompt` (plain text, multi-line for the character-sheet style generators), `generator`, `seed` (the seed that actually produced this prompt).

### How it works

Each generator on the site is a standalone `.js` file on the site's CDN, holding that generator's word lists **and** the string templating that turns them into a finished prompt. The sentence shapes only exist in the code, so scraping the arrays alone would get half the data — this node runs the file instead.

- **Discovery** — the generator page is fetched and the script URL read out of it (the CDN stamps a version into the path, so it does change over time). Only URLs on the site's CDN host are accepted.
- **Execution** — `prompts52/jsmini.py` is a small JavaScript interpreter covering exactly the subset those 20 files use: `var`/`if`/`for`, string concatenation, array literals, a handful of `String`/`Array`/`Math` methods and a `document` shim that feeds the node's widgets in as form fields. Anything outside that subset raises an error naming the construct rather than quietly producing nonsense — so if the site rewrites a generator, you get a message instead of a garbled prompt. `Math.random` is wired to a seeded RNG, which is where reproducibility comes from.
- **Caching** — the page and the script are memoized in memory for an hour, so a workflow queued fifty times fetches once. Requests to a host are serialized with a minimum interval (0.4 s).
- **No prompt data is stored in this repo.** The word lists are the site's content and are fetched at run time, exactly like the booru node fetches images rather than shipping them. The output HTML (`<br>` between character-sheet fields, the odd `<i>`) is flattened to text.

### Notes

- `Random Choice` shuffles **your own** list (`choice_list`) — it has no word list of its own; it is included because it is in the site's menu.
- Generators are versioned by the site, not by this pack: a seed reproduces a prompt only as long as the underlying word list is unchanged.

---

## Anatomy Defect Filter (Ollama) 🔍

Splits an `IMAGE` (one picture or a batch) into **`passed`** and **`failed`** by asking an [Ollama](https://ollama.com) vision model whether each picture has the anatomy defects you selected — extra or missing limbs, wrong finger count, smeared hands, impossible poses and so on. Wire `failed` into a Save Image node to keep the rejects separately, or just leave it unconnected to throw them away.

It needs a **chat-capable vision model** (`qwen3-vl`, `llama3.2-vision`, `gemma3`, `minicpm-v`, …). A pure embedding model cannot answer "does this hand have six fingers" — it only yields a vector. Use a non-thinking variant: Ollama returns thinking models' answer in a separate field and the node treats an empty answer as an error.

| Widget | Meaning |
| --- | --- |
| `ollama_url` | Base URL of the Ollama server, reachable **from the ComfyUI machine** (`http://host:11434`). |
| `model` | Name of the vision model as Ollama knows it (`ollama list`). Plain text on purpose — see Security. |
| `extra_limbs`, `missing_limbs`, `bad_fingers`, `smeared_limbs`, `impossible_pose`, `face_deformation`, `merged_bodies` | Which defects to look for. At least one check (or a custom criterion) must be on. |
| `custom_criterion` | Your own defect, in plain words (`a hand holding the cup has no thumb`). Evaluated like the built-in ones. |
| `confidence_threshold` | The model rates each check with a confidence 0–1; a *found* defect at or above this fails the image. Lower = stricter. |
| `max_side` | Longest side the image is downscaled to before sending (default 768). Bigger is slower and not always better; hands need enough pixels though. |
| `timeout`, `seed` | Per-request timeout; seed for the request (temperature is always 0). |
| `empty_branch` | What a branch with zero images outputs, see below. |

**Outputs:** `passed`, `failed`, `report` (one line per image: `#3 FAIL bad_fingers (0.85): six fingers on left hand`), `report_json` (same, machine-readable), `passed_indices`, `failed_indices` (comma-separated positions in the input batch, e.g. `0,2,5`, to put filtered images back in order). The text outputs are always produced, even when a branch has no images.

**Mixed batches.** With 10 images of which 2 are bad, `passed` is a batch of 8 and `failed` a batch of 2 — both ordinary outputs. `empty_branch` only matters when one side ends up with *no* images (e.g. all 10 passed, or you feed one image per queue so one output is always empty):

- `blocker` — the empty output is a ComfyUI `ExecutionBlocker`: every node that depends on it silently doesn't run (a Save Image on `failed` simply does nothing when nothing failed). The catch is that *all* nodes fed by that output are skipped, not just the Save.
- `placeholder` — the empty output is a single black image the size of the input, so downstream nodes always run. Filter it out yourself if you don't want it saved.

**How a verdict is made.** Each image gets one request: a checklist prompt, the image as base64 JPEG, `format: json`, temperature 0. The answer is parsed tolerantly (code fences, checks nested or top-level); a check the model omits counts as not found, a found defect with no confidence counts as fully confident. An unparsable answer is retried once with a different seed, then the run **fails with an error** — it never quietly marks the image as failed or passed. If Ollama is unreachable or the model is missing, the run also errors with the reason.

**Expect imperfect judgement.** Small vision models (7–8B) are unreliable at counting fingers and spotting subtle distortions, in both directions. Try the filter on ~20 images you've already judged by hand and tune `confidence_threshold` / model before filtering anything in bulk. Results for identical inputs and settings are cached by ComfyUI, so re-queuing an unchanged graph doesn't ask the model again.

---

## YuE2 Music Generation 🎵

Wraps [m-a-p/YuE2-3B](https://huggingface.co/m-a-p/YuE2-3B): style + lyrics in, a full stereo song out. Three nodes in category `audio/yue2`:

| Node | Does |
| --- | --- |
| **YuE2 Model Loader** | Loads the pipeline once (`vae`: `YuE2-Vae` or `YuE2-Vae-legacy`, `device`, default `auto` = CUDA, else Apple MPS, else CPU). Outputs a `YUE2_PIPELINE` to feed the other two. Cached in memory keyed by `(vae, device)` — ComfyUI can re-execute a loader node far more often than the ~7GB of weights actually need reloading. |
| **YuE2 Plan Score** | `style` + `lyrics` + `seed` → an editable `abc` (ABC notation) `STRING`, no audio rendered. The starting point for the agentic-editing loop below. |
| **YuE2 Generate Song** | `style` + `lyrics` + `cot` + `seed` (+ optional `abc`, `max_abc_tokens`, `max_semantic_tokens`) → `AUDIO` + the `abc` score that produced it. Feed the `AUDIO` output into ComfyUI's own **Save Audio** node. |

### `cot` (composition mode)

- `full` — plan melody and chords, then render. Default, best quality.
- `melody` — melody-only planning. What the model card recommends for covers.
- `off` — render directly, no symbolic planning pass.

### Cover and agentic editing are the same call, different arguments

yue2 doesn't have separate cover/edit entry points — both come down to calling `pipeline(...)` with an `abc` score already filled in:

- **Fresh generation**: leave `abc` blank.
- **Cover**: get an ABC transcription of an existing recording from wherever (**not** included in this pack — we could not confidently pin down "SheetSage2", the tool the model card mentions, to a real package/API; happy to add a transcription node once that's sorted out), feed it into `abc` with `cot="melody"`.
- **Agentic editing**: `YuE2 Plan Score` → revise the `abc` text (by hand, or via whatever agent/LLM node you wire up — that part is entirely outside yue2 itself) → `YuE2 Generate Song` with the revised `abc` and `cot="full"` → take its `abc` output, revise again, repeat.

### Requirements

- **Hardware.** The official target is a **24GB NVIDIA GPU** (BF16), ~70 s for a 3.6-minute song on an RTX 4090. `device=auto` also runs on **Apple silicon (MPS)** — verified here on a 32GB M-series Mac — but expect ~13 tokens/s: a 98-second power-metal track took about **13 minutes** (2.6 min planning, ~10 min audio) and ~11GB of memory. CPU works in principle and is far slower still. This is local inference, not a network call.
- **The `yue2` inference package** is *not on PyPI* and pins `torch==2.10.0`, `transformers==4.57.6` and a few more. Download the wheel from the [model repo's file list](https://huggingface.co/m-a-p/YuE2-3B/tree/main) (`yue2_infer-0.1.5-py3-none-any.whl` at the time of writing) and `pip install` that file. If your ComfyUI already has a different torch/transformers, that install will change them — consider a separate environment if you can't afford that.
- Model weights (7.3GB + a 0.5GB VAE) download automatically on first load, into the standard Hugging Face hub cache (`~/.cache/huggingface` by default) — not into ComfyUI's own `models/` folder. Check you have the disk space; if the download stalls on the new `xet` backend, retry with `HF_HUB_DISABLE_XET=1`.

### License

Model weights are **CC BY-NC 4.0 — non-commercial use only**. That's a constraint on the weights you download, separate from this pack's own MIT license on the node code itself. See `THIRD_PARTY_NOTICES.md` in the model repo for its own bundled dependencies.

### Making a shorter track

The song's length comes from the plan, and the plan from your lyrics: a few lines of `[chorus]` give a ~1.5-minute track, a full verse + chorus + bridge a lot more (and a plan of 4000+ tokens). **Write less lyrics to get a shorter song.** `max_abc_tokens` (default 4096) and `max_semantic_tokens` (default 9000) are hard caps on how much is generated, which bound worst-case time and memory — but hitting one *truncates* the plan or the audio mid-way rather than shortening it gracefully.

### Apple silicon: memory

On MPS the eager decoding loop leaks allocator cache: measured driver memory grew from 8GB to 25GB over ~2000 tokens while live tensors stayed at 7.4GB, until macOS killed the process ("your system has run out of application memory", even though Activity Monitor shows free memory — and with a nearly full disk macOS can't grow swap either). The nodes release the cache every 32 tokens, which keeps it flat at ~8–11GB. Close other heavy apps anyway.

### What has and hasn't been verified

The wrapper was checked against the `yue2` 0.1.5 source and run through the real package on Apple MPS (loader → plan → generate; the Generate node's `AUDIO` output holds a 98 s stereo 48 kHz waveform, the plan is valid ABC at the requested tempo). **Not** verified: running on CUDA, and running inside a ComfyUI graph with the real package (the test harness imported the node functions in a standalone environment, because yue2's torch pin differs from a current ComfyUI's).

---

## Example workflows

`example_workflows/` holds a ready-to-load graph for every node. ComfyUI lists them itself under **Templates → comfyui-bart-nodes**, or drag a `.json` onto the canvas. Each has a Note explaining what to set; the image examples ship with the placeholder `directory` `/path/to/your/images`, which you must point at a real folder before running.

| File | Shows |
| --- | --- |
| `01_load_random_image.json` | Load Random Image: manual pick / dice / drag & drop / `randomize_on_queue` |
| `02_sequential_images.json` | `sequential_on_queue`: one step per Queue, also with a batch count > 1 |
| `03_random_booru.json` | Load Random Booru Image with a `rating:general` tag search |
| `04_random_prompt_52prompts.json` | Load Random Prompt (52prompts) into a text preview |
| `05_anatomy_filter.json` | Directory loader → Anatomy Defect Filter → `passed` preview, `failed` saved to `output/rejected/`, report |
| `06_yue2_text_to_song.json` | YuE2 Model Loader → Generate Song → Save Audio |
| `07_yue2_plan_edit_generate.json` | YuE2 plan → editable ABC score → generate (the agentic-editing loop) |
| `08_yue2_cover_from_abc.json` | YuE2 cover mode: an externally obtained ABC transcription + `cot=melody` |

01–05 were loaded back into a real ComfyUI frontend and run from its Run button; 06–08 load fine but need the `yue2` package and a big GPU to execute (see the YuE2 section).

---

## ⚠️ Security

**Directory node.** The `/random_image/list`, `/random_image/pick` and `/random_image/view` routes accept a `dir` parameter with **no restriction whatsoever** — anyone who can reach ComfyUI's HTTP port (not necessarily through the graph/UI at all — a bare GET request is enough) can list and read the contents of arbitrary files on disk that the ComfyUI process has access to. This is a deliberate tradeoff for the node's core feature (loading from any folder), not a bug that an allowlist should close.

**Booru node.** It makes **outbound requests to a third-party image board** from the ComfyUI host, and any prompt containing it does so on execution — the booru sees your server's IP and your tag queries. The `/random_booru/*` routes take `source` + `tags` + `index`/`post_id`, never a raw URL from the caller. The file URL itself is read out of third-party HTML, so every candidate (`_ORIGINAL_URL`, `_OG_IMAGE`, `_MAIN_IMAGE`) must be on `gelbooru.com` or a subdomain (`imgN.gelbooru.com`) — a candidate on any other host is skipped — and `download()` re-checks the host right before the request goes out, so these endpoints cannot be pointed at an arbitrary target (no SSRF). They are also unauthenticated like everything else here: anyone reaching the port can make your server fetch booru pages and fill the temp cache. Downloaded content is arbitrary third-party imagery, entirely unfiltered by rating (see above), and cached copies stay in ComfyUI's temp directory until it is cleaned.

**52prompts node.** Same outbound-request caveat as the booru node: the site sees your server's IP, and `/random_prompts52/pick` is unauthenticated like everything else here. It takes a generator **label** out of a fixed table, never a URL, and the script URL it ends up fetching must be on the site's CDN host, so these endpoints cannot be pointed at an arbitrary target (no SSRF). The fetched script is **not** executed as JavaScript — it is run by `prompts52/jsmini.py`, which has no filesystem, network or `eval` surface at all: the worst a rewritten generator can do is raise an error or return odd text.

**Anatomy filter node.** It sends your images to whatever `ollama_url` the workflow says, from the ComfyUI host — so images leave the machine if that server is remote, and a workflow someone else wrote can point it at any host:port reachable from yours (it only ever POSTs to `/api/chat` on that base URL). The node adds **no HTTP routes**: a frontend helper that took the URL from the browser (for example to fill a model dropdown) would turn ComfyUI into an open proxy, which is why `model` is a plain text field.

**If ComfyUI is exposed on a LAN or the internet** (not just `127.0.0.1`), keep this in mind and restrict access at the network level (VPN, an authenticating reverse proxy, firewall) rather than assuming ComfyUI or these nodes restrict anything on their own. This isn't unique to this pack either — ComfyUI itself ships with no authentication on any of its endpoints by default.

## Tests

The pure logic — file selection, booru position selection, the Gelbooru HTML parsers, the JavaScript interpreter behind the 52prompts node (against inline fixtures, no network), and the anatomy filter's verdict parsing and Ollama client (against a mocked server) — is covered by unit tests:

```bash
python3 -m unittest discover -s tests -v
```

One extra suite checks that all 20 generators on the live site still run. It is skipped unless you ask for it, since it makes ~40 requests:

```bash
PROMPTS52_LIVE=1 python3 -m unittest tests.test_prompts52_live -v
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
prompts52/
  jsmini.py             tiny JS interpreter: tokenizer, parser, evaluator, document shim
  catalog.py            the 20 generators: label -> page slug + which widgets it reads
  runner.py             script discovery, run, HTML -> text
  fetch.py              urllib GET, per-host throttle, in-memory TTL cache
  nodes.py              LoadRandom52Prompt
  routes.py             /random_prompts52/pick, /generators
anatomy/
  selection.py          pure logic: check catalogue, prompt, verdict parsing, pass/fail decision, report
  ollama.py             stdlib client for Ollama's /api/chat (vision question -> answer text)
  nodes.py              AnatomyDefectFilter: tensor -> JPEG, loop over the batch, split, empty-branch handling
yue2/
  selection.py          pure logic: artifact-file discovery, generate() kwargs assembly
  nodes.py              YuE2ModelLoader, YuE2Plan, YuE2Generate; pipeline cache, ABC/audio I/O
js/random_image.js      frontend: file dropdown, randomize button, drag & drop, preview
js/random_booru.js      frontend: 🎲/↧ buttons, preview, info line, last_post_id persistence
js/random_prompts52.js  frontend: 🎲/↧ buttons, per-generator widget show/hide, prompt display
__init__.py             registration of all node families, each import isolated (see CONTRIBUTING.md)
example_workflows/     one ready-to-load graph per node (listed by ComfyUI under Templates)
tests/                  unit tests (_pack.py imports pack submodules without torch)
```

## Known limitations

- Sequential/increment advancement is kept in the ComfyUI process's memory (resets on restart, then simply continues from the last value persisted in the workflow) and isn't synchronized across multiple parallel ComfyUI workers/processes, if you happen to run that (uncommon) setup.
- The booru node can only address the first 20034 positions of a search, and those positions shift as new posts are uploaded (see above).
- The 52prompts node depends on the shape of the site's generator scripts. They are hand-written and have been stable for years, but a rewrite that reaches outside the supported JavaScript subset would need `prompts52/jsmini.py` extended — it fails loudly with the offending construct when that happens.
- The YuE2 nodes have run end to end on Apple MPS (slow: ~13 min for a 98 s track) but not on CUDA, and not inside a ComfyUI graph with the real `yue2` package installed — see the YuE2 section.
- The anatomy filter has been run end to end in a real ComfyUI against a local Ollama (`qwen3-vl:8b`) on a few synthetic images — enough to show the routing, empty-branch modes and error paths work, not enough to say how well any model spots real six-fingered hands. Judgement quality depends entirely on the vision model you pick; calibrate on your own images.
- **TODO:** YuE2 isn't a row in the top overview table (line ~5) — it's a generative node, doesn't fit the "picks from" framing the table uses, so it's a prose mention + separate section instead. That's caused confusion (looks like the pack has 3 nodes at a glance). Rework the intro — either a second small table, or restructure the first one to fit both shapes.
