# comfyui-bart-nodes

Custom nodes for ComfyUI: smarter ways to **pick** an image (any folder, a touch-friendly gallery, a crop editor, booru boards), a few text and audio **generators**, and an Ollama-based **image filter**. Every node is named `Bart's ...` (search for "bart" to list them all) and sits under the **Bart's nodes** category, split into `Image`, `Text` and `Audio`.

## Nodes at a glance

| Node | Category | What it does | Needs |
| --- | --- | --- | --- |
| [**Bart's Load Random Image 🎲**](#load-random-image) | `Image` | loads an image from **any folder** on disk: by hand, at random, or the next one on every run | nothing beyond ComfyUI |
| [**Bart's Image Picker (input folder) 🖼️**](#image-picker) | `Image` | picks an image from ComfyUI's input folder through a **full-screen thumbnail gallery that works on touch screens** | nothing beyond ComfyUI |
| [**Bart's Smart Load Image (Crop) ✂️**](#smart-load-image) | `Image` | loads an image and lets you **crop it on the node**; only the selected part is output | nothing beyond ComfyUI |
| [**Bart's Load Random Booru Image 🎲**](#load-random-booru-image) | `Image` | pulls a post from a **booru tag search** (Gelbooru, yande.re, Konachan, Safebooru, Xbooru) | internet access |
| [**Bart's Anatomy Defect Filter (Ollama) 🔍**](#anatomy-defect-filter) | `Image` | splits images into `passed` / `failed` by asking an Ollama **vision model** about anatomy defects | an Ollama server with a vision chat model |
| [**Bart's Load Random Prompt (52prompts) 🎲**](#load-random-prompt-52prompts) | `Text` | outputs a random text prompt from one of 20 generators on [52prompts.com](https://52prompts.com/) | internet access |
| [**Bart's MiniMax H3 Prompt (Ollama) 🎬**](#minimax-h3-prompt) | `Text` | writes ready-to-use **MiniMax H3 video prompts** with a local LLM; a Generate button fills the result without running the graph | an Ollama server + a chat model |
| [**Bart's YuE2 Model Loader / Plan Score / Generate Song 🎵**](#yue2-music-generation) | `Audio` | generates a full song from style + lyrics with [m-a-p/YuE2-3B](https://huggingface.co/m-a-p/YuE2-3B), with an editable ABC score in between | the `yue2` wheel and a big GPU (24GB NVIDIA, or Apple silicon slowly) |

Every section below follows the same layout: a facts table, **Widgets**, **Outputs**, **How it works**, **Notes and limits**. The pack-wide parts are at the end: [Example workflows](#example-workflows), [Security](#security), [Tests](#tests), [Files](#files), [Known limitations](#known-limitations).

Conventions shared by the nodes: buttons (🎲, ✨, ⤢ ...) act **without executing the graph**; whatever a node last produced is shown in its preview and survives saving and reopening the workflow; seeds stay below 2⁵³ so the number shown is exactly the number used; every text widget can be turned into an input and linked.

## Install

**From an archive:** extract the `comfyui-bart-nodes` folder into `<ComfyUI>/custom_nodes/` and restart ComfyUI.

**With git:**

```bash
cd <ComfyUI>/custom_nodes
git clone <your_repo_URL> comfyui-bart-nodes
```

Update with `git pull` in that folder; restart ComfyUI after installing or updating.

Dependencies for the image nodes and the anatomy filter — `torch`, `Pillow`, `aiohttp`, `numpy` — already ship with ComfyUI. The booru, 52prompts and Ollama clients use the standard library (`urllib`), so they add nothing either. **YuE2 needs extra manual setup** (see its section), but a missing YuE2 dependency only disables the YuE2 nodes, not the rest of the pack: each node family's import is isolated in `__init__.py` (see `CONTRIBUTING.md`).

---

## Load Random Image

Loads an image from **any folder on disk** — chosen by hand, at random, or the next one in alphabetical order on every run.

| | |
| --- | --- |
| **Class · category** | `LoadRandomImage` · `Bart's nodes/Image` |
| **Example workflows** | [`01_load_random_image.json`](example_workflows/01_load_random_image.json), [`02_sequential_images.json`](example_workflows/02_sequential_images.json) |
| **Needs** | nothing beyond ComfyUI |
| **Network** | none (local files) |
| **HTTP routes** | `/random_image/list`, `/pick`, `/view`, `/input_dir` — the `dir` parameter is **unrestricted** (see [Security](#security)) |
| **Verified** | in a real ComfyUI, API and frontend: picks, dice, drag & drop, sequential stepping including batch counts above 1 |

### Widgets

| Widget | Meaning |
| --- | --- |
| `directory` | Absolute path to a folder of images (recursive; `.png .jpg .jpeg .webp .bmp .gif`). A counter under the preview shows how many files were found, refreshed whenever the directory changes. |
| filename dropdown | Pick a specific file from the list. |
| 🎲 **Randomize** | Button: picks a random file right now and updates the preview. |
| drag & drop | Drop an image on the node: it is uploaded through ComfyUI's own `/upload/image`, `directory` switches to the managed input folder and the file is selected (like the stock Load Image). |
| `randomize_on_queue` | A random pick on **every** Queue Prompt (server-side, not just via the button). Whatever is shown is ignored when this runs, so the preview hides itself while this is checked. |
| `sequential_on_queue` | The next file in alphabetical order on every Queue Prompt, wrapping after the last. The shown file **is** what the next run outputs, so the preview stays visible. |

The two checkboxes are mutually exclusive in the UI, and the server also rejects the queue if both are on (a hand-edited workflow.json can't get around it).

### Outputs

| Output | Type | Meaning |
| --- | --- | --- |
| `IMAGE` | `IMAGE` | The loaded image (animated files give all frames as a batch). |
| `MASK` | `MASK` | From the alpha channel, like the stock Load Image. |
| `filename` | `STRING` | The file that was actually loaded this run. |
| `directory` | `STRING` | The resolved absolute directory this run used. |

### How it works

**Sequential semantics.** A run outputs the file **currently** selected (the one already in the preview); the advance to the next happens **after**, preparing the start for the next run. The pointer lives in server memory per node `unique_id` + `directory`, together with the `filename` the previous run was given. That protects against the batch-queue race (several runs queued before the first finishes all carry the same stale `filename`; they follow the pointer instead of loading the same file repeatedly) while still honouring the widget: if `filename` differs from last time — you picked another file, rolled the dice, or reloaded a workflow — the file shown in the widget loads.

The preview shows what **actually** loaded on the last run (it survives saving and reopening the workflow), not what is queued next — except while `randomize_on_queue` is checked, where it is hidden.

### Notes and limits

- The advance state is in the ComfyUI process's memory: it resets on restart (then continues from the last value saved in the workflow) and isn't shared between parallel ComfyUI processes.
- For ComfyUI's own input folder with a touch-friendly picker use [Image Picker](#image-picker); for cropping use [Smart Load Image](#smart-load-image).

---

## Image Picker

A Load Image replacement for **phones and tablets**. On a touch screen the stock file dropdown opens on the finger-down and closes again on the finger-up, leaving only the ◀ ▶ arrows to step through files. This node opens a **full-screen gallery** instead.

| | |
| --- | --- |
| **Class · category** | `ImagePicker` · `Bart's nodes/Image` |
| **Example workflow** | [`11_image_picker.json`](example_workflows/11_image_picker.json) |
| **Needs** | nothing beyond ComfyUI |
| **Network** | none |
| **HTTP routes** | `/image_picker/list`, `/image_picker/thumb` — confined to the input folder |
| **Verified** | on a 375×812 touch-emulated viewport: layout, scrolling, tap-to-select, the early-tap guard, search, sort, sizes, a 300-file folder with chunked rendering, stepping, upload into a subfolder, running the node. **Not** on a physical phone or tablet: the emulator sends mouse-style clicks, so the real finger-up behaviour that breaks the stock dropdown was reasoned about and guarded against, not reproduced. |

### Widgets

| Widget | Meaning |
| --- | --- |
| **🖼 Choose image** (or tap the preview) | Opens the gallery. The button is an ordinary page button, not a canvas widget, and the gallery ignores taps in its first 350 ms, so the opening gesture can't select or dismiss anything. |
| the gallery | Thumbnails **with file names**, folders first. Native touch scrolling (momentum included; a scroll never counts as a tap). **Tap an image** to select it and close. Large 44 px controls, 16 px inputs (no iOS zoom on focus). |
| breadcrumbs | `🏠 input › folder › subfolder`: tap a segment to jump up; tap a 📁 to go into a subfolder (the stock node can't leave the top level). |
| search / sort | Filter by name; sort by name A→Z / Z→A (numbers sort naturally: `img2` before `img10`), newest or oldest first. |
| size | **S / M / L** buttons and a slider (90-400 px cells). Size and sort are remembered in the browser. |
| ◀ / ▶ | The previous / next file in the same folder, wrapping at the ends. |
| **＋ Upload** | In the gallery (into the folder being viewed) and on the node: pick files, or drop an image on the node. One uploaded file is selected right away. |

### Outputs

| Output | Type | Meaning |
| --- | --- | --- |
| `IMAGE` | `IMAGE` | The picked image (animated files give all frames as a batch; EXIF rotation applied). |
| `MASK` | `MASK` | From the alpha channel, like Load Image. |
| `filename` | `STRING` | The path inside the input folder, e.g. `trip/IMG_0042.jpg`. |
| `width`, `height` | `INT` | Size of the image. |

### How it works

The node stores the path in a hidden text widget (a normal dropdown would have to list every file and subfolder up front, and ComfyUI rejects values that aren't in it). The gallery gets its data from two routes: `list` (one folder level: subfolders, and image files with size and date) and `thumb` (a WebP thumbnail in one of five size buckets, 128-512 px, cached in ComfyUI's temp folder and keyed by path + modification time, so an edited file gets a fresh thumbnail). Big photos are decoded at reduced size; a file that can't be read shows a ⚠️ cell. The gallery is a shared module (`js/bart_image_gallery.js`), so other nodes can reuse it.

### Notes and limits

- Only the **input folder** (and its subfolders) is reachable. The routes refuse `..`, absolute paths and drive letters, and serve only image files. A symlinked collection placed *inside* the input folder works (as with the stock `/view`); the check is by path, not by where a symlink ends up.
- A folder listing is capped at 5000 files (the gallery says so; use search or subfolders).

---

## Smart Load Image

Like the stock Load Image, plus a **crop editor on the node**: pick a file, frame the part you want, and **only that part leaves the node**.

| | |
| --- | --- |
| **Class · category** | `SmartLoadImage` · `Bart's nodes/Image` |
| **Example workflow** | [`10_smart_load_image.json`](example_workflows/10_smart_load_image.json) |
| **Needs** | nothing beyond ComfyUI |
| **Network** | none |
| **HTTP routes** | none (the preview uses ComfyUI's own `/view`) |
| **Verified** | in a real ComfyUI: drawing, moving and resizing with the mouse (also with an aspect lock), numeric edits, save and reload, server-side crops checked pixel by pixel, a photo stored sideways with an EXIF orientation tag |

### Widgets

| Widget | Meaning |
| --- | --- |
| `image` + **📁 Upload image** | Files from ComfyUI's `input` folder. Upload a new one with the button or **drop an image on the node**: it is saved to `input` and selected. |
| the preview | **Drag on empty space** to draw a crop box, **drag inside** it to move it, **drag a handle** (corners and sides) to resize. The outside is dimmed, thirds guides are drawn, and the info line shows `900×600 → 471×337 at (163, 142) · 1.398`. |
| `crop_x`, `crop_y`, `crop_width`, `crop_height` | The crop in **pixels of the original image**. The editor writes them while you drag; you can also type them, or **link** them from other nodes. `crop_width` or `crop_height` of **0 = no crop** (the default). A box sticking out of the image is cut at its edge instead of failing, so a saved crop still works if the file is later replaced by a smaller one. |
| `aspect_lock` | `free`, `original`, `1:1`, `4:3`, `3:4`, `3:2`, `2:3`, `16:9`, `9:16`, `21:9`, `9:21`. While not `free`, drawing and resizing keep the ratio, and picking one reshapes the current box (shrinking it around its centre, never growing). |
| `snap_to` | `1`, `8`, `16`, `32`, `64`: width and height snap to multiples of it (handy for diffusion models). With a ratio lock and a grid the closest pair on the grid is chosen, so 16:9 on a 64 grid becomes 1024×576 when it fits and a near ratio like 896×512 when it doesn't. |
| **⤢ Full image** / **▣ Fit aspect** | Remove the crop / make the largest box of the chosen ratio, centred. |

### Outputs

| Output | Type | Meaning |
| --- | --- | --- |
| `IMAGE` | `IMAGE` | The **cropped part only** (animated files are cropped frame by frame with the same box). |
| `MASK` | `MASK` | From the alpha channel of the cropped part. |
| `width`, `height` | `INT` | Size of the cropped part. |
| `filename` | `STRING` | The file name. |

### How it works

The crop is stored as the four pixel widgets and applied on the server **after** EXIF rotation — the same way the browser shows the preview, so what you frame is what you get. The geometry of drawing, moving and resizing (with ratio lock and snap grid) lives in `js/smart_load_image.js` as plain functions and is unit-tested under `node`.

### Notes and limits

- Choosing a different file resets the crop to "no crop".
- The editor shows the crop widgets' own values. If you link a crop number from another node, the link wins when the graph runs, but the preview box keeps showing the widget's value.
- Files outside ComfyUI's `input` folder: use [Load Random Image](#load-random-image) (an arbitrary directory, no crop).

---

## Load Random Booru Image

Pulls a post from a **booru image board** by tag search — randomly, by position in the result list, or the next one on every run.

| | |
| --- | --- |
| **Class · category** | `LoadRandomBooruImage` · `Bart's nodes/Image` |
| **Example workflow** | [`03_random_booru.json`](example_workflows/03_random_booru.json) |
| **Needs** | internet access to the chosen board |
| **Network** | outbound requests to the board (it sees your server's IP and your tag queries), throttled to one per 0.6 s per host |
| **HTTP routes** | `/random_booru/pick`, `/count`, `/view`, `/sources` — they take a source name, tags and a position or post id, never a URL |
| **Verified** | in a real ComfyUI against the live sites: count, pick and view for every source; the deepest reachable position on Safebooru |

### Widgets

| Widget | Meaning |
| --- | --- |
| `source` | `gelbooru`, `yandere` ([yande.re](https://yande.re)), `konachan` / `konachan_net` ([konachan.com](https://konachan.com) and its safe-for-work mirror [konachan.net](https://konachan.net)), `safebooru` ([safebooru.org](https://safebooru.org)) or `xbooru` ([xbooru.com](https://xbooru.com), explicit). The list comes from the source registry, so adding a backend adds an entry. |
| `tags` | Space-separated tag query, exactly what you would type in the site's search box (`1girl blue_eyes rating:general`, `cat -comic`, `sort:score`). Empty = the whole site, newest first. |
| `random_post` | A random position in the result list on **every** Queue Prompt (server-side). |
| `increment_on_queue` | The next position on every Queue Prompt, wrapping at the end of the result list. |
| `index` | Position in the result list, 0-based, newest first: used when neither checkbox is on, and as the starting point for `increment_on_queue`. |
| 🎲 **Random** | Button: picks a random post right now, writes its position into `index` and shows it in the preview. |
| ↧ **Load index** | Button: fetches whatever position `index` currently holds into the preview (the spinner itself doesn't fetch: each step would be a request to a remote site). |
| preview | The last post actually loaded (or the last one a button fetched) plus an info line `#post_id · position / total · rating`. Proxied through ComfyUI, so the browser never talks to the board directly. |

Same mutual exclusion, advance-after-output timing and batch-race protection as [Load Random Image](#load-random-image); the pointer is keyed by `unique_id` + source + tags. `random_post` hides the preview (it is about to be discarded); `increment_on_queue` keeps it.

### Outputs

| Output | Type | Meaning |
| --- | --- | --- |
| `IMAGE` | `IMAGE` | The post's original image. |
| `MASK` | `MASK` | From the alpha channel. |
| `post_id` | `STRING` | The post id on the board. |
| `post_tags` | `STRING` | The post's own tag string. |
| `post_url` | `STRING` | Link to the post page. |
| `index` | `INT` | The position actually used this run. |

### How it works

**Content rating.** Gelbooru's "safe images only" switch is a per-account/session setting; anonymous requests already return every rating, and the node additionally sends the `fringeBenefits=yup` cookie (the site's legacy explicit-content opt-in). So **all ratings are always included** — filter with tags (`rating:general`, `-rating:explicit`, …) if you want less.

**Gelbooru** has no usable anonymous API (`index.php?page=dapi&s=post&q=index&json=1` answers 401 without an `api_key`/`user_id` pair), so the backend scrapes the ordinary search page:

- **Listing** — `index.php?page=post&s=list&tags=<query>&pid=<offset>`. `pid` is a *post offset*, not a page number, and a page holds exactly **42** thumbnails (`&limit=` is ignored). Position `i` lives on `pid = (i // 42) * 42`, at slot `i % 42`.
- **Total count** — taken from the paginator's "last page" link, then refined by fetching that last page and counting its thumbnails, so it is exact whenever the last page is reachable. Cached for 60 s per (source, tags).
- **File URL** — the listing only carries thumbnails, so the post page is fetched and the original file URL read out of it (`https://imgN.gelbooru.com/images/…`), falling back to the sample image.
- **Download** — `imgN.gelbooru.com` answers **302 → the post page** without a `Referer: https://gelbooru.com/`, i.e. hotlinking is blocked; the backend sends it. Downloaded files are cached on disk under ComfyUI's temp directory (`random_booru/`), keyed by a hash of the URL, so a preview and the following execution download once.

**yande.re and Konachan** run the Moebooru engine, which has a plain anonymous JSON API (one engine class `MoebooruSource`, one small subclass per site):

- **Listing** — `post.json?tags=<query>&limit=100&page=<n>`; position `i` is on page `i // 100 + 1`, slot `i % 100`.
- **Total count** — the `count` attribute in the header of `post.xml?tags=<query>&limit=1`, cached for 60 s. Capped at 1,000,000 positions; pages deeper than the query's real size come back empty.
- **File URL** — one extra `post.json?tags=id:<id>` request, the `file_url` field, which must be on the site's own domain or a subdomain (`files.yande.re`).
- **Ratings** — `rating:s` / `rating:q` / `rating:e` work as tags; `konachan_net` only ever has the safe ones.

**Safebooru and Xbooru** answer the old Gelbooru 0.2 `dapi` anonymously:

- **Listing** — `index.php?page=dapi&s=post&q=index&json=1&limit=100&pid=<page>&tags=<query>`; the API's `pid` is a page number, so position `i` is on page `i // 100`. An empty body means "no results".
- **Total count** — the `<posts count="N">` header of the same call without `json=1`.
- **File URL** — `&id=<id>` returns that one post; its `file_url` (or `images/<directory>/<image>`) must be on the site's own domain or a subdomain (`img.xbooru.com`).
- **Depth limit** — measured on both sites: answers up to an offset of **200,000** (`pid * limit`), refuses beyond with `API limited due to abuse`.

**Adding another booru.** `booru/sources/base.py` defines the interface (`Post` + `BooruSource`: `count()`, `page()`, `resolve_file_url()`); `gelbooru.py` implements it, `moebooru.py` and `dapi.py` are engine base classes (a new site on either only sets `name`, `origin` and `domain`), and `booru/sources/__init__.py` maps names to classes. Registering a module there makes it appear in the `source` combo with no node or frontend change. Planned and ruled-out sites, with reasons, are in [ROADMAP.md](ROADMAP.md).

### Notes and limits

- **Depth limit per source:** Gelbooru exposes at most **20034 positions** (`pid=19992` still returns 42 posts, `pid=20034` none); yande.re and Konachan up to 1,000,000; Safebooru and Xbooru 200,100. A random pick never goes past the limit. Narrow the search with tags to reach further into a big result set.
- **The result list is not stable:** positions are relative to the site's default order (newest first), so new uploads shift everything down. `index=5` means "the 6th newest match right now"; `post_id` is the permanent handle. Add `sort:id:asc` for an ordering that only grows at the end.
- **Non-image posts** (`.mp4`/`.webm`) can't be decoded: in random and increment mode the node skips to another position (a few attempts); in fixed mode, where you named an exact position, it raises an error naming the post.

---

## Anatomy Defect Filter

Splits an `IMAGE` (one picture or a batch) into **`passed`** and **`failed`** by asking an [Ollama](https://ollama.com) vision model whether each picture has the anatomy defects you selected — extra or missing limbs, wrong finger count, smeared hands, impossible poses. Wire `failed` into a Save Image node to keep the rejects separately, or leave it unconnected to throw them away.

| | |
| --- | --- |
| **Class · category** | `AnatomyDefectFilter` · `Bart's nodes/Image` |
| **Example workflow** | [`05_anatomy_filter.json`](example_workflows/05_anatomy_filter.json) |
| **Needs** | an Ollama server with a **chat-capable vision model** (`qwen3-vl`, `llama3.2-vision`, `gemma3`, `minicpm-v`, …). A pure embedding model can't answer "does this hand have six fingers": it only yields a vector. |
| **Network** | outbound to `ollama_url` only (`POST /api/chat`); the images leave the machine if that server is remote |
| **HTTP routes** | none (a frontend helper taking the URL from the browser would turn ComfyUI into an open proxy, which is why `model` is a plain text field) |
| **Verified** | in a real ComfyUI against a local Ollama (`qwen3-vl:8b`) on a few synthetic images: routing, empty-branch modes and error paths. **Not** how well any model spots real six-fingered hands. |

### Widgets

| Widget | Meaning |
| --- | --- |
| `ollama_url` | Base URL of the Ollama server, reachable **from the ComfyUI machine** (`http://host:11434`). |
| `model` | The vision model as Ollama knows it (`ollama list`). Plain text on purpose. |
| `extra_limbs`, `missing_limbs`, `bad_fingers`, `smeared_limbs`, `impossible_pose`, `face_deformation`, `merged_bodies` | Which defects to look for. At least one check (or a custom criterion) must be on. |
| `custom_criterion` | Your own defect in plain words (`a hand holding the cup has no thumb`), evaluated like the built-in ones. |
| `confidence_threshold` | The model rates each check 0-1; a *found* defect at or above this fails the image. Lower = stricter. |
| `max_side` | Longest side the image is downscaled to before sending (default 768). Bigger is slower and not always better; hands need enough pixels though. |
| `timeout`, `seed` | Per-request timeout; the request seed (temperature is always 0; the seed is capped at 2³¹−1 because Ollama reads it as a signed integer). |
| `num_ctx` | Context window requested from Ollama (default 4096: the checklist + one image + a short JSON answer). Pinned because Ollama otherwise sizes it from free memory: 22GB for one image on a 32GB machine, which made `qwen3-vl:8b` crawl at under 1 token/s. |
| `append_no_think` | Appends `/no_think` to the prompt (default on). Needed for qwen3-family models, ignored by others. |
| `empty_branch` | What a branch with zero images outputs: `blocker` or `placeholder`, see below. |

### Outputs

| Output | Type | Meaning |
| --- | --- | --- |
| `passed`, `failed` | `IMAGE` | The two halves of the batch. |
| `report` | `STRING` | One line per image: `#3 FAIL bad_fingers (0.85): six fingers on left hand`. |
| `report_json` | `STRING` | The same, machine-readable. |
| `passed_indices`, `failed_indices` | `STRING` | Comma-separated positions in the input batch (`0,2,5`), to put filtered images back in order. |

The text outputs are always produced, even when a branch has no images.

### How it works

**Mixed batches.** With 10 images of which 2 are bad, `passed` is a batch of 8 and `failed` a batch of 2: both ordinary outputs. `empty_branch` only matters when one side ends up with *no* images (all 10 passed, or you feed one image per queue):

- `blocker` — the empty output is a ComfyUI `ExecutionBlocker`: every node that depends on it silently doesn't run (a Save Image on `failed` simply does nothing when nothing failed). The catch: *all* nodes fed by that output are skipped, not just the Save.
- `placeholder` — the empty output is a single black image the size of the input, so downstream nodes always run. Filter it out yourself if you don't want it saved.

**How a verdict is made.** Each image gets one request: a checklist prompt (each line is a *problem*; `found: true` means it is present in this image — a custom criterion read as an expectation once inverted the verdict), the image as a base64 JPEG, `format: json`, temperature 0, at most 1024 answer tokens. The answer is parsed tolerantly (code fences, checks nested or top-level); a check the model omits counts as not found, a found defect with no confidence counts as fully confident, and a confidence in percent (`85`) is read as 0.85. An unparsable answer is retried once with a different seed, then the run **fails with an error**: it never quietly marks an image as failed or passed. If Ollama is unreachable or the model is missing, the run also errors with the reason.

Thinking-capable models (the default `qwen3-vl` tag is one) are handled: the request sends `think: false`, and because qwen3-family models ignore that and still burn their token budget thinking, `append_no_think` adds the `/no_think` soft switch. If an answer still comes back empty the error says so.

### Notes and limits

- **Expect imperfect judgement.** Small vision models (7-8B) are unreliable at counting fingers and spotting subtle distortions, in both directions. Try the filter on ~20 images you've already judged by hand and tune `confidence_threshold` and the model before filtering anything in bulk.
- Results for identical inputs and settings are cached by ComfyUI, so re-queuing an unchanged graph doesn't ask the model again.

---

## Load Random Prompt (52prompts)

Outputs a random **text prompt** from one of the generators in 52prompts.com's *Generators* menu — writing prompts, scenarios, character sheets, locations, hobbies, zodiac rolls — as a `STRING` you can wire straight into a CLIP Text Encode.

| | |
| --- | --- |
| **Class · category** | `LoadRandom52Prompt` · `Bart's nodes/Text` |
| **Example workflow** | [`04_random_prompt_52prompts.json`](example_workflows/04_random_prompt_52prompts.json) |
| **Needs** | internet access to 52prompts.com |
| **Network** | outbound to the site and its CDN (it sees your server's IP); one request per 0.4 s per host, pages and scripts cached in memory for an hour |
| **HTTP routes** | `/random_prompts52/pick`, `/generators` — a generator **label** from a fixed table, never a URL |
| **Verified** | in a real ComfyUI; a live suite (`PROMPTS52_LIVE=1`) checks that all 20 generators on the site still run |

### Widgets

| Widget | Meaning |
| --- | --- |
| `generator` | Which generator: a dropdown of all 20, named after the site's menu entries (`Prompts`, `Scenarios - Two Person`, `Teen Characters`, `Monster Characters`, `Mermaids`, `Zodiac Signs`, …). |
| `randomize` | A fresh prompt on **every** Queue Prompt. The seed that produced it is written back into `seed`, so a result worth keeping can be reproduced by turning this off. |
| `seed` | Used when `randomize` is off: the same seed + generator + inputs gives the same prompt for as long as the site's word lists stay put. Up to 2⁵³−1, the largest integer a JS number holds exactly, so the seed shown after a randomized run is the one that really made the prompt. |
| `input_1` … `input_3`, `choice_list` | Shown only for generators that ask for something: the scenario generators take character names (blank = the generator's own placeholder), the cast one a list of names, `Objects` / `Random Choice` a count. The frontend hides and relabels them per generator. |
| 🎲 **Generate** | Button: picks a prompt right now with a fresh seed. |
| ↧ **Load seed** | Button: the same for whatever `seed` holds. |
| preview | The prompt this node last output (persisted with the workflow) plus an info line with the generator and seed. |

### Outputs

| Output | Type | Meaning |
| --- | --- | --- |
| `prompt` | `STRING` | Plain text, multi-line for the character-sheet style generators. |
| `generator` | `STRING` | The generator that was used. |
| `seed` | `INT` | The seed that actually produced this prompt. |

### How it works

Each generator on the site is a standalone `.js` file on the site's CDN holding that generator's word lists **and** the string templating that turns them into a finished prompt. The sentence shapes only exist in the code, so scraping the arrays alone would get half the data: this node runs the file instead.

- **Discovery** — the generator page is fetched and the script URL read out of it (the CDN stamps a version into the path, so it changes over time). Only URLs on the site's CDN host are accepted.
- **Execution** — `prompts52/jsmini.py` is a small JavaScript interpreter covering exactly the subset those 20 files use: `var`/`if`/`for`, string concatenation, array literals, a handful of `String`/`Array`/`Math` methods, `typeof`, object literals, and a `document` shim that feeds the node's widgets in as form fields. Anything outside that subset raises an error naming the construct rather than producing nonsense, so if the site rewrites a generator you get a message instead of a garbled prompt. `Math.random` is wired to a seeded RNG, which is where reproducibility comes from.
- **No prompt data is stored in this repo.** The word lists are the site's content, fetched at run time like the booru node fetches images. The output HTML (`<br>` between character-sheet fields, the odd `<i>`) is flattened to text.

### Notes and limits

- `Random Choice` shuffles **your own** list (`choice_list`); it has no word list of its own and is included because it is in the site's menu.
- Generators are versioned by the site, not by this pack: a seed reproduces a prompt only while the underlying word list is unchanged.
- The node depends on the shape of the site's scripts. They have been stable for years, but a rewrite outside the supported JavaScript subset needs `jsmini.py` extended; it fails loudly with the offending construct.

---

## MiniMax H3 Prompt

Turns a short request ("an old fisherman hauls a net at dawn, gulls circling the boat") into a finished prompt for the **MiniMax H3** video model, using a local Ollama model, and hands the video node its duration, size and seed too.

| | |
| --- | --- |
| **Class · category** | `MiniMaxH3Prompt` · `Bart's nodes/Text` |
| **Example workflow** | [`09_minimax_h3_prompt.json`](example_workflows/09_minimax_h3_prompt.json) |
| **Needs** | an Ollama server + a chat model. Tested: `qwen3:4b-instruct`, Qwen 3.6 / 3.8 class models with thinking off (200-400 tokens per answer). For the very smallest models (1-2B) try `variant = slots`. |
| **Network** | outbound to `ollama_url` only (`POST /api/chat`) |
| **HTTP routes** | `POST /minimax_h3/generate` — the Generate button; takes the widget values, including `ollama_url`, from the caller (see [Security](#security)) |
| **Verified** | the whole pipeline against a real Ollama — `qwen3:4b-instruct` (4 GB, 4-10 s per prompt, validator OK on the first attempt, a different take per seed, `story` with 3 clips) and Qwen3.8 27B (30-110 s) — and the button / saved text / generate-on-run / stale hint / mode-dependent fields / save-and-reload behaviour in a real ComfyUI frontend. **Not:** `variant = slots` on 1-4B models, and linking the outputs into the real MiniMax video nodes (their inputs were read from the node definitions only). |

The heavy lifting is the bundled **h3kit** ([minimaxh3prompt/](minimaxh3prompt/), docs in [README_ru.md](minimaxh3prompt/README_ru.md), test log in [TESTS.md](minimaxh3prompt/TESTS.md)): Python computes the shot plan, cut times, picture-binding line, trigger placement and dialogue blocks, the LLM only writes the scene, then Python auto-fixes the answer, validates it and retries with the concrete error list. The node is the ComfyUI wrapper around it.

### Widgets

| Widget | Meaning |
| --- | --- |
| `ollama_url`, `model` | The Ollama server (http/https) and a chat model. |
| `request` | What to film, in any language. |
| `duration`, `aspect`, `mode`, `variant`, `shots` | `duration` 4-120 s (over 15 s = `story`, see below); `mode` T2VA / I2VA / FL2VA / L2VA; `variant` `auto` picks `t2va` / `i2va` / `fl2va` / `talking` / `product` / `ref` / `story` from the inputs, or force one (`slots` is never picked automatically); `shots` 0 = automatic, 1-3 forces the count. |
| `triggers` | `style:retro_vhs, subject:sks_man, object:avr_bot, place:alps_road, plain_style_word`, each placed exactly once. |
| `dialogue`, `text` | Lines split by newline or ` \| `, optional `S2:` speaker and `[Spanish]` language prefix; `text` is on-screen text (the only thing that gets quotes). |
| `image` / `start` / `end` | Shown only for the modes that read them (I2VA first frame; FL2VA start + end; L2VA end). |
| `refs` | Ref2VA references, **one per line**: `image\|subject\|young woman in a green parka\|S1`, `video\|motion\|...`, `audio\|voice\|...`. They are text descriptions; the actual files go into H3 itself. Shown for `auto` / `ref`. |
| `seed` | Sampling seed. The button sets a new one on every press; for run-time generation `control after generate` behaves as usual. |
| `short_side` | Pixels of the frame's short side for the `width` / `height` outputs (256-4096, default 768). Both sides are rounded **down** to a multiple of 32, so 16:9 at 768 gives 1344×768, the H3 nodes' own default. Last in the widget list on purpose (saved workflows are positional). |
| `temperature`, `num_ctx`, `num_predict`, `retries`, `timeout`, `think` | Ollama options; `retries` = how often the kit re-asks with the validator's error list (0-5); `num_predict` 0 = the model's default. |
| `append_no_think` | Appends Qwen3's `/no_think` switch to the last user message. Keep it on for Qwen3-family models; turn it off for others if you see the literal text in their output. |
| ✨ **Generate** / 🔄 **Regenerate** | Button: runs the whole pipeline right now **without executing the graph** and fills `generated`. Every press picks a **new seed**, so Regenerate gives another take. It shows `⏳ Generating…` and ignores clicks until done; the info line shows the variant, clip count and validator result (or the error). |
| `generated` | The result. Saved with the workflow, **editable by hand**. |

### Outputs

New outputs are always appended, so existing links keep their slots.

| Output | Type | Meaning |
| --- | --- | --- |
| `prompt` | `STRING` list | One entry per clip: a single entry for everything except `story`. |
| `report` | `STRING` | Variant, clip count, validator result, warnings such as "too much dialogue for this duration". |
| `duration` | `INT` list | Seconds, one per clip (`story` clips get their own, about 10 s each; otherwise the `duration` widget). |
| `frames` | `INT` list | `duration × 24` (24 fps). The H3 nodes snap a length up to their 17k+5 frame grid themselves. |
| `width`, `height` | `INT` | From `aspect` + `short_side`; 9:16 at 512 gives 512×896. |
| `seed` | `INT` | The seed this run used. |

The list outputs make a video node fed by `prompt` + `duration` run once per clip with that clip's own length; `width`, `height` and `seed` are shared by all clips. Wire them into a video node's duration / size / seed inputs (for the Cloud and API H3 nodes, whose `aspect_ratio` is a dropdown, set it by hand: a `STRING` can't feed a dropdown).

### How it works

**Button, saved text, running the graph:**

| Situation | What happens |
| --- | --- |
| Run the graph, `generated` not empty | The saved text is output **as is**: nothing is sent to Ollama, hand edits included. This also holds when you changed the request after generating: the node never silently replaces text you may have edited; it shows `⚠ inputs changed since this text was generated` instead, and **Regenerate** redoes it. |
| Run the graph, `generated` empty | The run generates first (with the `seed` widget), outputs the result and writes it into `generated`, so the next run reuses it. |

**Linked inputs.** Any widget can be turned into an input and fed by a link (for example one shared `duration` for this node and the video node). The graph uses the linked value. The **Generate button** runs outside the graph, so it can only read a linked value from a Primitive-style source node (`Int`, `Primitive`, ...); if a widget is fed by a node whose output is computed when the graph runs, the button says so and does nothing. Unlink it or use a Primitive node.

**`story` (over 15 s).** A planner splits the video into clips of about 10 s, then each clip is written as its own prompt with the characters carried over and "end of clip N = start of clip N+1". In `generated` the clips are separated by `=== CLIP 2 (10 s) ===` marker lines (edit them freely; text before the first marker counts as a clip too); `prompt` outputs one string per clip.

### Notes and limits

- If the validator still finds problems after the retries, the best attempt is returned anyway and the problems are listed in `report`: a prompt that is 95% right is more useful to edit than an error.
- **Thinking models.** `qwen3-vl:8b` was tried: it ignores both `think: false` and `/no_think` with this kit's system prompt and spent its whole token budget reasoning (700 and even 3000 tokens, no answer). The node then reports an empty answer with a hint. Use a non-thinking instruct model, or a thinking model with a large `num_predict` and patience.
- **Interrupt.** ComfyUI's Interrupt doesn't cancel a generation already waiting on Ollama (a blocking HTTP call); it ends at the answer or at `timeout`.
- `minimaxh3prompt/h3kit.py` is the kit as delivered plus two small patches: `ollama_chat()` accepts `seed` and `no_think` (the CLI has `--seed` / `--no-think`), and the CLI parser setup is one statement per line (lint). A newer kit version can be dropped in and the patches re-applied.

---

## YuE2 Music Generation

Wraps [m-a-p/YuE2-3B](https://huggingface.co/m-a-p/YuE2-3B): style + lyrics in, a **full stereo song** out. Three nodes: a loader, a planner and a generator, with an editable ABC score between planning and rendering.

| | |
| --- | --- |
| **Class · category** | `YuE2ModelLoader`, `YuE2Plan`, `YuE2Generate` · `Bart's nodes/Audio` |
| **Example workflows** | [`06_yue2_text_to_song.json`](example_workflows/06_yue2_text_to_song.json), [`07_yue2_plan_edit_generate.json`](example_workflows/07_yue2_plan_edit_generate.json), [`08_yue2_cover_from_abc.json`](example_workflows/08_yue2_cover_from_abc.json) |
| **Needs** | the **`yue2` inference package** (not on PyPI; pins `torch==2.10.0`, `transformers==4.57.6`) and hardware: an official target of a **24GB NVIDIA GPU** (BF16, ~70 s for a 3.6-minute song on an RTX 4090), or Apple silicon (MPS), slowly |
| **Network** | only the one-time weight download from Hugging Face (7.3GB + a 0.5GB VAE) |
| **HTTP routes** | none |
| **Verified** | the wrapper against the `yue2` 0.1.5 source, and loader → plan → generate through the real package on Apple MPS (the `audio` output holds a 98 s stereo 48 kHz waveform; the plan is valid ABC at the requested tempo). **Not:** CUDA, and running inside a ComfyUI graph with the real package (the test harness imported the node functions in a standalone environment, because yue2's torch pin differs from a current ComfyUI's). |

### Widgets

| Node | Widget | Meaning |
| --- | --- | --- |
| Model Loader | `vae` | `YuE2-Vae` or `YuE2-Vae-legacy`. |
| Model Loader | `device` | Text, default `auto` = CUDA, else Apple MPS, else CPU (or name one: `cuda`, `mps`, `cpu`). The loaded pipeline is cached in memory keyed by `(vae, device)`: ComfyUI can re-execute a loader far more often than ~7GB of weights need reloading. |
| Plan Score, Generate Song | `style`, `lyrics`, `seed` | What to sing and how; the seed is capped at 2⁵³−1. |
| Generate Song | `cot` | Composition mode: `full` (plan melody and chords, then render; default, best quality), `melody` (melody-only planning; what the model card recommends for covers), `off` (render directly, no planning pass). |
| Generate Song | `abc` (optional) | An ABC score. Blank = fresh generation; filled = cover / agentic editing (below). `cot=off` can't be combined with a score; the node says so when the graph is queued. |
| Plan Score, Generate Song | `max_abc_tokens` (default and ceiling 4096) | Hard cap on the planning pass. |
| Generate Song | `max_semantic_tokens` (default and ceiling 9000) | Hard cap on the audio pass. Both caps bound worst-case time and memory, but a hit *truncates* the plan or audio mid-way instead of shortening it. |

### Outputs

| Node | Output | Type | Meaning |
| --- | --- | --- | --- |
| Model Loader | `pipeline` | `YUE2_PIPELINE` | Feeds the other two nodes. |
| Plan Score | `abc` | `STRING` | The editable ABC (ABC notation) score; no audio is rendered. |
| Generate Song | `audio` | `AUDIO` | Feed it into ComfyUI's own **Save Audio**. |
| Generate Song | `abc` | `STRING` | The score that produced this song. |

### How it works

yue2 has no separate cover/edit entry points: both are a `pipeline(...)` call with an `abc` score already filled in.

- **Fresh generation:** leave `abc` blank.
- **Cover:** get an ABC transcription of an existing recording from wherever (**not** included in this pack: "SheetSage2", the tool the model card mentions, could not be pinned to a real package or API), feed it into `abc` with `cot="melody"`.
- **Agentic editing:** `Plan Score` → revise the `abc` text (by hand, or via any agent/LLM node you wire up; that part is outside yue2) → `Generate Song` with the revised `abc` and `cot="full"` → take its `abc` output, revise again, repeat.

### Notes and limits

- **License.** The model weights are **CC BY-NC 4.0, non-commercial use only**. That constrains the weights you download, separately from this pack's MIT license on the node code. See `THIRD_PARTY_NOTICES.md` in the model repo.
- **Installing the package.** Download the wheel from the [model repo's file list](https://huggingface.co/m-a-p/YuE2-3B/tree/main) (`yue2_infer-0.1.5-py3-none-any.whl` at the time of writing) and `pip install` that file. If your ComfyUI has a different torch/transformers, that install will change them; consider a separate environment.
- **Weights** download automatically on first load into the Hugging Face hub cache (`~/.cache/huggingface` by default), not into ComfyUI's `models/` folder. If the download stalls on the `xet` backend, retry with `HF_HUB_DISABLE_XET=1`.
- **Making a shorter track.** The length comes from the plan and the plan from your lyrics: a few `[chorus]` lines give a ~1.5-minute track, a full verse + chorus + bridge a lot more (and a plan of 4000+ tokens). **Write less lyrics to get a shorter song.**
- **Apple silicon speed and memory.** About 13 tokens/s: a 98-second power-metal track took about **13 minutes** (2.6 min planning, ~10 min audio) and ~11GB. On MPS the eager decoding loop leaks allocator cache (driver memory grew from 8GB to 25GB over ~2000 tokens while live tensors stayed at 7.4GB, until macOS killed the process, even though Activity Monitor showed free memory; with a nearly full disk macOS can't grow swap either). The nodes release the cache every 32 tokens, which keeps it flat at ~8-11GB. Close other heavy apps anyway.
- CPU works in principle and is far slower still. This is local inference, not a network call.

---

## Example workflows

`example_workflows/` holds a ready-to-load graph for every node, plus one with **all of them**. ComfyUI lists them itself under **Templates → comfyui-bart-nodes**, or drag a `.json` onto the canvas. Each has a Note explaining what to set; the image examples that read a folder ship with the placeholder `directory` `/path/to/your/images`, which you must point at a real folder before running.

| File | Shows |
| --- | --- |
| [`01_load_random_image.json`](example_workflows/01_load_random_image.json) | Load Random Image: manual pick / dice / drag & drop / `randomize_on_queue` |
| [`02_sequential_images.json`](example_workflows/02_sequential_images.json) | `sequential_on_queue`: one step per Queue, also with a batch count > 1 |
| [`03_random_booru.json`](example_workflows/03_random_booru.json) | Load Random Booru Image with a `rating:general` tag search |
| [`04_random_prompt_52prompts.json`](example_workflows/04_random_prompt_52prompts.json) | Load Random Prompt (52prompts) into a text preview |
| [`05_anatomy_filter.json`](example_workflows/05_anatomy_filter.json) | Directory loader → Anatomy Defect Filter → `passed` preview, `failed` saved to `output/rejected/`, report |
| [`06_yue2_text_to_song.json`](example_workflows/06_yue2_text_to_song.json) | YuE2 Model Loader → Generate Song → Save Audio |
| [`07_yue2_plan_edit_generate.json`](example_workflows/07_yue2_plan_edit_generate.json) | YuE2 plan → editable ABC score → generate (the agentic-editing loop) |
| [`08_yue2_cover_from_abc.json`](example_workflows/08_yue2_cover_from_abc.json) | YuE2 cover mode: an externally obtained ABC transcription + `cot=melody` |
| [`09_minimax_h3_prompt.json`](example_workflows/09_minimax_h3_prompt.json) | MiniMax H3 Prompt: request in, Generate button, prompt / report / duration / size previews |
| [`10_smart_load_image.json`](example_workflows/10_smart_load_image.json) | Smart Load Image: crop on the node, cropped preview + width / height |
| [`11_image_picker.json`](example_workflows/11_image_picker.json) | Image Picker: touch-friendly gallery, preview + width / height |
| [`12_all_nodes.json`](example_workflows/12_all_nodes.json) | **All nodes in one graph**, in four groups (below) |

**`12_all_nodes.json`** has four groups; they don't depend on each other, so mute or bypass the ones you don't need (select the group's nodes, `Ctrl+M` to mute, `Ctrl+B` to bypass):

1. **Pick images** — Load Random Image (muted until you set `directory`), Image Picker, Smart Load Image, Load Random Booru Image (Safebooru, `landscape`), each into a preview.
2. **Check anatomy** — Smart Load Image's cropped image → Anatomy Defect Filter → `passed` preview, `failed` saved to `output/rejected/`, report. Needs an Ollama vision model.
3. **Write a video prompt** — Load Random Prompt (52prompts) → the `request` of MiniMax H3 Prompt (a linked widget) → prompt, duration and size previews. Needs an Ollama chat model.
4. **Make music** — YuE2 Model Loader → Plan Score → Generate Song → Save Audio. **Bypassed by default**: it needs the `yue2` package and a big GPU. Un-bypass it (`Ctrl+B` again) once that is set up.

The examples were loaded back into a real ComfyUI frontend (01-05 and 09-12) and run from its Run button; 06-08 load fine but need the `yue2` package and a big GPU to execute.

---

## Security

| Node | Outbound requests | HTTP routes | Main exposure |
| --- | --- | --- | --- |
| Load Random Image | none | `/random_image/*` | **unrestricted `dir`**: arbitrary files readable by anyone who can reach the port |
| Image Picker | none | `/image_picker/list`, `/thumb` | confined to the input folder; image files only |
| Smart Load Image | none | none | — |
| Load Random Booru Image | the chosen booru | `/random_booru/*` | your IP and tag queries go to the board; unauthenticated fetch/cache filling |
| Anatomy Defect Filter | `ollama_url` | none | your images go to that server |
| Load Random Prompt (52prompts) | 52prompts.com + CDN | `/random_prompts52/*` | the site sees your IP |
| MiniMax H3 Prompt | `ollama_url` | `POST /minimax_h3/generate` | the route takes `ollama_url` from the caller |
| YuE2 nodes | Hugging Face (weights, once) | none | — |

**Directory node (Load Random Image).** The `/random_image/list`, `/pick` and `/view` routes accept a `dir` parameter with **no restriction whatsoever**: anyone who can reach ComfyUI's HTTP port (not necessarily through the graph or UI at all; a bare GET is enough) can list and read arbitrary files the ComfyUI process can access. This is a deliberate tradeoff for the node's core feature (loading from any folder), not a bug an allowlist should close.

**Image Picker.** Its routes take a subfolder and a file name relative to ComfyUI's input folder and refuse `..`, absolute paths and drive letters; only image files are listed or turned into thumbnails. The check is by path, not by realpath, so a symlinked collection inside the input folder works (as with the stock `/view`). Anyone reaching the port can read the images in the input folder and make the server generate thumbnails (cached in the temp folder).

**Booru node.** It makes **outbound requests to a third-party image board** from the ComfyUI host, and any prompt containing it does so on execution. The `/random_booru/*` routes take `source` + `tags` + `index`/`post_id`, never a raw URL. The file URL itself is read out of third-party responses (HTML for Gelbooru, JSON for the rest), so every candidate must be on the source's own domain or a subdomain (`gelbooru.com` / `imgN.gelbooru.com`, `yande.re` / `files.yande.re`, `xbooru.com` / `img.xbooru.com`, ...); a candidate on any other host is skipped, and `download()` re-checks the host right before the request goes out, so these endpoints can't be pointed at an arbitrary target (no SSRF). They are unauthenticated like everything else here: anyone reaching the port can make your server fetch booru pages and fill the temp cache. Downloaded content is arbitrary third-party imagery, entirely unfiltered by rating, and cached copies stay in ComfyUI's temp directory until it is cleaned.

**52prompts node.** Same outbound-request caveat: the site sees your server's IP, and `/random_prompts52/pick` is unauthenticated. It takes a generator **label** from a fixed table, never a URL, and the script URL it fetches must be on the site's CDN host, so there is no SSRF. The fetched script is **not** executed as JavaScript: `prompts52/jsmini.py` has no filesystem, network or `eval` surface at all; the worst a rewritten generator can do is raise an error or return odd text.

**MiniMax H3 prompt node.** It POSTs your request text to the workflow's `ollama_url` from the ComfyUI host, **plus one HTTP route**: `POST /minimax_h3/generate` takes the widget values, including `ollama_url`, from the caller, so anyone who can reach the port can make the server send a JSON POST to `/api/chat` on any http(s) host:port it can reach (loopback and LAN included) and read back the parsed prompt text or an error message. Mitigations: only http/https, a fixed path, a timeout, only the parsed `message.content` is returned (never a raw response), every other value is range-checked. If the port is reachable by people you don't trust, don't leave this node installed.

**Anatomy filter.** It sends your images to whatever `ollama_url` the workflow says, from the ComfyUI host: images leave the machine if that server is remote, and a workflow someone else wrote can point it at any host:port reachable from yours (it only ever POSTs to `/api/chat`). The node adds **no HTTP routes**: a frontend helper taking the URL from the browser would turn ComfyUI into an open proxy, which is why `model` is a plain text field.

**If ComfyUI is exposed on a LAN or the internet** (not just `127.0.0.1`), restrict access at the network level (VPN, an authenticating reverse proxy, firewall) rather than assuming ComfyUI or these nodes restrict anything: ComfyUI itself ships with no authentication on any of its endpoints by default.

## Tests

The pure logic is covered by unit tests (310+, no torch, ComfyUI or network needed): file selection, booru position selection and the backends' parsers (Gelbooru HTML, Moebooru / dapi JSON), the 52prompts JavaScript interpreter (against inline fixtures), the YuE2 helpers, the MiniMax H3 wrapper (against a faked Ollama), the Image Picker's path safety / folder listing / thumbnail naming, the crop box clamping and, under `node` when installed, the crop editor's drag geometry, and the anatomy filter's verdict parsing and Ollama client (against a mocked server).

```bash
python3 -m unittest discover -s tests -v
```

One extra suite checks that all 20 generators on the live site still run. It is skipped unless you ask for it, since it makes ~40 requests; it is the check that catches the site changing its scripts (once, a new analytics snippet broke every generator):

```bash
PROMPTS52_LIVE=1 python3 -m unittest tests.test_prompts52_live -v
```

The nodes themselves, their routes and the frontend widgets are checked by hand in a real ComfyUI (see each node's **Verified** row).

## Files

```
__init__.py              registration of all node families, each import isolated (see CONTRIBUTING.md)
selection.py, nodes.py, routes.py
                         Load Random Image: file selection (list_images, resolve_filenames), the node, /random_image/*
booru/                   Load Random Booru Image
  selection.py           pure position logic: resolve_index() (random / fixed / increment)
  pick.py                position -> post -> local file, incl. retry on non-image posts
  fetch.py               urllib GET with UA/cookie/referer, per-host throttle, disk cache
  nodes.py, routes.py    the node; /random_booru/pick, /count, /view, /sources
  sources/base.py        Post dataclass, BooruSource interface, url_on_domain()
  sources/gelbooru.py    Gelbooru scraper: listing / count / post-page parsing
  sources/moebooru.py    Moebooru JSON-API engine: yande.re, Konachan .com / .net
  sources/dapi.py        Gelbooru-0.2 dapi engine: Safebooru, Xbooru
  sources/__init__.py    name -> backend registry
imagepicker/             Image Picker
  selection.py           pure logic: safe subfolder/filename cleaning, folder listing, thumbnail buckets + cache names
  nodes.py, routes.py    the node; /image_picker/list, /image_picker/thumb (cached WebP thumbnails)
smartload/               Smart Load Image
  selection.py           pure logic: clamp_box(), aspect-lock / snap choices
  nodes.py               the node: input-folder file, EXIF transpose, crop per frame
anatomy/                 Anatomy Defect Filter
  selection.py           pure logic: check catalogue, prompt, verdict parsing, pass/fail decision, report
  ollama.py              stdlib client for Ollama's /api/chat (vision question -> answer text)
  nodes.py               the node: tensor -> JPEG, loop over the batch, split, empty-branch handling
prompts52/               Load Random Prompt (52prompts)
  jsmini.py              tiny JS interpreter: tokenizer, parser, evaluator, document shim
  catalog.py             the 20 generators: label -> page slug + which widgets it reads
  runner.py, fetch.py    script discovery, run, HTML -> text; urllib GET with throttle + TTL cache
  nodes.py, routes.py    the node; /random_prompts52/pick, /generators
minimaxh3prompt/         MiniMax H3 Prompt
  h3kit.py               the prompt kit (stdlib only, also a CLI): shot plan, request builder, auto-fix, validator, Ollama client
  prompts/, README_ru.md, TESTS.md
                         the kit's system prompts (per variant), its docs and test log
  selection.py           pure logic: widget coercion/ranges, URL check, clip join/split, frame size, report text
  runner.py              kit call with options + error mapping (HTTP/timeout/unreachable -> H3Error)
  nodes.py, routes.py    the node (saved-text-wins logic, outputs); POST /minimax_h3/generate
yue2/                    YuE2 nodes
  selection.py           pure logic: VAE choices, generate() kwargs, token budgets
  nodes.py               YuE2ModelLoader, YuE2Plan, YuE2Generate; pipeline cache, ABC/audio I/O
js/                      frontend, one file per node (WEB_DIRECTORY)
  random_image.js        file dropdown, randomize button, drag & drop, preview
  image_picker.js        Image Picker UI: preview, Choose / ◀ ▶ / Upload buttons
  bart_image_gallery.js  the shared full-screen touch gallery (no extension of its own)
  smart_load_image.js    crop editor: draw / move / resize, aspect lock, snap grid, upload + drag & drop
  random_booru.js        🎲/↧ buttons, preview, info line, last_post_id persistence
  random_prompts52.js    🎲/↧ buttons, per-generator widget show/hide, prompt display
  minimax_h3.js          Generate/Regenerate button, stale-input hint, mode-dependent fields
example_workflows/       one ready-to-load graph per node + 12_all_nodes (listed by ComfyUI under Templates)
tests/                   unit tests (_pack.py imports pack submodules without torch)
ROADMAP.md               planned work: further booru sources, with probe results
CONTRIBUTING.md          how to add a node sub-package, and the documentation template
```

## Known limitations

- Load Random Image and the booru nodes keep their advance state in the ComfyUI process's memory (it resets on restart, then continues from the last value saved in the workflow) and don't share it between parallel ComfyUI processes.
- The booru node can only address a limited number of positions per source (see its section), and those positions shift as new posts are uploaded.
- The 52prompts node depends on the shape of the site's generator scripts; a rewrite outside the supported JavaScript subset needs `prompts52/jsmini.py` extended (it fails loudly).
- The YuE2 nodes have run end to end on Apple MPS (slow: ~13 min for a 98 s track) but not on CUDA, and not inside a ComfyUI graph with the real `yue2` package installed.
- The anatomy filter's judgement quality depends entirely on the vision model you pick; it has been exercised on a few synthetic images only. Calibrate on your own.
- Image Picker has not been tried on a physical touch device (see its **Verified** row).
- MiniMax H3 Prompt: Interrupt doesn't cancel a request already waiting on Ollama; its outputs have not been wired into the real MiniMax video nodes.
