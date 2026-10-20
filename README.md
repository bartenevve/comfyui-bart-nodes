# comfyui-bart-nodes

Every node is named `Bart's ...` (search for "bart" to list them all) and sits under the **Bart's nodes** category, split into `Image`, `Text` and `Audio`.

Nodes that pick *what* to load for you, instead of making you point at one thing:

| Node | Picks from | Manual / random / stepping |
| --- | --- | --- |
| **Bart's Load Random Image 🎲** (`LoadRandomImage`) | an **arbitrary directory** on disk (not just the managed `ComfyUI/input`) | filename dropdown / random / next in alphabetical order |
| **Bart's Load Random Booru Image 🎲** (`LoadRandomBooruImage`) | a **booru tag search** (Gelbooru, yande.re, Konachan, Safebooru, Xbooru) | position in results / random / next position |
| **Bart's Load Random Prompt (52prompts) 🎲** (`LoadRandom52Prompt`) | one of the 20 **text prompt generators** on [52prompts.com](https://52prompts.com/), chosen from a dropdown | seed / random each run |

The two image nodes live in `Bart's nodes/Image`, the prompt node in `Bart's nodes/Text`. All three share the same UI conventions (🎲 button that works without executing the graph, preview that survives a workflow reload).

Two more groups do something different — they *process* or *generate* rather than pick:

| Node | Does | Needs |
| --- | --- | --- |
| **Bart's Smart Load Image (Crop) ✂️** (`SmartLoadImage`, category `Bart's nodes/Image`) — [details](#smart-load-image-crop) | loads an image and lets you crop it right on the node; only the selected part is output | nothing beyond ComfyUI |
| **Bart's Anatomy Defect Filter (Ollama) 🔍** (`AnatomyDefectFilter`, category `Bart's nodes/Image`) — [details](#anatomy-defect-filter-ollama-) | splits images into `passed` / `failed` by asking an Ollama vision model about anatomy defects (extra limbs, wrong finger count, ...) | an Ollama server with a chat-capable vision model |
| **Bart's MiniMax H3 Prompt (Ollama) 🎬** (`MiniMaxH3Prompt`, category `Bart's nodes/Text`) — [details](#minimax-h3-prompt-ollama-) | writes ready-to-use prompts for the MiniMax H3 video model with a local Ollama LLM, from a short request (any language); a Generate button fills the result without running the graph | an Ollama server + a chat model (non-thinking instruct models work best) |
| **Bart's YuE2 Model Loader / Plan Score / Generate Song 🎵** (category `Bart's nodes/Audio`) — [details](#yue2-music-generation-) | generates a full song from style + lyrics with [m-a-p/YuE2-3B](https://huggingface.co/m-a-p/YuE2-3B), with an editable ABC score between planning and rendering | the `yue2` wheel and a big GPU (24GB NVIDIA, or Apple silicon, slowly) — real requirements the other nodes don't have |

## Install (manual / from archive)

1. Copy/extract the `comfyui-bart-nodes` folder into `<ComfyUI>/custom_nodes/`
2. Restart ComfyUI

Dependencies for the picker nodes and the anatomy filter — `torch`, `Pillow`, `aiohttp`, `numpy` — already ship with ComfyUI, no separate install needed; the booru, 52prompts and Ollama clients all use the standard library (`urllib`), so they add nothing either. **YuE2 needs extra manual setup** — see its own section — but a missing YuE2 dependency only disables the YuE2 nodes, not the rest of the pack (each node family's import is isolated in `__init__.py`; see `CONTRIBUTING.md`).

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

## Smart Load Image (Crop)

Like the stock Load Image, plus a crop editor on the node: pick a file, frame the part you want, and **only that part leaves the node**.

| Part | What it does |
| --- | --- |
| `image` + **📁 Upload image** | Files from ComfyUI's `input` folder. Upload a new one with the button or **drop an image on the node** - it is saved to `input` and selected. The preview comes from ComfyUI's own `/view`; the node adds no routes for serving files. |
| the preview | **Drag on empty space** to draw a crop box, **drag inside** it to move it, **drag a handle** (corners and sides) to resize. The area outside is dimmed, thirds guides are drawn, and the info line shows `900×600 → 471×337 at (163, 142) · 1.398`. |
| `crop_x`, `crop_y`, `crop_width`, `crop_height` | The crop in **pixels of the original image**. The editor writes them while you drag; you can also type them, or **link** them from other nodes. `crop_width` or `crop_height` of **0 = no crop** (the whole image, which is the default). A box sticking out of the image is cut at its edge instead of failing, so a saved crop still works if the file is later replaced by a smaller one. |
| `aspect_lock` | `free`, `original`, `1:1`, `4:3`, `3:4`, `3:2`, `2:3`, `16:9`, `9:16`, `21:9`, `9:21`. While it is not `free`, drawing and resizing keep the ratio, and picking one reshapes the current box (shrinking it around its centre, never growing). |
| `snap_to` | `1`, `8`, `16`, `32`, `64`: width and height snap to multiples of it (handy for diffusion models). With a ratio lock and a grid the closest pair on the grid is chosen, so 16:9 on a 64 grid becomes 1024×576 when it fits and a near ratio like 896×512 when it doesn't. |
| **⤢ Full image** / **▣ Fit aspect** | Remove the crop / make the largest box of the chosen ratio, centred. |

**Outputs:** `IMAGE` and `MASK` (from the alpha channel, like Load Image) of the cropped part only, `width` and `height` of that part, `filename`. Animated files (GIF/WebP) are cropped frame by frame with the same box.

Notes:
- The crop is applied **after** EXIF rotation, the same way the browser shows the preview, so what you frame is what you get. Verified on a photo stored sideways with an EXIF orientation tag.
- Choosing a different file resets the crop to "no crop".
- The editor shows the crop widgets' own values. If you link a crop number from another node, the link wins when the graph runs, but the preview box keeps showing the widget's value.
- Files outside ComfyUI's `input` folder: use [Load Random Image](#load-random-image-) for an arbitrary directory (no crop there).

## Load Random Booru Image 🎲

Pulls a post from a booru image board by tag search — randomly or by position in the result list — and outputs it as an `IMAGE`/`MASK` pair.

| Widget | Meaning |
| --- | --- |
| `source` | Which booru to query: `gelbooru`, `yandere` ([yande.re](https://yande.re)), `konachan` / `konachan_net` ([konachan.com](https://konachan.com), and its safe-for-work mirror [konachan.net](https://konachan.net)), `safebooru` ([safebooru.org](https://safebooru.org)) or `xbooru` ([xbooru.com](https://xbooru.com), explicit). The list comes from the source registry, so adding a backend adds an entry. |
| `tags` | Space-separated tag query, exactly what you would type in the chosen site's search box (`1girl blue_eyes rating:general`, `cat -comic`, `sort:score`). Empty = the whole site, newest first. |
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

### yande.re and Konachan backends (Moebooru)

These run the Moebooru engine, which has a plain anonymous JSON API, so the backend does not scrape HTML. One engine class (`MoebooruSource`), one small subclass per site:

- **Listing** — `post.json?tags=<query>&limit=100&page=<n>`; position `i` is on page `i // 100 + 1`, slot `i % 100`.
- **Total count** — the `count` attribute in the header of `post.xml?tags=<query>&limit=1`, cached for 60 s like the Gelbooru count. Capped at 1,000,000 positions; pages deeper than the query's real size come back empty. (yande.re has ~1.3 M posts, Konachan far fewer.)
- **File URL** — one extra `post.json?tags=id:<id>` request, the `file_url` field. It must be on the site's own domain or a subdomain (`files.yande.re`), otherwise the post is refused.
- **Download** — the original file (often several MB, PNGs included), sent with a `Referer`, cached on disk like the other backends.
- **Ratings** — `rating:s` / `rating:q` / `rating:e` (safe / questionable / explicit) work as tags; anonymous queries return every rating, except on `konachan_net`, which only ever has the safe ones.

### Safebooru and Xbooru backends (Gelbooru 0.2 `dapi`)

Unlike gelbooru.com itself (see above), these two answer the old Gelbooru API anonymously:

- **Listing** — `index.php?page=dapi&s=post&q=index&json=1&limit=100&pid=<page>&tags=<query>`. The API's `pid` is a page number, so position `i` is on page `i // 100`, slot `i % 100`. An empty body means "no results".
- **Total count** — the `<posts count="N">` header of the same call without `json=1`, cached for 60 s.
- **File URL** — `&id=<id>` returns that single post; its `file_url` (or `images/<directory>/<image>` when absent) must be on the site's own domain or a subdomain (`img.xbooru.com`).
- **Depth limit** — measured on both sites: the API answers up to an offset of **200,000** (`pid * limit`) and refuses beyond that with `API limited due to abuse`. The backend exposes at most 200,100 positions and surfaces the site's message if it is refused anyway. Narrow the search with tags to reach further into a big result set.

Planned and ruled-out sites are listed with reasons in [ROADMAP.md](ROADMAP.md).

### Adding another booru

`booru/sources/base.py` defines the interface (`Post` + `BooruSource`: `count()`, `page()`, `resolve_file_url()`), `booru/sources/gelbooru.py` implements it, and `booru/sources/moebooru.py` / `booru/sources/dapi.py` are engine base classes (a new site on either engine only sets `name`, `origin` and `domain`), `booru/sources/__init__.py` maps names to classes — dropping a module in there and registering it makes it appear in the `source` combo, no node or frontend change needed.

---

## Load Random Prompt (52prompts) 🎲

Outputs a random **text** prompt from one of the generators in 52prompts.com's *Generators* menu — writing prompts, scenarios, character sheets, locations, hobbies, zodiac rolls and so on — as a `STRING` you can wire straight into a CLIP Text Encode.

| Widget | Meaning |
| --- | --- |
| `generator` | Which generator to use. Dropdown of all 20, named after the site's own menu entries (`Prompts`, `Scenarios - Two Person`, `Teen Characters`, `Monster Characters`, `Mermaids`, `Zodiac Signs`, …). |
| `randomize` | Draw a fresh prompt on **every** Queue Prompt. The seed that produced it is written back into `seed`, so a result worth keeping can be reproduced by turning this off. |
| `seed` | Used when `randomize` is off: the same seed + generator + inputs gives the same prompt, for as long as the site's word lists stay put. Seeds go up to 2⁵³−1 — the largest integer the frontend's JS numbers hold exactly, so the seed shown after a randomized run is the seed that really made the prompt. |
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

It needs a **chat-capable vision model** (`qwen3-vl`, `llama3.2-vision`, `gemma3`, `minicpm-v`, …). A pure embedding model cannot answer "does this hand have six fingers" — it only yields a vector. Thinking-capable models (the default `qwen3-vl` tag is one) are handled: the request sends `think: false`, and because qwen3-family models ignore that and still burn their whole token budget thinking, `append_no_think` adds the `/no_think` soft switch to the prompt. If an answer still comes back empty the error says so.

| Widget | Meaning |
| --- | --- |
| `ollama_url` | Base URL of the Ollama server, reachable **from the ComfyUI machine** (`http://host:11434`). |
| `model` | Name of the vision model as Ollama knows it (`ollama list`). Plain text on purpose — see Security. |
| `extra_limbs`, `missing_limbs`, `bad_fingers`, `smeared_limbs`, `impossible_pose`, `face_deformation`, `merged_bodies` | Which defects to look for. At least one check (or a custom criterion) must be on. |
| `custom_criterion` | Your own defect, in plain words (`a hand holding the cup has no thumb`). Evaluated like the built-in ones. |
| `confidence_threshold` | The model rates each check with a confidence 0–1; a *found* defect at or above this fails the image. Lower = stricter. |
| `max_side` | Longest side the image is downscaled to before sending (default 768). Bigger is slower and not always better; hands need enough pixels though. |
| `timeout`, `seed` | Per-request timeout; seed for the request (temperature is always 0; the seed is capped at 2³¹−1 because Ollama reads it as a signed integer). |
| `num_ctx` | Context window requested from Ollama (default 4096, enough for the checklist + one image + a short JSON answer). Pinned because Ollama otherwise sizes it from free memory — 22GB for one image on a 32GB machine, which made `qwen3-vl:8b` crawl at under 1 token/s. |
| `append_no_think` | Append `/no_think` to the prompt (default on). Needed for qwen3-family models, ignored by others. |
| `empty_branch` | What a branch with zero images outputs, see below. |

**Outputs:** `passed`, `failed`, `report` (one line per image: `#3 FAIL bad_fingers (0.85): six fingers on left hand`), `report_json` (same, machine-readable), `passed_indices`, `failed_indices` (comma-separated positions in the input batch, e.g. `0,2,5`, to put filtered images back in order). The text outputs are always produced, even when a branch has no images.

**Mixed batches.** With 10 images of which 2 are bad, `passed` is a batch of 8 and `failed` a batch of 2 — both ordinary outputs. `empty_branch` only matters when one side ends up with *no* images (e.g. all 10 passed, or you feed one image per queue so one output is always empty):

- `blocker` — the empty output is a ComfyUI `ExecutionBlocker`: every node that depends on it silently doesn't run (a Save Image on `failed` simply does nothing when nothing failed). The catch is that *all* nodes fed by that output are skipped, not just the Save.
- `placeholder` — the empty output is a single black image the size of the input, so downstream nodes always run. Filter it out yourself if you don't want it saved.

**How a verdict is made.** Each image gets one request: a checklist prompt (each line is a *problem*; `found: true` means it is present in this image — a custom criterion read as an expectation once inverted the verdict), the image as base64 JPEG, `format: json`, temperature 0, at most 1024 answer tokens. The answer is parsed tolerantly (code fences, checks nested or top-level); a check the model omits counts as not found, a found defect with no confidence counts as fully confident, and a confidence given in percent (`85`) is read as 0.85. An unparsable answer is retried once with a different seed, then the run **fails with an error** — it never quietly marks the image as failed or passed. If Ollama is unreachable or the model is missing, the run also errors with the reason.

**Expect imperfect judgement.** Small vision models (7–8B) are unreliable at counting fingers and spotting subtle distortions, in both directions. Try the filter on ~20 images you've already judged by hand and tune `confidence_threshold` / model before filtering anything in bulk. Results for identical inputs and settings are cached by ComfyUI, so re-queuing an unchanged graph doesn't ask the model again.

---

## MiniMax H3 Prompt (Ollama) 🎬

Turns a short request ("an old fisherman hauls a net at dawn, gulls circling the boat") into a finished prompt for the **MiniMax H3** video model, using a local Ollama model. The heavy lifting is the bundled **h3kit** ([minimaxh3prompt/](minimaxh3prompt/), docs in [README_ru.md](minimaxh3prompt/README_ru.md), test log in [TESTS.md](minimaxh3prompt/TESTS.md)): Python computes the shot plan, cut times, picture-binding line, trigger placement and dialogue blocks, the LLM only writes the scene, then Python auto-fixes the answer, validates it and retries with the concrete error list. The node is the ComfyUI wrapper around it.

### Generate button, saved text, running the graph

| Step | What happens |
| --- | --- |
| **✨ Generate** | Runs the whole pipeline right now, **without executing the graph**, and fills the `generated` box. Every press picks a **new seed**, so **🔄 Regenerate** gives another take. The server round trip runs off the event loop; the button shows `⏳ Generating…` and ignores clicks until it is done. The info line shows the variant, clip count and validator result (or the error). |
| `generated` | The result. Saved with the workflow, **editable by hand**. |
| Run the graph, `generated` not empty | The saved text is output **as is**: nothing is sent to Ollama, hand edits included. This also holds when you changed the request after generating - the node never silently replaces text you may have edited; it shows `⚠ inputs changed since this text was generated` instead, and **Regenerate** redoes it. |
| Run the graph, `generated` empty | The run generates first (with the `seed` widget), outputs the result and writes it into `generated`, so the next run reuses it. |

### Widgets

| Widget | Meaning |
| --- | --- |
| `ollama_url`, `model` | The Ollama server (http/https) and a chat model. Tested: `qwen3:4b-instruct`, Qwen 3.6 / 3.8 class models with thinking off (200-400 tokens per answer). For the very smallest models (1-2B) try `variant = slots`. |
| `request` | What to film, in any language. |
| `duration`, `aspect`, `mode`, `variant`, `shots` | `duration` 4-120 s (over 15 s = `story`, see below); `mode` T2VA / I2VA / FL2VA / L2VA; `variant` `auto` picks `t2va` / `i2va` / `fl2va` / `talking` / `product` / `ref` / `story` from the inputs, or force one (`slots` is never picked automatically); `shots` 0 = automatic, 1-3 forces the count. |
| `triggers` | `style:retro_vhs, subject:sks_man, object:avr_bot, place:alps_road, plain_style_word` - each placed exactly once. |
| `dialogue`, `text` | Lines split by newline or ` \| `, optional `S2:` speaker and `[Spanish]` language prefix; `text` is on-screen text (the only thing that gets quotes). |
| `image` / `start` / `end` | Shown only for the modes that read them (I2VA first frame; FL2VA start + end; L2VA end). |
| `refs` | Ref2VA references, **one per line**: `image\|subject\|young woman in a green parka\|S1`, `video\|motion\|...`, `audio\|voice\|...`. They are text descriptions - the actual image/video/audio files go into H3 itself. Shown for `auto` / `ref`. |
| `seed` | Sampling seed. The button sets a new one on every press; for run-time generation `control after generate` behaves as usual. |
| `short_side` | Pixels of the frame's short side for the `width` / `height` outputs (256-4096, default 768). Both sides are rounded **down** to a multiple of 32 (what the H3 nodes use), so 16:9 at 768 gives 1344×768 - the H3 nodes' own default. Last in the widget list on purpose (saved workflows are positional). |
| `temperature`, `num_ctx`, `num_predict`, `retries`, `timeout`, `think` | Ollama options; `retries` = how many times the kit re-asks with the validator's error list (0-5); `num_predict` 0 = the model's default. |
| `append_no_think` | Appends Qwen3's `/no_think` switch to the last user message. Keep it on for Qwen3-family models; turn it off for other models if you see the literal text in their output. |

**Outputs** (new ones are always appended, so existing links keep their slots):

| Output | Type | Meaning |
| --- | --- | --- |
| `prompt` | `STRING` list | One entry per clip - a single entry for everything except `story`. |
| `report` | `STRING` | Variant, clip count, validator result, warnings such as "too much dialogue for this duration". |
| `duration` | `INT` list | Seconds, one per clip (`story` clips get their own, about 10 s each; otherwise the `duration` widget). |
| `frames` | `INT` list | `duration × 24` (24 fps). The H3 nodes snap a length up to their 17k+5 frame grid themselves. |
| `width`, `height` | `INT` | From `aspect` + `short_side`; 9:16 at 512 gives 512×896. |
| `seed` | `INT` | The seed this run used. |

The list outputs make a video node fed by `prompt` + `duration` run once per clip with that clip's own length; `width`, `height` and `seed` are shared by all clips. Wire them into a video node's duration / size / seed inputs (for the Cloud and API H3 nodes, whose `aspect_ratio` is a dropdown, set it by hand - a `STRING` can't feed a dropdown).

**Linked inputs.** Any widget can be turned into an input and fed by a link (for example one shared `duration` for this node and the video node). The graph uses the linked value. The **Generate button** runs outside the graph, so it can only read a linked value from a Primitive-style source node (`Int`, `Primitive`, ...) - if a widget is fed by a node whose output is computed when the graph runs, the button says so and does nothing; unlink it or use a Primitive node.

**`story` (over 15 s).** A planner splits the video into clips of about 10 s, then each clip is written as its own prompt with the characters carried over and "end of clip N = start of clip N+1". In `generated` the clips are separated by `=== CLIP 2 (10 s) ===` marker lines (edit them freely; text before the first marker counts as a clip too); `prompt` outputs one string per clip, so downstream nodes run once per clip.

### Notes

- If the validator still finds problems after the retries, the best attempt is returned anyway and the problems are listed in `report` - a prompt that is 95% right is more useful to edit than an error.
- **Thinking models.** `qwen3-vl:8b` was tried here: it ignores both `think: false` and `/no_think` with this kit's system prompt and spent its whole token budget reasoning (700 and even 3000 tokens, no answer). The node then reports an empty answer with a hint. Use a non-thinking instruct model, or a thinking model with a large `num_predict` and patience.
- **Interrupt.** ComfyUI's Interrupt doesn't cancel a generation that is already waiting on Ollama (the request is a blocking HTTP call); it ends at the answer or at `timeout`.
- `minimaxh3prompt/h3kit.py` is the kit as delivered plus a small patch: `ollama_chat()` accepts `seed` and `no_think` (and the CLI has `--seed` / `--no-think`). Everything else is untouched, so a newer kit version can be dropped in and the patch re-applied.
- Verified: the whole pipeline against a real Ollama - `qwen3:4b-instruct` (4 GB, 4-10 s per prompt, validator OK on the first attempt, a different take per seed, `story` with 3 clips) and Qwen3.8 27B (valid on the first attempt, 30-110 s) - and the button / saved text / generate-on-run / stale hint / mode-dependent fields / save-and-reload behaviour in a real ComfyUI frontend against a mock Ollama. Not verified: `variant = slots` on 1-4B models, and linking `duration` / size / seed into the real MiniMax video nodes (their inputs were read from the node definitions only).

## YuE2 Music Generation 🎵

Wraps [m-a-p/YuE2-3B](https://huggingface.co/m-a-p/YuE2-3B): style + lyrics in, a full stereo song out. Three nodes in category `Bart's nodes/Audio`:

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
| `09_minimax_h3_prompt.json` | MiniMax H3 prompt: request in, Generate button, prompt + report previews |
| `10_smart_load_image.json` | Smart Load Image: crop on the node, cropped preview + width / height |

01–05, 09 and 10 were loaded back into a real ComfyUI frontend and run from its Run button; 06–08 load fine but need the `yue2` package and a big GPU to execute (see the YuE2 section).

---

## ⚠️ Security

**Directory node.** The `/random_image/list`, `/random_image/pick` and `/random_image/view` routes accept a `dir` parameter with **no restriction whatsoever** — anyone who can reach ComfyUI's HTTP port (not necessarily through the graph/UI at all — a bare GET request is enough) can list and read the contents of arbitrary files on disk that the ComfyUI process has access to. This is a deliberate tradeoff for the node's core feature (loading from any folder), not a bug that an allowlist should close.

**Booru node.** It makes **outbound requests to a third-party image board** from the ComfyUI host, and any prompt containing it does so on execution — the booru sees your server's IP and your tag queries. The `/random_booru/*` routes take `source` + `tags` + `index`/`post_id`, never a raw URL from the caller. The file URL itself is read out of third-party responses (HTML for Gelbooru, JSON for the rest), so every candidate (Gelbooru: `_ORIGINAL_URL`, `_OG_IMAGE`, `_MAIN_IMAGE`; the JSON sources: the `file_url` field) must be on the source's own domain or a subdomain (`gelbooru.com` / `imgN.gelbooru.com`, `yande.re` / `files.yande.re`, `xbooru.com` / `img.xbooru.com`, ...) — a candidate on any other host is skipped — and `download()` re-checks the host right before the request goes out, so these endpoints cannot be pointed at an arbitrary target (no SSRF). They are also unauthenticated like everything else here: anyone reaching the port can make your server fetch booru pages and fill the temp cache. Downloaded content is arbitrary third-party imagery, entirely unfiltered by rating (see above), and cached copies stay in ComfyUI's temp directory until it is cleaned.

**52prompts node.** Same outbound-request caveat as the booru node: the site sees your server's IP, and `/random_prompts52/pick` is unauthenticated like everything else here. It takes a generator **label** out of a fixed table, never a URL, and the script URL it ends up fetching must be on the site's CDN host, so these endpoints cannot be pointed at an arbitrary target (no SSRF). The fetched script is **not** executed as JavaScript — it is run by `prompts52/jsmini.py`, which has no filesystem, network or `eval` surface at all: the worst a rewritten generator can do is raise an error or return odd text.

**MiniMax H3 prompt node.** Same outbound-request caveat as the anatomy filter (it POSTs your request text to the `ollama_url` of the workflow, from the ComfyUI host), **plus one HTTP route**: `POST /minimax_h3/generate` takes the widget values - including `ollama_url` - from the caller, so anyone who can reach ComfyUI's port can make the server send a JSON POST to `/api/chat` on any http(s) host:port it can reach (loopback and LAN included) and read back the parsed prompt text or an error message. Mitigations: only http/https, a fixed path, a timeout, only the parsed `message.content` is returned (never a raw response), and every other value is range-checked. It is the same exposure class as the other routes here (ComfyUI has no auth by default); if the port is reachable by people you don't trust, don't leave this node installed.

**Anatomy filter node.** It sends your images to whatever `ollama_url` the workflow says, from the ComfyUI host — so images leave the machine if that server is remote, and a workflow someone else wrote can point it at any host:port reachable from yours (it only ever POSTs to `/api/chat` on that base URL). The anatomy node adds **no HTTP routes** (the MiniMax node's button route is described above): a frontend helper that took the URL from the browser (for example to fill a model dropdown) would turn ComfyUI into an open proxy, which is why `model` is a plain text field.

**If ComfyUI is exposed on a LAN or the internet** (not just `127.0.0.1`), keep this in mind and restrict access at the network level (VPN, an authenticating reverse proxy, firewall) rather than assuming ComfyUI or these nodes restrict anything on their own. This isn't unique to this pack either — ComfyUI itself ships with no authentication on any of its endpoints by default.

## Tests

The pure logic — file selection, booru position selection, the booru backends' parsers (Gelbooru HTML, Moebooru / dapi JSON), the JavaScript interpreter behind the 52prompts node (against inline fixtures, no network), the YuE2 helper logic, the MiniMax H3 wrapper (against a faked Ollama), the crop box clamping and - under `node`, when installed - the crop editor's drag geometry, and the anatomy filter's verdict parsing and Ollama client (against a mocked server) — is covered by unit tests (290+, no torch, ComfyUI or network needed):

```bash
python3 -m unittest discover -s tests -v
```

One extra suite checks that all 20 generators on the live site still run. It is skipped unless you ask for it, since it makes ~40 requests — and it is the check that catches the site changing its scripts (once, a new analytics snippet broke every generator):

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
  sources/moebooru.py   Moebooru JSON-API engine: yande.re, Konachan .com / .net
  sources/dapi.py       Gelbooru-0.2 dapi engine: Safebooru, Xbooru
  sources/__init__.py   name -> backend registry
prompts52/
  jsmini.py             tiny JS interpreter: tokenizer, parser, evaluator, document shim
  catalog.py            the 20 generators: label -> page slug + which widgets it reads
  runner.py             script discovery, run, HTML -> text
  fetch.py              urllib GET, per-host throttle, in-memory TTL cache
  nodes.py              LoadRandom52Prompt
  routes.py             /random_prompts52/pick, /generators
smartload/
  selection.py          pure logic: clamp_box() (crop inside the image), aspect-lock / snap choices
  nodes.py              SmartLoadImage: input-folder file, EXIF transpose, crop per frame, IMAGE/MASK/width/height
anatomy/
  selection.py          pure logic: check catalogue, prompt, verdict parsing, pass/fail decision, report
  ollama.py             stdlib client for Ollama's /api/chat (vision question -> answer text)
  nodes.py              AnatomyDefectFilter: tensor -> JPEG, loop over the batch, split, empty-branch handling
minimaxh3prompt/
  h3kit.py              the prompt kit (stdlib only, also a CLI): shot plan, request builder, auto-fix, validator, Ollama client
  prompts/              the kit's system prompts (per variant), TESTS.md / README_ru.md next to it
  selection.py          pure logic: widget coercion/ranges, URL check, clip join/split, report text
  runner.py             kit call with options + error mapping (HTTP/timeout/unreachable -> H3Error)
  nodes.py              MiniMaxH3Prompt: saved-text-wins logic, IS_CHANGED, VALIDATE_INPUTS
  routes.py             POST /minimax_h3/generate (the Generate button)
yue2/
  selection.py          pure logic: artifact-file discovery, generate() kwargs assembly
  nodes.py              YuE2ModelLoader, YuE2Plan, YuE2Generate; pipeline cache, ABC/audio I/O
js/random_image.js      frontend: file dropdown, randomize button, drag & drop, preview
js/random_booru.js      frontend: 🎲/↧ buttons, preview, info line, last_post_id persistence
js/random_prompts52.js  frontend: 🎲/↧ buttons, per-generator widget show/hide, prompt display
js/smart_load_image.js  frontend: crop editor (draw/move/resize, aspect lock, snap grid), upload + drag & drop
js/minimax_h3.js        frontend: Generate/Regenerate button, stale-input hint, mode-dependent fields
__init__.py             registration of all node families, each import isolated (see CONTRIBUTING.md)
example_workflows/     one ready-to-load graph per node (listed by ComfyUI under Templates)
tests/                  unit tests (_pack.py imports pack submodules without torch)
ROADMAP.md              planned work: further booru sources, with probe results
```

## Known limitations

- Sequential/increment advancement is kept in the ComfyUI process's memory (resets on restart, then simply continues from the last value persisted in the workflow) and isn't synchronized across multiple parallel ComfyUI workers/processes, if you happen to run that (uncommon) setup.
- The booru node can only address the first 20034 positions of a Gelbooru search (yande.re / Konachan: up to 1,000,000; Safebooru / Xbooru: 200,100), and those positions shift as new posts are uploaded (see above).
- The 52prompts node depends on the shape of the site's generator scripts. They are hand-written and have been stable for years, but a rewrite that reaches outside the supported JavaScript subset would need `prompts52/jsmini.py` extended — it fails loudly with the offending construct when that happens.
- The YuE2 nodes have run end to end on Apple MPS (slow: ~13 min for a 98 s track) but not on CUDA, and not inside a ComfyUI graph with the real `yue2` package installed — see the YuE2 section.
- The anatomy filter has been run end to end in a real ComfyUI against a local Ollama (`qwen3-vl:8b`) on a few synthetic images — enough to show the routing, empty-branch modes and error paths work, not enough to say how well any model spots real six-fingered hands. Judgement quality depends entirely on the vision model you pick; calibrate on your own images.
