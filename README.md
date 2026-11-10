# comfyui-bart-nodes

Custom nodes for ComfyUI: smarter ways to **pick** an image (any folder, a touch-friendly gallery, a crop editor, booru boards), a few text and audio **generators**, and an Ollama-based **image filter**. Every node is named `Bart's ...` (search for "bart" to list them all) and sits under the **Bart's nodes** category, split into `Image`, `Text`, `Latent` and `Audio`.

## Nodes at a glance

| Node | Category | What it does | Needs |
| --- | --- | --- | --- |
| [**Bart's Load Random Image 🎲**](#load-random-image) | `Image` | loads an image from **any folder** on disk: by hand, at random, or the next one on every run | nothing beyond ComfyUI |
| [**Bart's Image Picker (input folder) 🖼️**](#image-picker) | `Image` | picks an image from ComfyUI's input folder through a **full-screen thumbnail gallery that works on touch screens**; also a **seeded random** or **sequential** pick from a folder | nothing beyond ComfyUI |
| [**Bart's Smart Load Image (Crop) ✂️**](#smart-load-image) | `Image` | loads an image and lets you **crop it on the node**; only the selected part is output | nothing beyond ComfyUI |
| [**Bart's Format Detector 📐**](#format-detector) | `Image` | picks a **video format** (from a list, or the one nearest to an image), gives **width and height** for a number of megapixels, and crops the image to fill the frame around its centre | nothing beyond ComfyUI |
| [**Bart's Load Random Booru Image 🎲**](#load-random-booru-image) | `Image` | pulls a post from a **booru tag search** (Gelbooru, yande.re, Konachan, Safebooru, Xbooru) | internet access |
| [**Bart's Anatomy Defect Filter (Ollama) 🔍**](#anatomy-defect-filter) | `Image` | splits images into `passed` / `failed` by asking an Ollama **vision model** about anatomy defects | an Ollama server with a vision chat model |
| [**Bart's Load Random Prompt (52prompts) 🎲**](#load-random-prompt-52prompts) | `Text` | outputs a random text prompt from one of 20 generators on [52prompts.com](https://52prompts.com/) | internet access |
| [**Bart's MiniMax H3 Prompt Helper (Ollama/Clip) 🎬**](#minimax-h3-prompt) | `Text` | writes ready-to-use **MiniMax H3 video prompts** with a local LLM (Ollama, or a text-LLM CLIP inside ComfyUI); a Generate button fills the result without running the graph | an Ollama server + a chat model, or a Qwen / Gemma CLIP |
| [**Bart's Easy Ollama 🦙**](#easy-ollama) | `Text` | the plainest **Ollama call**: address, model, prompt, optional images, a JSON of options in; the answer and a debug text out | an Ollama server (a vision model for images) |
| [**Bart's Simple concatenate 🔗**](#simple-concatenate) | `Text` | joins **any number of inputs** (text, numbers, ...) into one text; a new input appears as the last one is connected; the separator is the only setting | a ComfyUI with dynamic inputs |
| [**Bart's Lora Selector 🎛️**](#lora-selector) | `Model` | **several LoRAs on one node**, each with a switch and a strength, chosen on a screen that shows trigger words, model family and recommended settings, with filter and search | nothing beyond ComfyUI |
| [**Bart's Model Selector 🧩**](#model-selector) | `Model` | loads **any model file** (checkpoint, diffusion model, text encoder, VAE, CLIP vision; safetensors, ckpt, GGUF) from **whichever model folder** it lies in, chosen on a screen with **filters and the file's characteristics**; gives model, clip, vae, clip_vision as the file holds them, and the name | nothing beyond ComfyUI (GGUF needs a GGUF loader pack) |
| [**Bart's WAN Latent Trim Start 🎞️**](#wan-latent-trim-start) | `Latent` | cuts frames off the **start** of a WAN video latent **before the VAE decode**; the count is in pixel frames | nothing beyond ComfyUI |
| [**Bart's YuE2 Model Loader / Plan Score / Generate Song 🎵**](#yue2-music-generation) | `Audio` | generates a full song from style + lyrics with [m-a-p/YuE2-3B](https://huggingface.co/m-a-p/YuE2-3B), with an editable ABC score in between | the `yue2` wheel and a big GPU (24GB NVIDIA, or Apple silicon slowly) |
| [**Bart's VoxCPM Model Loader / Speak (TTS / voice clone) 🗣️**](#voxcpm-speech) | `Audio` | speaks a text with [OpenBMB VoxCPM](https://github.com/OpenBMB/VoxCPM): plain, in a **voice described in words**, or **cloned from a recording** | the `voxcpm` package and a GPU (or a lot of patience) |

Every section below follows the same layout: a facts table, **Widgets**, **Outputs**, **How it works**, **Notes and limits**. The pack-wide parts are at the end: [Example workflows](#example-workflows), [Security](#security), [Tests](#tests), [Files](#files), [Known limitations](#known-limitations).

Conventions shared by the nodes: buttons (🎲, ✨, ⤢ ...) act **without executing the graph**; whatever a node last produced is shown in its preview and survives saving and reopening the workflow; seeds stay below 2⁵³ so the number shown is exactly the number used; every text widget can be turned into an input and linked.

The four image loaders (Load Random Image, Image Picker, Smart Load Image, Load Random Booru Image) decode files the same way: a truncated or partly downloaded file loads as far as it goes instead of stopping the run, 16-bit grayscale (a depth map) is scaled to 8 bits instead of being clipped to white, a palette image's transparency (GIF, PNG8) reaches `MASK`, EXIF rotation is applied, and an animation becomes a batch of its frames (frames of another size than the first are dropped).

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

The frontend adds a hidden `edit_serial` that it renews whenever **you** change the file by hand (dropdown, 🎲, upload). With a serial present the rule gets simpler and stricter: the same serial as the previous run means no hand edit in between, so the pointer is followed whatever the widget says (a batch whose later items were serialized after the UI had already synced an earlier run's advance carries an in-between value that no comparison could recognise as stale); a new serial means a deliberate pick, which wins **even when it is the very file the previous run started with** - pick `a.png` again to repeat it. Callers that never send a serial (API scripts) keep the value-based rule.

The preview shows what **actually** loaded on the last run (it survives saving and reopening the workflow), not what is queued next — except while `randomize_on_queue` is checked, where it is hidden.

### Notes and limits

- The advance state is in the ComfyUI process's memory: it resets on restart (then continues from the last value saved in the workflow) and isn't shared between parallel ComfyUI processes.
- For ComfyUI's own input folder with a touch-friendly picker use [Image Picker](#image-picker); for cropping use [Smart Load Image](#smart-load-image).

---

## Image Picker

A Load Image replacement for **phones and tablets**. On a touch screen the stock file dropdown opens on the finger-down and closes again on the finger-up, leaving only the ◀ ▶ arrows to step through files. This node opens a **full-screen gallery** instead, and can also pick **at random (by seed)** or **the next file on every run** from a folder of the input folder.

| | |
| --- | --- |
| **Class · category** | `ImagePicker` · `Bart's nodes/Image` |
| **Example workflow** | [`11_image_picker.json`](example_workflows/11_image_picker.json) |
| **Needs** | nothing beyond ComfyUI |
| **Network** | none |
| **HTTP routes** | `/image_picker/list`, `/image_picker/pool`, `/image_picker/thumb` — confined to the input folder |
| **Verified** | the modes in a real ComfyUI (API and frontend): seeded random from a folder with and without subfolders (the previewed file is the file the run loads, also after the seed changed by itself), sequential stepping with a batch of 3 queued runs and with ◀ ▶ through a recursive pool, the gallery's **Use this folder**, save and reload, and an old workflow saved before the modes existed (loads as Fixed). On a 375×812 touch-emulated viewport (fixed mode): layout, scrolling, tap-to-select, the early-tap guard, search, sort, sizes, a 300-file folder with chunked rendering, stepping, upload into a subfolder, running the node. On a desktop viewport with a real mouse: a double-click on a folder (opens it once and selects nothing in the folder it lands in), Esc, an 81-megapixel image (⚠️ cell, HTTP 413), twelve parallel thumbnail requests for it, and revalidation answered with HTTP 304. **Not** on a physical phone or tablet: the emulator sends mouse-style clicks, so the real finger-up behaviour that breaks the stock dropdown was reasoned about and guarded against, not reproduced. |

### Widgets

| Widget | Meaning |
| --- | --- |
| **Fixed / 🎲 Random / ➡ Sequential** | Big segmented buttons (the node's `mode`). **Fixed**: the image shown. **Random**: a file of the pool chosen by the `seed`. **Sequential**: the file shown, then the next one of the pool on every run, wrapping after the last. |
| pool row (Random / Sequential) | `📁 trip/2024 · 312 images`: the folder the pool is made of (tap it to change it) and a **subfolders** checkbox (`include_subfolders`, off by default: only that folder; on: the whole tree below it). A pool starts at the folder of the image you had. |
| `seed` + `control after generate` | Shown in Random mode only. The preview shows **the file this seed selects, i.e. what the next run will load**; the usual `randomize` control gives a new one after every queued run, 🎲 sets a new seed right now, `fixed` repeats the same image. The same seed always gives the same file (for the same folder contents). |
| **🖼 Choose image** (or tap the preview) | Opens the gallery. The button is an ordinary page button, not a canvas widget, and the gallery ignores taps in its first 350 ms, so the opening gesture can't select or dismiss anything. |
| the gallery | Thumbnails **with file names**, folders first. Native touch scrolling (momentum included; a scroll never counts as a tap). **Tap an image** to select it and close. Large 44 px controls, 16 px inputs (no iOS zoom on focus). |
| breadcrumbs | `🏠 input › folder › subfolder`: tap a segment to jump up; tap a 📁 to go into a subfolder (the stock node can't leave the top level). |
| search / sort | Filter by name; sort by name A→Z / Z→A (numbers sort naturally: `img2` before `img10`), newest or oldest first. |
| size | **S / M / L** buttons and a slider (90-400 px cells). Size and sort are remembered in the browser. |
| ◀ / ▶ | The previous / next file in the same folder (Fixed) or in the whole pool (Sequential), wrapping at the ends. Hidden in Random mode. |
| **📁 Use this folder** | In the gallery of Random / Sequential mode: makes the folder you are looking at the pool. Tapping an image there selects it (the start of the sequence), and moves the pool to its folder if it is outside the current one. |
| **＋ Upload** | In the gallery (into the folder being viewed) and on the node: pick files, or drop an image on the node. Only image files are taken (PNG, JPEG, WebP, BMP, GIF); anything else is reported and skipped. One uploaded file is selected right away. |

### Outputs

| Output | Type | Meaning |
| --- | --- | --- |
| `IMAGE` | `IMAGE` | The picked image (animated files give all frames as a batch; EXIF rotation applied). |
| `MASK` | `MASK` | From the alpha channel, like Load Image. |
| `filename` | `STRING` | The path inside the input folder, e.g. `trip/IMG_0042.jpg`. |
| `width`, `height` | `INT` | Size of the image. |
| `folder` | `STRING` | The folder of the loaded image inside the input folder (`trip/2024`; empty for the input folder itself). |

### How it works

**Modes.** The mode, pool folder, `include_subfolders`, `seed` and a hidden `edit_serial` are widgets added after `image`, so workflows saved before them load as Fixed. Random picks `pool[hash(seed) mod N]` (a SHA-256 of the seed, so neighbouring seeds don't walk the list) from the pool sorted in natural order (`img2` before `img10`); the server and the preview use the same function, which is why the preview is exact. Sequential uses the same pointer logic as [Load Random Image](#load-random-image) (including `edit_serial`: batch counts above 1 and queued runs advance one by one, a hand pick wins, even of the file the last run started with), keyed by node and pool, and pushes the next file into the widget after each run. A run whose inputs are unchanged is cached by ComfyUI: Random with a fixed seed does not re-run downstream nodes, Sequential always runs. An empty or missing pool folder is an error naming it.

The node stores the path in a hidden text widget (a normal dropdown would have to list every file and subfolder up front, and ComfyUI rejects values that aren't in it). The gallery gets its data from two routes: `list` (one folder level: subfolders, and image files with size and date) and `thumb` (a WebP thumbnail in one of five size buckets, 128-512 px, cached in ComfyUI's temp folder and keyed by path + modification time; the browser revalidates them on every use (`Cache-Control: no-cache` plus an ETag, so an unchanged thumbnail costs an HTTP 304) and an edited file gets a fresh one at once). Big photos are decoded at reduced size; an image over **64 megapixels** is not decoded at all, and a file that can't be read shows a ⚠️ cell. At most **three thumbnails are generated at the same time**, however many the gallery asks for. The gallery is a shared module (`js/bart_image_gallery.js`), so other nodes can reuse it; opening it while another one is open replaces that one, and a double-tap can't select a second cell.

### Notes and limits

- Only the **input folder** (and its subfolders) is reachable. The routes refuse `..`, absolute paths, NUL bytes and (on Windows) drive letters, answer a name the file system itself refuses (too long, a symlink loop) with HTTP 400, and serve only image files. A symlinked collection placed *inside* the input folder works (as with the stock `/view`); the check is by path, not by where a symlink ends up.
- A pool is capped at 20,000 images (the first ones of a walk that visits folders alphabetically; the pool row shows `+`). Subfolders reached through a symbolic link are not followed in a recursive pool (a link back up could loop), the pool folder itself may be one.
- A folder listing is capped at 5000 images: the **first 5000 by name** are shown and the gallery says so (use search or subfolders for the rest).

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
| **Verified** | in a real ComfyUI: drawing, moving and resizing with the mouse (also with an aspect lock), numeric edits, save and reload, server-side crops checked pixel by pixel, a photo stored sideways with an EXIF orientation tag; edge cases with a real mouse: a plain click (leaves the crop alone), a handle dragged far outside the image (stops at the image edge) and past the opposite corner (collapses to the 8-pixel minimum, never NaN), a 16:9 lock on a 64 grid. **Not** with a finger or a pen: the touch handling (one pointer at a time, 32 px handle targets) is covered by reading the code and the geometry tests only. |

### Widgets

| Widget | Meaning |
| --- | --- |
| `image` + **📁 Upload image** | Files from ComfyUI's `input` folder. Upload a new one with the button or **drop an image on the node**: it is saved to `input` and selected. |
| the preview | **Drag on empty space** to draw a crop box, **drag inside** it to move it, **drag a handle** (corners and sides) to resize. A plain click changes nothing (only a drag of a few pixels does), a second finger is ignored while one is dragging, and every handle has a 32 px touch target around its small knob. The outside is dimmed, thirds guides are drawn, and the info line shows `900×600 → 471×337 at (163, 142) · 1.398`. |
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
- Upload takes image files only (PNG, JPEG, WebP, BMP, GIF); anything else is refused with a message under the preview.
- The editor shows the crop widgets' own values. If you link a crop number from another node, the link wins when the graph runs, but the preview box keeps showing the widget's value.
- Files outside ComfyUI's `input` folder: use [Load Random Image](#load-random-image) (an arbitrary directory, no crop).

---

## Format Detector

Picks a video format and the frame size for a number of megapixels, and cuts the image to fill that frame: **no bars, no stretching**. Made with MiniMax H3's canvas in mind (sides in multiples of 32, 1344 × 768 at its default size).

| | |
| --- | --- |
| **Class · category** | `FormatDetector` · `Bart's nodes/Image` |
| **Example workflow** | [`18_format_detector.json`](example_workflows/18_format_detector.json) |
| [`19_model_selector.json`](example_workflows/19_model_selector.json) | Model Selector: choose any model file on the picker screen, the file's name to a preview (choose a model before running) |
| **Needs** | nothing beyond ComfyUI |
| **Network** | none |
| **HTTP routes** | none |
| **Verified** | in a real ComfyUI through its API and frontend: auto, a chosen format, a custom ratio, the H3 limit with its note, bad input refused at queue time, a square picture cut to 16:9 (looked at: centred, round circles stay round, 1344 × 768), the example run. The arithmetic is unit-tested for every format at many sizes. |

### Widgets and inputs

| | Meaning |
| --- | --- |
| `image` (optional input) | The picture to fit. Every frame of a batch is cut and scaled the same way; without it the node only works out the size. |
| `format` | `auto` (default), or one of **16:9, 9:16, 4:3, 3:4, 1:1, 21:9, 9:21, 3:2, 2:3, 5:4, 4:5, 2:1, 1:2**, or `custom`. **auto** takes the format whose proportions are nearest to the image (nearest in the logarithm of the ratio, so 2:1 and 1:2 are equally far from a square); 16:9 when no image is connected. The six formats MiniMax H3 Prompt knows (16:9, 9:16, 1:1, 4:3, 3:4, 21:9) are all in the list. |
| `custom_ratio` | Used only with `format = custom`: `16:10`, `16/10`, `16x10` or a decimal such as `1.85` (between 1:20 and 20:1). |
| `megapixels` | The area of the frame, as a number (0.05 to 64). **1.03** (default) is H3's own canvas, 768 × 1344 pixels. |
| `limit_h3` | On by default: the frame stays within H3's 768 × 1344 pixels, so a larger `megapixels` is cut down to it (and `info` says so). Switch it off for other models. |
| `crop_image` | On by default. **Off: the image goes out unchanged** (the very same image, no cut and no scaling) and the node only works out `width`, `height` and the format (`auto` still looks at the image). `info` says that the image was passed on. |

### Outputs

| Output | Type | Meaning |
| --- | --- | --- |
| `width`, `height` | `INT` | The frame, **both sides multiples of 32** (what H3 needs). Of the pairs of multiples of 32 near the asked area, the one that keeps the format's proportions best is taken (16:9 at 1.03 MP is 1344 × 768, 9:16 is 768 × 1344, 1:1 is 1024 × 1024, or 992 × 992 under the limit). |
| `image` | `IMAGE` | With `crop_image` off, the input unchanged. Otherwise the input cut around its centre to the frame's proportions (the largest such part: only the surplus on the sides, or top and bottom, is removed, equally on both) and scaled to width × height with an anti-aliased bicubic. Nothing when no image was connected. |
| `aspect` | `STRING` | The format that was used, such as `16:9` (a custom ratio as `5:3`). |
| `ratio` | `FLOAT` | width / height of that format. |
| `info` | `STRING` | What was decided: the format and why, the size and its megapixels, how much of the image was cropped, and a note when the H3 limit changed the size. |

### Notes and limits

- The frame is a whole number of 32-pixel steps, so it is a hair off the exact format (1344 × 768 is 1.75:1, not 16:9 = 1.78:1). The image is cut to the **frame's** proportions, so a perfect 16:9 picture loses about 2 % at the sides rather than being squeezed. `info` shows the share that was cut.
- The cut is always at the **centre**: a head near the top of a tall picture can lose some of its top when it is fitted to a wide format. There is no crop offset yet.
- A small picture is scaled up (no sharpening is added); a batch is cut by the proportions of its own frames, which are the same within a batch.

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

**Downloads and the cache.** Every original is fetched with the site's own `Referer`, checked and only then cached under ComfyUI's temp folder (`random_booru/`, keyed by a hash of the URL), so a preview and the run after it download once, and a post that is already on disk is shown without asking the board anything (the post's file URL is remembered). A body that is shorter than the server's `Content-Length`, or does not start like an image (the HTML post page that hosts send when they reject a hotlink), is an error and is **not** cached - it would otherwise break that post until the temp folder was cleaned. The cache is capped at 512 MB: the least recently used files are deleted past that. Redirects are followed only within the site's own domain.

**Failed runs.** In `increment_on_queue` mode a run that fails on a flaky network (a timeout, HTTP 408/429/5xx, a cut-off transfer) does not use up its position: the next queue tries the same post. A post that is gone for good (HTTP 404, no file URL) still moves on, so the run can never get stuck on it. Gelbooru's search page without any thumbnail and without its "Nobody here but us chickens" notice (a block or maintenance page, a changed layout) is reported as an error, not as "no posts".

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
- **Execution** — `prompts52/jsmini.py` is a small JavaScript interpreter covering exactly the subset those 20 files use: `var`/`if`/`for`, string concatenation, array literals, a handful of `String`/`Array`/`Math` methods, `typeof`, object literals, and a `document` shim that feeds the node's widgets in as form fields. Anything outside that subset raises an error naming the construct rather than producing nonsense, so if the site rewrites a generator you get a message instead of a garbled prompt. `Math.random` is wired to a seeded RNG, which is where reproducibility comes from. A run is bounded: 1,000,000 loop iterations in total (nested loops included), arrays of at most 1,000,000 items and strings of at most 2,000,000 characters (checked before a concatenation, `join`, `concat` or `push` is carried out), so a broken or hostile script ends with an error instead of eating the machine's memory.
- **No prompt data is stored in this repo.** The word lists are the site's content, fetched at run time like the booru node fetches images. The output HTML (`<br>` between character-sheet fields, the odd `<i>`) is flattened to text.

### Notes and limits

- `Random Choice` shuffles **your own** list (`choice_list`); it has no word list of its own and is included because it is in the site's menu.
- Generators are versioned by the site, not by this pack: a seed reproduces a prompt only while the underlying word list is unchanged.
- The node depends on the shape of the site's scripts. They have been stable for years, but a rewrite outside the supported JavaScript subset needs `jsmini.py` extended; it fails loudly with the offending construct.

---

## MiniMax H3 Prompt

Turns a short request ("an old fisherman hauls a net at dawn, gulls circling the boat") into a finished prompt for the **MiniMax H3** video model, using a local Ollama model **or a text-LLM CLIP inside ComfyUI** (no Ollama needed), and hands the video node its duration, size and seed too.

| | |
| --- | --- |
| **Class · category** | `MiniMaxH3Prompt` · `Bart's nodes/Text` |
| **Example workflow** | [`09_minimax_h3_prompt.json`](example_workflows/09_minimax_h3_prompt.json) |
| **Needs** | **either** an Ollama server + a chat model, **or** a text-LLM encoder (a Qwen or Gemma model loaded with Load CLIP, the kind core's Generate Text node takes) on the `clip` input. Ollama tested: `qwen3:4b-instruct`, Qwen 3.6 / 3.8 class models with thinking off (200-400 tokens per answer). For the very smallest models (1-2B) try `variant = slots`. |
| **Network** | Ollama backend: outbound to `ollama_url` only (`POST /api/chat`). CLIP backend: none |
| **HTTP routes** | `POST /minimax_h3/generate` — the Generate button; takes the widget values, including `ollama_url`, from the caller as `application/json` (at most 256 KB, at most 4 generations at once; see [Security](#security)) |
| **Verified** | the whole pipeline against a real Ollama — `qwen3:4b-instruct` (4 GB, 4-10 s per prompt, validator OK on the first attempt, a different take per seed, `story` with 3 clips) and Qwen3.8 27B (30-110 s) — and the button / saved text / generate-on-run / stale hint / mode-dependent fields / save-and-reload behaviour in a real ComfyUI frontend, including a widget linked from a Primitive node, through a Reroute, and from a computing node. The route was fuzzed (wrong content type, oversized and deeply nested bodies, URLs with credentials / fragments / bad ports, infinities): every case is a clean 4xx. The CLIP backend: a graph run through a real ComfyUI with a stand-in CLIP object (`<think>` cut, Ollama fields ignored, `slots` refused at queue time, the button states in the frontend) **and with the real `qwen_3_4b.safetensors` text encoder (Load CLIP, type `lumina2`) on CPU**: a 6 s T2VA prompt, validator OK on the first attempt with `retries = 0`, ~1.4 tokens/s (about 11 minutes for a 900-token budget; a GPU is far faster). **Not:** a Gemma encoder, longer or `story` / `ref` prompts on the CLIP backend, `variant = slots` on 1-4B models, and linking the outputs into the real MiniMax video nodes (their inputs were read from the node definitions only). |

The heavy lifting is the bundled **h3kit** ([minimaxh3prompt/](minimaxh3prompt/), docs in [README_ru.md](minimaxh3prompt/README_ru.md), test log in [TESTS.md](minimaxh3prompt/TESTS.md)): Python computes the shot plan, cut times, picture-binding line, trigger placement and dialogue blocks, the LLM only writes the scene, then Python auto-fixes the answer, validates it and retries with the concrete error list. The node is the ComfyUI wrapper around it.

### Widgets

| Widget | Meaning |
| --- | --- |
| `ollama_url`, `model` | The Ollama server and a chat model. The URL is `http(s)://host[:port]`, optionally with a path prefix for a reverse proxy (`https://example.org/ollama`); no `?query`, `#fragment`, `;params` or `user:password@`. The node always posts to `<url>/api/chat`. |
| `request` | What to film, in any language. |
| `duration`, `aspect`, `mode`, `variant`, `shots` | `duration` 4-120 s (over 15 s = `story`, see below); `mode` T2VA / I2VA / FL2VA / L2VA; `variant` `auto` picks `t2va` / `i2va` / `fl2va` / `talking` / `product` / `ref` / `story` from the inputs, or force one (`slots` is never picked automatically); `shots` 0 = automatic, 1-3 forces the count. |
| `triggers` | `style:retro_vhs, subject:sks_man, object:avr_bot, place:alps_road, plain_style_word`, each placed exactly once. |
| `dialogue`, `text` | Lines split by newline or ` \| `, optional `S2:` speaker and `[Spanish]` language prefix; `text` is on-screen text (the only thing that gets quotes). |
| `image` / `start` / `end` | Shown only for the modes that read them (I2VA first frame; FL2VA start + end; L2VA end). |
| `clip` (input socket) | Optional. A text-LLM CLIP: when linked, the text is written by this encoder inside ComfyUI and **`ollama_url` / `model` are ignored** (and not validated). See *Backends* below. |
| `refs` | Ref2VA references, **one per line**: `image\|subject\|young woman in a green parka\|S1`, `video\|motion\|...`, `audio\|voice\|...`. They are text descriptions; the actual files go into H3 itself. Shown for `auto` / `ref`. |
| `seed` | Sampling seed. The button sets a new one on every press; for run-time generation `control after generate` behaves as usual. |
| `short_side` | Pixels of the frame's short side for the `width` / `height` outputs (256-4096, default 768). Both sides are rounded **down** to a multiple of 32, so 16:9 at 768 gives 1344×768, the H3 nodes' own default. Last in the widget list on purpose (saved workflows are positional). |
| `temperature`, `num_ctx`, `num_predict`, `retries`, `timeout`, `think` | Ollama options; `num_ctx` 4096-131072 (the kit's prompts are long, a smaller window would silently cut them); `retries` = how often the kit re-asks with the validator's error list (0-5); `num_predict` 0 = the model's default; `think` asks a thinking model to think (and then `/no_think` is not added, whatever `append_no_think` says). |
| `append_no_think` | Appends Qwen3's `/no_think` switch to the last user message, unless `think` is on. Keep it on for Qwen3-family models; turn it off for others if you see the literal text in their output. |
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

**Backends.** *Ollama* (default): the Generate button and graph runs call `ollama_url`. *CLIP*: link a CLIP from **Load CLIP** (loaded with a Qwen / Gemma text model) to the `clip` socket. The same kit runs on top (shot plan, auto-fix, validator, retries with the error list), but the model call goes to `clip.generate()`, like core's **Generate Text** node: `seed`, `temperature`, `think` and `num_predict` (0 = 2048 tokens) are passed on, the retry history is folded into the user prompt, and a `<think>` block is cut from the answer. Differences you will notice: a CLIP is an object of the running graph and cannot be sent to the server route, so **the button can't generate** with a CLIP linked (it reads `▶ Written when the graph runs`, or **🗑 Clear** when there is text: the text is emptied, a new seed is set, and the next run writes a new take); `variant = slots` needs Ollama's constrained JSON decoding and is refused; the `story` plan asks for JSON in the prompt instead of enforcing it, so a small model may need `retries`; `num_ctx`, `timeout` and `append_no_think` have no effect; and the Interrupt button works (it stops the encoder).

**Linked inputs.** Any widget can be turned into an input and fed by a link (for example one shared `duration` for this node and the video node). The graph uses the linked value. The **Generate button** runs outside the graph, so it can only read a linked value from a Primitive-style source node (the frontend's `Primitive`, or core's `Int` / `Float` / `String` / `Boolean` primitives), also when the link runs through **Reroute** nodes; if a widget is fed by a node whose output is computed when the graph runs (even one with a single widget of its own), the button says so and does nothing. Unlink it or use a Primitive node. A linked `seed` is sent as it is (the button can't change a value that comes over a link), so Regenerate then repeats the same take.

**`story` (over 15 s).** A planner splits the video into clips of about 10 s, then each clip is written as its own prompt with the characters carried over and "end of clip N = start of clip N+1". In `generated` the clips are separated by `=== CLIP 2 (10 s) ===` marker lines (edit them freely; text before the first marker counts as a clip too); `prompt` outputs one string per clip.

### Notes and limits

- If the validator still finds problems after the retries, the best attempt is returned anyway and the problems are listed in `report`: a prompt that is 95% right is more useful to edit than an error.
- **Thinking models.** `qwen3-vl:8b` was tried: it ignores both `think: false` and `/no_think` with this kit's system prompt and spent its whole token budget reasoning (700 and even 3000 tokens, no answer). The node then reports an empty answer with a hint. Use a non-thinking instruct model, or a thinking model with a large `num_predict` and patience.
- **Interrupt.** ComfyUI's Interrupt doesn't cancel a generation already waiting on Ollama (a blocking HTTP call); it ends at the answer or at `timeout`.
- **Empty answers.** When the model returns nothing usable (every raw answer blank), the run fails with "returned an empty answer" and a hint, for every variant (`i2va`, `fl2va`, `ref`, ... included), instead of handing back the kit's padded skeleton as if it were a prompt.
- `minimaxh3prompt/h3kit.py` is the kit as delivered plus a few small patches: `ollama_chat()` accepts `seed`, `no_think` (the CLI has `--seed` / `--no-think`) an `on_answer` callback (how the node sees the raw answers) and a `chat` argument (replaces `ollama_chat`, which is how the CLIP backend plugs in), does **not follow redirects**, and reads at most 16 MB of a response; the answer clean-up regular expressions are rewritten so a long, odd answer can't make them crawl (the originals were quadratic or worse), and an answer is cut at 200,000 characters before it is cleaned; the CLI parser setup is one statement per line (lint). A newer kit version can be dropped in and the patches re-applied.

---

## Easy Ollama

The plainest way to ask a local **Ollama** something, with or without images. Every setting is on the node, and every one can also be fed by a link.

| | |
| --- | --- |
| **Class · category** | `OllamaChat` · `Bart's nodes/Text` |
| **Example workflow** | [`15_easy_ollama.json`](example_workflows/15_easy_ollama.json) |
| **Needs** | an Ollama server; for images a vision model (tested: `qwen3-vl:2b-instruct`, 1.9 GB) |
| **Network** | outbound to `address` only (`POST /api/chat`, then a `GET /api/ps` for the debug text) |
| **HTTP routes** | none |
| **Verified** | against a real Ollama 0.40 and `qwen3-vl:2b-instruct`: three images through a real ComfyUI graph (Load Image ×3 → Batch Images → this node) with a `num_ctx` of 8192; six images (6520 prompt tokens, more than 6000) with `num_ctx` 8192; the same prompt with the context left unset, which made this server load the model with a context of 262144 and 33 GB. Requests with a `num_ctx` of 256 up to 1,000,000 are checked against a stand-in server to arrive exactly as written. **Not:** `num_ctx` above 8192 on a real model (the stand-in server proves the request is passed on, not that the machine can hold it), and remote or proxied servers. |

### Widgets

| Widget | Meaning |
| --- | --- |
| `address` | `localhost` (default), `192.168.1.5`, `myhost:11500` or a full `http(s)://host:port/prefix`. A bare host gets `http://` and Ollama's port 11434. No credentials, query or fragment. |
| `model` | The model name, as `ollama list` shows it. Required. |
| `prompt` | The text. Required. |
| `images` (optional input) | An `IMAGE`; **every frame of a batch is one image** for the model. For several pictures join them with **Batch Images** (it resizes the later ones to the first). Each is sent as a JPEG, scaled down to a long side of 2048 px first. |
| `settings` | A JSON object, **pre-filled with Ollama's defaults and `num_ctx: 8192`**. Anything in it is passed on as written: no range is checked, so any `num_ctx` works. Empty box = no options at all. |

The default `settings`:

```json
{
  "temperature": 0.8,
  "top_k": 40,
  "top_p": 0.9,
  "min_p": 0.0,
  "repeat_penalty": 1.1,
  "repeat_last_n": 64,
  "seed": -1,
  "num_predict": -1,
  "num_ctx": 8192
}
```

`seed: -1` is Ollama's real default, **random** (its documentation says 0, but 0 is a *fixed* seed there: tested, the same answer every time). A random seed, or none, makes the node run on every queue; a fixed one gives the same answer for the same prompt.

Keys that are not model options are lifted out of it: `think`, `keep_alive`, `format` and `system` go to the top level of the Ollama request, and `timeout` (seconds, default 900) and `image_max_side` (pixels, default 2048) steer the node. Everything else goes into Ollama's `options` (`seed`, `stop`, `num_batch`, ...).

### Outputs

| Output | Type | Meaning |
| --- | --- | --- |
| `text` | `STRING` | The model's answer (empty when something went wrong). |
| `debug` | `STRING` | What was sent (address, model, image sizes, request size, options), the HTTP status and time, why it stopped, the prompt and answer token counts, the model's reasoning if it has any, **the server's error message**, and what the server holds in memory (`context 8192 | 2.6 GB | 100% on GPU`). Wire it into **Preview Any**. |

### Notes and limits

- **Errors do not stop the graph.** An unreachable server, an unknown model or a refused request give an empty `text` and an `ERROR: ...` line in `debug`. Only an empty `model` or `prompt` and a settings box that is not valid JSON are refused when the graph is queued.
- **The context size matters.** Left unset, the server picks it: the test server loaded even this 1.7B model with a context of **262144** and took **33 GB** of memory (and then a long time). With `num_ctx: 8192` the same model took 2.6 GB and answered in 20 seconds. The debug text warns when the server chose a huge context by itself, and when the prompt filled the whole `num_ctx` (Ollama then silently cuts off its start). Each image costs roughly 1000 tokens at 768×512 with Qwen3-VL.
- **Re-running.** With a random seed (`-1`, the default, or none) every queue asks again; with a fixed `seed`, unchanged inputs reuse the previous answer (ComfyUI's cache), and a changed seed asks again.
- A redirect from the server is not followed, and a response over 64 MB is refused. Interrupt does not stop a request in progress.
- Not a chat: one prompt, one answer, no history.

---

## Lora Selector

Several LoRAs on **one node**: each row has an ON/OFF switch and a strength, and the LoRA is chosen on a **picker screen** that shows what is known about every file.

| | |
| --- | --- |
| **Class · category** | `LoraSelector` · `Bart's nodes/Model` |
| **Example workflow** | [`16_lora_selector.json`](example_workflows/16_lora_selector.json) |
| [`17_simple_concatenate.json`](example_workflows/17_simple_concatenate.json) | Simple concatenate: two texts and a number joined into one prompt |
| [`18_format_detector.json`](example_workflows/18_format_detector.json) | Format Detector: Load Image → the nearest video format → the cropped image, width, height and the info text |
| **Needs** | nothing beyond ComfyUI (LoRA files in its `loras` folders) |
| **Network** | none |
| **HTTP routes** | `/lora_selector/list`, `/info`, `/preview` (GET) and `/notes` (POST, JSON only) — only the files ComfyUI itself lists as LoRAs (see [Security](#security)) |
| **Verified** | in a real ComfyUI with sample LoRA files (their safetensors headers, Civitai and A1111 sidecar files and preview images): the picker screen (cards, previews, family chips, search by name, trigger word, frequent tag and your own notes, both together with a chip), the detail panel, adding rows (the next row appears, a recommended strength is taken over), ON/OFF, strength with a clamp to ±100, a CLIP strength field when a CLIP is connected, a missing file marked in red, dragging rows to reorder them (mouse and touch-style pointer events), the CLIP-strength fields following `apply_to_clip`, the run's warnings under the rows, save and reload, queue-time errors (missing file, bad strength, bad JSON), saving notes, and the layout on a 375 px phone viewport. The application is checked with **ComfyUI's real code** (`load_lora_for_models`, real LoRA files, a real `ModelPatcher` around a tiny stand-in network named like a Wan model: patched without any CLIP, the original model untouched, trigger words merged, the family warning raised) and in unit tests against stand-ins. **Not:** a real checkpoint (none was installed), and metadata from real downloaded files beyond the formats described below. |

### Widgets and inputs

| | Meaning |
| --- | --- |
| `model` (required input) | The diffusion model the LoRAs are applied to. |
| `clip` (optional input) | The CLIP model. Connect it to apply the LoRAs to it too and to get a **CLIP strength** field on every row (empty = the same as the model strength). **Without it the node works on the model alone** and the `clip` output is empty (it is meant for models that have no CLIP of their own to patch). |
| `apply_to_clip` | On by default. **Off = the LoRAs go to the model only and a connected CLIP passes through untouched**, which is what most Flux, Wan and other video LoRAs want (the CLIP strength fields are hidden then). If a LoRA cannot be applied to the CLIP at all (an error, not just keys that do not match), the model still gets it and the run says so. |
| the rows | **＋ Add LoRA…** opens the picker. A filled row has a **⋮⋮ handle (drag it to change the order**; mouse, finger or pen), a switch (**ON** / **OFF**), the LoRA's name (tap it to pick another), the strength, the CLIP strength (with a CLIP connected) and ✕ to remove it. **The next empty row appears as soon as the last one is filled.** A LoRA whose file is missing is marked ⚠ in red; it must be switched off or replaced before the graph can run. Rows are applied top to bottom. Up to 64 rows. |

The picker screen:

- a **card for every LoRA** found in the loras folders (sub-folders included): preview image, name, model family, size, trigger words;
- **filter chips by model family** (`SDXL`, `SDXL (Pony)`, `SD 1.x / 2.x`, `Flux`, `SD 3`, ..., with counts) and a **search** that needs every word you type to be found in the name, the trigger words, the frequent training tags or the family (`cel shading`, `watercolor`, `pixel`); sort by name, newest or size;
- a **detail panel** for the selected card: preview, family and base model, **trigger words** (tap one to copy it, or **Copy all**), the **frequent training tags**, **recommended settings** (strength, sampler, steps, CFG, negative prompt), Civitai names and description, **training data** (network dim / alpha, resolution, epochs, images, clip skip), and **My notes**: trigger words, a recommended strength and a text of your own, saved to `ComfyUI/user/bart_lora_notes.json` and used before anything else. **Use this LoRA** adds it (starting at the recommended strength, if any).

### Outputs

| Output | Type | Meaning |
| --- | --- | --- |
| `model` | `MODEL` | The model with the switched-on LoRAs applied. |
| `clip` | `CLIP` | The CLIP with them applied (nothing when no CLIP was connected). |
| `lora_names` | `STRING` | The names of the LoRAs that were applied, without folder and extension, separated by commas (`watercolor_sdxl, anime_flux`). |
| `trigger_words` | `STRING` | The trigger words of those LoRAs (your notes, then Civitai, then the A1111 `.json`; kohya's training tags are not included), in order, without repeats, separated by commas: join it with your prompt (for example with **Simple concatenate**). Empty when none are known. |

### How it works

Each row is applied with ComfyUI's own `load_lora_for_models`, the same call as the stock **Load LoRA**, one file after the other, so the result is that of a chain of Load LoRA nodes. A row that is switched off, or whose strengths are both 0, is not even loaded. The rows are kept as JSON in a hidden widget of the node.

**Compatibility warning.** The family of every applied LoRA (from its metadata or tensor names) is compared with the family of the connected model (from its class: SDXL, SD 1.x / 2.x, SD 3, Flux, Wan, Hunyuan, Qwen, LTX). When both are known and differ, the node writes `anime_flux looks like a Flux LoRA, but the connected model is SDXL` under its rows (and to the ComfyUI log). Pony counts as SDXL; SD 1.x and 2.x are not told apart; an unknown family on either side gives no warning. It is a hint, nothing is blocked.

Where the information comes from (nothing is downloaded, and no file is ever unpickled):

| Source | Gives |
| --- | --- |
| the **safetensors header** (kohya `ss_*` fields, `modelspec.*`) | model family and base checkpoint, training data, **frequent training tags** (`ss_tag_frequency`), title and author. Without metadata the family is guessed from the tensor names. |
| `foo.civitai.info` (Civitai Helper) | trigger words, base model, model and version names, description, sampler / steps / CFG of the first example image |
| `foo.json` (the A1111 LoRA tab) | `activation text` (trigger words), `preferred weight`, `negative text`, `sd version`, notes |
| `foo.preview.png` / `foo.png` (also `.jpg`, `.jpeg`, `.webp`) | the preview image |
| **My notes** | trigger words, strength and text you typed on the screen |

Trigger words come from My notes first, then Civitai, then the A1111 `.json`; kohya's training tags are listed separately because they are not always the triggers.

### Notes and limits

- `.pt`, `.ckpt` and `.bin` LoRAs work, but nothing is read from them (they are pickles); only their sidecar files and your notes are shown.
- The model family is a guess when the file has no metadata. A LoRA for another family is only *warned about*, not blocked: ComfyUI applies it as far as its keys match and logs the rest as `NOT LOADED`.
- A LoRA replaced under the same name makes the node run again (its file's date and size are part of the cache key); the picker's list is kept for 30 seconds, **⟳** rescans.
- Metadata is read once per file version and cached in memory; a folder of thousands of LoRAs takes a moment the first time the picker opens.

---

## Simple Concatenate

Joins any number of inputs into one text. **A new input appears as soon as the last one is connected**, and the only setting is the separator.

| | |
| --- | --- |
| **Class · category** | `BartSimpleConcatenate` · `Bart's nodes/Text` |
| **Example workflow** | [`17_simple_concatenate.json`](example_workflows/17_simple_concatenate.json) |
| **Needs** | a ComfyUI with dynamic ("autogrow") inputs; an older one skips this node alone and logs why |
| **Network** | none |
| **HTTP routes** | none |
| **Verified** | in a real ComfyUI frontend and through its API: slots appearing as inputs are connected (one free slot is always there) and tidying up on disconnect, a text, an integer, a float and a boolean joined with the default line break, `", "`, a tab, an empty separator, one input, none, a gap in the slot numbers, and an image refused with a message naming the input; the example runs. |

### Widgets and inputs

| | Meaning |
| --- | --- |
| inputs (grow as you connect) | Anything that can be turned into text: text, integers, floats, booleans (written `True` / `False`), a dictionary (as JSON). A list contributes each of its items. Nothing connected to a slot = nothing there. Up to 32 inputs; they are joined in slot order. |
| `separator` | The only setting. Default **`\n`, a line break**; `\t` is a tab, `\r` a carriage return, `\\` one backslash; anything else (`, `, ` `, ` | `) is used as typed. Can be linked too. |

### Outputs

| Output | Type | Meaning |
| --- | --- | --- |
| `text` | `STRING` | The inputs one after the other with the separator between them. |

### Notes and limits

- An **empty text keeps its place** (two separators in a row); an empty *slot* does not count at all.
- Something that is not text (an image, a model, a latent, ...) stops the run with a message such as `Simple concatenate: text1 is a Tensor, which cannot be turned into text`, rather than writing `<object at 0x...>`.
- The separator is a single-line box, which cannot show a real line break: that is why the default is typed as `\n`. A real line break pasted into it works too.

---

## Model Selector

One node for every model file, in the spirit of [ComfyUI-SmartModelLoaders-MXD](https://github.com/Maxed-Out-99/ComfyUI-SmartModelLoaders-MXD): **the format does not matter and neither does the folder the file lies in.** It reads the file, works out what it is, loads it the right way and gives out **whatever the file holds**: a checkpoint gives model + CLIP + VAE, a diffusion model only the model, and so on.

| | |
| --- | --- |
| **Class · category** | `ModelSelector` · `Bart's nodes/Model` |
| **Example workflow** | [`19_model_selector.json`](example_workflows/19_model_selector.json) |
| **Needs** | nothing beyond ComfyUI. **GGUF files** need a GGUF loader pack installed: [ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF) or ComfyUI-SmartModelLoaders-MXD (this node borrows its loader; nothing of theirs is copied) |
| **Network** | none |
| **HTTP routes** | `/model_selector/list`, `/model_selector/info` (GET) — only files under the model folders |
| **Verified** | in a real ComfyUI with sample files of every kind (headers of the right shape): the routes, the picker screen (cards, the three filter rows, the search, the characteristics panel, GGUF refused until a loader pack exists), choosing, the dimmed outputs, save and reload, a missing file marked in red, queue-time errors (empty, missing, outside the folders, GGUF without a pack), and the message for a damaged file. A **real** (tiny, pixel-space) VAE file went through the node into a real `VAEDecode`, with the kind taken from its folder. Which ComfyUI loader gets which file, and what comes out where, is unit-tested against stand-ins, GGUF included. **Not:** a real checkpoint, diffusion model, text encoder or CLIP vision file (none was installed), a real GGUF through a real loader pack, and the family guess on real downloaded models (only on headers made to look like them). |

### Widgets and inputs

| | Meaning |
| --- | --- |
| **＋ Choose a model…** | Opens the picker screen. The node shows the chosen file's name, its type, model family, precision and what it gives (`checkpoint · SDXL · safetensors fp16 2.6B → MODEL, CLIP, VAE`), and the outputs the file does **not** fill are drawn as `name (none)`. A file that has gone is marked ⚠ in red; the graph will not run until another is chosen. |
| `weight_dtype` (advanced) | For checkpoints and diffusion models: `default` or load the weights as `fp8_e4m3fn` / `fp8_e4m3fn_fast` / `fp8_e5m2` (as Load Diffusion Model). |
| `clip_type` (advanced) | For a **text encoder** file: what it is meant for (`stable_diffusion`, `flux`, `wan`, ..., the types of Load CLIP, see its recipes). One file does not say, so you do. For a GGUF text encoder it is passed to the loader pack. |
| `device` (advanced) | For a text encoder file: `cpu` keeps it off the GPU. |

The picker screen:

- a card for **every model file** of the model folders (checkpoints, diffusion models / unet, text encoders / clip, vae, clip_vision, and the GGUF folders), sub-folders included, in **any format**: `.safetensors`, `.sft`, `.ckpt`, `.pt`, `.pth`, `.bin`, `.gguf`;
- three rows of **filters**: the **type** (checkpoint, diffusion model, text encoder, VAE, CLIP vision), the **model** family (SDXL, SD 1.x, SD 3, Flux, Wan, Qwen Image, Z-Image, LTX, Hunyuan, T5, ...) and the **format**, each with counts; they combine. A **search** that needs every word you type to be found in the name, type, family, format or precision (`flux bf16`, `q4_k`), and sorting by name, newest or size;
- a **characteristics panel** for the selected card: the type (and whether it comes from the file or only from its folder), the model family, format, **precision** (fp32 / fp16 / bf16 / fp8, or the GGUF quantisation such as Q4_K_M), the **number of parameters**, the number of tensors, the size, the folder, the date, **what it gives on its outputs**, and the metadata the file carries (title, author, description, architecture, and for trained models the base model, resolution and epochs). **Use this model** chooses it.

### Outputs

| Output | Type | Meaning |
| --- | --- | --- |
| `model` | `MODEL` | The diffusion model: from a checkpoint or a diffusion model file, empty otherwise. |
| `clip` | `CLIP` | The text encoder: from a checkpoint or a text encoder file. |
| `vae` | `VAE` | The VAE: from a checkpoint or a VAE file. |
| `clip_vision` | `CLIP_VISION` | The CLIP vision model: from a CLIP vision file. |
| `name` | `STRING` | The file's name without its extension (`flux1-dev-Q4_K_M`). |

Outputs the file does not hold are empty: connect only the ones your file gives.

### How it works

**What a file is** is decided by its **content**, so a diffusion model lying in the `checkpoints` folder, or a VAE in `unet`, is still loaded as what it is. For `.safetensors` only the **header** is read (tensor names, shapes and types, the `__metadata__` block): a file with a diffusion-model part and a text-encoder or VAE part is a checkpoint, with only the diffusion-model part a diffusion model, and so on; the family comes from the metadata, else from the tensor names. For `.gguf` the architecture and quantisation come from the header. A file whose content says nothing (a pickle `.ckpt` / `.pt`, which is **never opened** by the scan, or an unusual layout) takes the kind of the folder it lies in, and the panel says so.

Loading is ComfyUI's own: `load_checkpoint_guess_config` for checkpoints (model, CLIP, VAE), `load_diffusion_model`, `load_clip`, the VAE and CLIP vision loaders; a pickle file is loaded the way ComfyUI loads it (`safe_load`). GGUF files go through the class of the installed loader pack (`UnetLoaderGGUF` / `CLIPLoaderGGUF`, or the Smart loaders of MXD), which is told where the file is: the pack does not need the file to lie in its own folder.

### Notes and limits

- The scan covers the **model-loading folders** (and the extra folders ComfyUI is configured with), not the whole `models` directory: LoRAs, ControlNets, upscalers and embeddings have their own loaders (use [Lora Selector](#lora-selector) for LoRAs). Files whose names start with a dot are skipped; at most 20,000 files are listed.
- The id of a choice is `folder::path/inside/it` (`checkpoints::sdxl/base.safetensors`), so the same file name in two folders is two different choices, and a workflow keeps working when the file is moved *within* its folder only if you pick it again.
- One text-encoder file at a time: models that need two or more encoders (SDXL's, Flux's) take them from a checkpoint, or you load the encoders separately (a dual-CLIP loader is not included).
- A file that is not a recognised kind (it says nothing and lies in no known folder) is refused with a message instead of being guessed.
- The family and kind are **guesses from headers**: check the characteristics panel before trusting them on an unusual model.

---

## WAN Latent Trim Start

Cuts frames off the **start** of a WAN video latent **before the VAE decode**, with the count in **pixel frames** (the unit you see in the finished video).

| | |
| --- | --- |
| **Class · category** | `WanLatentTrim` · `Bart's nodes/Latent` |
| **Example workflows** | [`13_wan_latent_trim.json`](example_workflows/13_wan_latent_trim.json) (needs no model), group 5 of [`12_all_nodes.json`](example_workflows/12_all_nodes.json) |
| **Needs** | nothing beyond ComfyUI |
| **Network** | none |
| **HTTP routes** | none |
| **Verified** | output compared with ComfyUI's own **Trim Video Latent** on a 21-frame latent: bit-identical for 0, 4, 8, 12, 40 and 80 px frames; run in a real ComfyUI (API and frontend) on an empty 81-frame latent, including the snapping and the error case; the frame formula checked against the WAN VAE's `upscale_ratio` in ComfyUI's source. **Not** run on a real WAN sampler output through a real VAE decode. |

Ported from the standalone `comfyui-wan-latent-trim` project, with a few changes: logging instead of `print`, the two extra outputs, and tests.

### Widgets

| Widget | Meaning |
| --- | --- |
| `samples` (input) | A 5-dimensional video latent `[B, C, T, H, W]`, for example the output of a WAN sampler. |
| `trim_start_frames` | Pixel frames to remove from the start (0-16384). Converted to latent frames as `round(N / 4)`, halves rounding up; multiples of 4 are exact. 0 passes the latent through unchanged. |

### Outputs

| Output | Type | Meaning |
| --- | --- | --- |
| `samples` | `LATENT` | The trimmed latent. The input is not modified. |
| `removed_frames` | `INT` | Pixel frames that were **really** removed (a request that isn't a multiple of 4 is snapped). |
| `frames_left` | `INT` | Pixel frames the trimmed latent will decode to. |

### How it works

WAN's VAE compresses time 4× with a causal first frame, so `T` latent frames decode to `4T − 3` pixel frames (`F = (T − 1) · 4 + 1`; ComfyUI's own WAN `upscale_ratio` is `a * 4 - 3`). Dropping `L` latent frames from the front therefore drops exactly `4 · L` pixel frames: the `+1` keyframe cancels between the old and the new total. That is why the pixel count converts cleanly, and why the cut can only land on a multiple of 4. Put the node **between the sampler and VAE Decode**; it saves decoding frames you would throw away.

ComfyUI's own **Trim Video Latent** does the same slice, but its `trim_amount` is in *latent* frames and it neither reports what it did nor refuses a cut that leaves nothing. This node adds the pixel-frame unit, the two reporting outputs, clear errors, and trims a per-frame `noise_mask` along with the samples.

### Notes and limits

- **WAN-style 4× latents only.** The conversion assumes 4× temporal compression. LTX-Video (8×, `8T − 7`) and Mochi (6×, `6T − 5`) latents are 5-dimensional too and would be accepted, but the pixel count would be wrong; use ComfyUI's `LatentCut` (`dim = t`) in latent frames for those.
- A 4-dimensional (image) latent is refused with a message; asking to remove all frames or more is refused too (`nothing would remain`).
- Only a 5-dimensional `noise_mask` whose time axis matches the samples is trimmed; the usual 4-dimensional mask is left as it is.
- The start only. To cut the end, use `LatentCut` with `dim = t`.
- Reasoned, not measured: a causal VAE decodes the new first latent frame as a single frame, so the frames right after the cut can differ slightly from decoding the whole clip and cutting the pixels.
- The same class id as the standalone `comfyui-wan-latent-trim` project: don't install both (one overrides the other); workflows made with the standalone node load here unchanged.

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

## VoxCPM Speech

Wraps [OpenBMB/VoxCPM](https://github.com/OpenBMB/VoxCPM), a tokenizer-free text-to-speech model: text in, **speech** out, with three ways to choose the voice. Two nodes: a loader and a speaker.

| | |
| --- | --- |
| **Class · category** | `VoxCPMModelLoader`, `VoxCPMGenerate` · `Bart's nodes/Audio` |
| **Example workflow** | [`14_voxcpm_speak.json`](example_workflows/14_voxcpm_speak.json) |
| **Needs** | the **`voxcpm` package** (`pip install voxcpm`; Python 3.10-3.12, torch ≥ 2.5; it also pulls in gradio 6, datasets 3, funasr, modelscope, ...: consider a separate environment) and hardware: upstream quotes ~8 GB of VRAM for VoxCPM2 (~6 GB for 1.5, ~5 GB for 0.5B) and a real-time factor of ~0.3 on an RTX 4090 |
| **Network** | only the one-time weight download from Hugging Face (and, with `load_denoiser`, the ZipEnhancer model from ModelScope) |
| **HTTP routes** | none |
| **Verified** | the nodes inside a real ComfyUI with a stand-in `voxcpm` package (registered, queued, the not-installed message, empty text refused at queue time) and in unit tests against the upstream `generate()` signature (read from its source). **Not:** the real package and weights: no audio from a real VoxCPM model has been produced by this pack, so speed, memory and voice quality are the upstream's claims. |

### Widgets

| Node | Widget | Meaning |
| --- | --- | --- |
| Model Loader | `model` | `openbmb/VoxCPM2` (2B, 30 languages, 48 kHz, voice design and reference cloning), `openbmb/VoxCPM1.5` (zh / en, 44.1 kHz) or `openbmb/VoxCPM-0.5B` (zh / en, 16 kHz); weights download on first use. A checkpoint folder (with its `config.json`) put in `ComfyUI/models/voxcpm/` shows up as `local: <folder>`. |
| Model Loader | `device` | `auto` (CUDA, else Apple MPS, else CPU), `cuda`, `mps`, `cpu`. The loaded model is cached in memory keyed by all its load options. |
| Model Loader | `optimize` | `torch.compile` plus a warm-up run (upstream's default). Off here: it helps on CUDA but is slow to start and fragile elsewhere. |
| Model Loader | `load_denoiser`, `local_files_only` | Also load the ZipEnhancer noise suppressor (needed by `denoise`); never touch the network. |
| Speak | `text` | What to say (line breaks become spaces). |
| Speak | `voice_description` | **Voice design** (VoxCPM2): a description in words, `A young woman, gentle and sweet voice`, which the node puts in parentheses in front of the text, as upstream expects. With a reference audio it steers the *style* of the cloned voice (`slightly faster, cheerful tone`). Parentheses inside it are dropped. Results vary between runs: try 1-3 seeds. |
| Speak | `reference_audio` | **Controllable cloning** (VoxCPM2 only): the voice of this clip. Any `AUDIO` (Load Audio, a recorder, ...); it is mixed to mono and handed over as a temporary WAV. |
| Speak | `prompt_audio` + `prompt_text` | **Continuation cloning** (every model): a clip and its **exact transcript**; the speech continues from it, keeping timbre, rhythm and style. Both or neither. With both this and `reference_audio` it is upstream's "ultimate cloning" (use the same clip for both for the closest likeness). |
| Speak | `seed` | With `control after generate` as usual; the same seed repeats the same take. |
| Speak | `cfg_value`, `inference_timesteps` | Guidance scale (2.0) and diffusion steps (10): more steps, slower and a little cleaner. |
| Speak | `normalize`, `denoise` | Text normalisation (numbers, dates; needs `wetext`), and denoising of the reference / prompt clips (needs `load_denoiser`). |
| Speak | `max_len`, `retry_badcase`, `retry_badcase_max_times`, `retry_badcase_ratio_threshold` | Token cap, and the retry loop for takes whose audio is too long for the text. |

### Outputs

| Node | Output | Type | Meaning |
| --- | --- | --- | --- |
| Model Loader | `model` | `VOXCPM_MODEL` | Feeds Speak. |
| Speak | `audio` | `AUDIO` | Mono, at the model's rate (48 / 44.1 / 16 kHz): into **Save Audio** or **Preview Audio**. |
| Speak | `info` | `STRING` | Which mode ran, the model, the length and the seed. |

### Notes and limits

- **Which mode runs** follows from what is connected: nothing = plain speech; a `voice_description` = voice design; `reference_audio` = controllable cloning; `prompt_audio` = continuation; both = ultimate cloning. VoxCPM 1.5 and 0.5B cannot do voice design or reference cloning: the node passes the upstream error on ("reference_wav_path is only supported with VoxCPM2 models").
- **License and misuse.** The code and weights are Apache-2.0. Upstream states that using voice cloning for impersonation, fraud or disinformation is strictly forbidden and asks you to label AI-generated speech. Only clone voices you have the right to use.
- **Interrupt** does not stop a generation in progress (one blocking call); it ends with the audio.
- A text is one generation, capped by `max_len` tokens: for a minutes-long script, speak it paragraph by paragraph rather than raising `max_len`.

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
| [`12_all_nodes.json`](example_workflows/12_all_nodes.json) | **All nodes in one graph**, in five groups (below) |
| [`13_wan_latent_trim.json`](example_workflows/13_wan_latent_trim.json) | WAN Latent Trim Start on an empty latent: no model needed, shows `removed_frames` / `frames_left` |
| [`14_voxcpm_speak.json`](example_workflows/14_voxcpm_speak.json) | VoxCPM Model Loader → Speak (a described voice) → Save Audio; the info line. Needs the `voxcpm` package |
| [`15_easy_ollama.json`](example_workflows/15_easy_ollama.json) | Easy Ollama: Load Image → a vision model → the answer and the debug text |
| [`16_lora_selector.json`](example_workflows/16_lora_selector.json) | Lora Selector: Load Checkpoint → several LoRAs with switches and strengths → the names of the LoRAs in use |

**`12_all_nodes.json`** has five groups; they don't depend on each other, so mute or bypass the ones you don't need (select the group's nodes, `Ctrl+M` to mute, `Ctrl+B` to bypass):

1. **Pick images** — Load Random Image (muted until you set `directory`), Image Picker, Smart Load Image, Load Random Booru Image (Safebooru, `landscape`), each into a preview.
2. **Check anatomy** — Smart Load Image's cropped image → Anatomy Defect Filter → `passed` preview, `failed` saved to `output/rejected/`, report. Needs an Ollama vision model.
3. **Write a video prompt** — Load Random Prompt (52prompts) → the `request` of MiniMax H3 Prompt (a linked widget) → prompt, duration and size previews. Needs an Ollama chat model.
4. **Make music** — YuE2 Model Loader → Plan Score → Generate Song → Save Audio. **Bypassed by default**: it needs the `yue2` package and a big GPU. Un-bypass it (`Ctrl+B` again) once that is set up.
5. **Trim a video latent** — an empty 81-frame latent → WAN Latent Trim Start (10 px frames asked, 12 removed) → `removed_frames` and `frames_left` previews. Needs no model.

The examples were loaded back into a real ComfyUI frontend (01-05 and 09-13) and run from its Run button; 06-08 load fine but need the `yue2` package and a big GPU to execute.

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
| WAN Latent Trim Start | none | none | — |
| YuE2 nodes | Hugging Face (weights, once) | none | — |
| VoxCPM nodes | Hugging Face (weights, once), ModelScope (optional denoiser) | none | the `voxcpm` package and its pinned dependencies; cloning someone's voice is on you |
| Easy Ollama | `address` | none | your prompt and images go to that server |
| Lora Selector | none | `/lora_selector/*` | lists the names and metadata of the LoRA files to anyone who can reach the port; `POST /notes` writes one small file in the user folder (JSON only, 64 KB, known LoRA names only) |
| Simple concatenate | none | none | — |
| Format Detector | none | none | — |
| Model Selector | none | `/model_selector/list`, `/info` | lists the names and header facts (type, family, precision, parameters, metadata) of the model files to anyone who can reach the port; only headers are read, no file is loaded or unpickled by the scan |

**Directory node (Load Random Image).** The `/random_image/list`, `/pick` and `/view` routes accept a `dir` parameter with **no restriction whatsoever**: anyone who can reach ComfyUI's HTTP port (not necessarily through the graph or UI at all; a bare GET is enough) can list and read arbitrary files the ComfyUI process can access. This is a deliberate tradeoff for the node's core feature (loading from any folder), not a bug an allowlist should close.

**Image Picker.** Its routes take a subfolder and a file name relative to ComfyUI's input folder and refuse `..`, absolute paths, NUL bytes and (on Windows) drive letters; only image files are listed or turned into thumbnails. The check is by path, not by realpath, so a symlinked collection inside the input folder works (as with the stock `/view`). `/image_picker/pool` only counts (and, with `list=1`, names) images, capped at 20,000. Anyone reaching the port can read the images in the input folder and make the server generate thumbnails (cached in the temp folder); the work is bounded: images over 64 megapixels are refused with HTTP 413, and at most three thumbnails are decoded at once.

**Booru node.** It makes **outbound requests to a third-party image board** from the ComfyUI host, and any prompt containing it does so on execution. The `/random_booru/*` routes take `source` + `tags` + `index`/`post_id`, never a raw URL. The file URL itself is read out of third-party responses (HTML for Gelbooru, JSON for the rest), so every candidate must be on the source's own domain or a subdomain (`gelbooru.com` / `imgN.gelbooru.com`, `yande.re` / `files.yande.re`, `xbooru.com` / `img.xbooru.com`, ...); a candidate on any other host is skipped, `download()` re-checks the host right before the request goes out, and the HTTP client refuses a redirect that leaves the domain (the Cookie and Referer never travel to another host), so these endpoints can't be pointed at an arbitrary target (no SSRF). They are unauthenticated like everything else here: anyone reaching the port can make your server fetch booru pages and fill the temp cache. Downloaded content is arbitrary third-party imagery, entirely unfiltered by rating, and cached copies stay in ComfyUI's temp directory until it is cleaned.

**52prompts node.** Same outbound-request caveat: the site sees your server's IP, and `/random_prompts52/pick` is unauthenticated. It takes a generator **label** from a fixed table, never a URL, and the script URL it fetches must be on the site's CDN host, so there is no SSRF. The fetched script is **not** executed as JavaScript: `prompts52/jsmini.py` has no filesystem, network or `eval` surface at all; the worst a rewritten generator can do is raise an error or return odd text.

**MiniMax H3 prompt node.** It POSTs your request text to the workflow's `ollama_url` from the ComfyUI host, **plus one HTTP route**: `POST /minimax_h3/generate` takes the widget values, including `ollama_url`, from the caller, so anyone who can reach the port can make the server send a JSON POST to `/api/chat` on any http(s) host:port it can reach (loopback and LAN included) and read back the parsed prompt text or an error message. Mitigations: only http/https; the path always ends in `/api/chat` (a URL with a `?query`, `#fragment`, `;params` or `user:password@` is refused, so nothing can be smuggled into the request line); redirects are not followed; a timeout and a 16 MB cap on the response; only the parsed `message.content` is returned (never a raw response), and an error quotes at most 200 characters of the `error` field of an Ollama HTTP error (such as `model not found`), nothing else from the peer; every other value is range-checked. The route accepts only `application/json` (a plain cross-site form post from some web page is refused with HTTP 415, a JSON one from another site needs a CORS preflight, which ComfyUI answers only when started with `--enable-cors-header`), takes bodies up to 256 KB, and runs generations on its own two-thread pool with at most four in flight (HTTP 429 beyond that), so it can't starve ComfyUI's other routes. If the port is reachable by people you don't trust, don't leave this node installed.

**Anatomy filter.** It sends your images to whatever `ollama_url` the workflow says, from the ComfyUI host: images leave the machine if that server is remote, and a workflow someone else wrote can point it at any host:port reachable from yours (it only ever POSTs to `/api/chat`). The node adds **no HTTP routes**: a frontend helper taking the URL from the browser would turn ComfyUI into an open proxy, which is why `model` is a plain text field.

**If ComfyUI is exposed on a LAN or the internet** (not just `127.0.0.1`), restrict access at the network level (VPN, an authenticating reverse proxy, firewall) rather than assuming ComfyUI or these nodes restrict anything: ComfyUI itself ships with no authentication on any of its endpoints by default.

## Tests

The logic is covered by unit tests (450+; they need no ComfyUI and no network, and the ones that need torch skip themselves without it): file selection and the sequential / increment rules (including the edit-serial handshake with the frontend), the shared image decoding (truncated, 16-bit, palette, EXIF and animated files, compared with the loaders it replaced), booru position selection, the download layer (against a local HTTP server: size and signature checks, redirects that leave the site, the cache limit, transient versus permanent failures) and the backends' parsers (Gelbooru HTML, Moebooru / dapi JSON), `IS_CHANGED` of every node called the way ComfyUI calls it, the 52prompts JavaScript interpreter (against inline fixtures, including its memory limits), the YuE2 helpers, the MiniMax H3 wrapper (against a faked Ollama) with its URL and option validation, the Image Picker's path safety / folder listing / thumbnail generation (also with many threads at once), the latent trim's frame math (and, with torch installed, the node against real tensors), the crop box clamping and, under `node` when installed, the crop editor's drag geometry, and the anatomy filter's verdict parsing and Ollama client (against a mocked server), the VoxCPM nodes (against a stand-in `voxcpm` package), the Model Selector (headers of every kind of model file, the folder scan, the loading per kind against stand-ins, GGUF), Format Detector (formats, sizes for every format at many megapixel values, the crop box, the node against real tensors), Simple concatenate (the text conversion and joining), the Lora Selector (LoRA headers and sidecars, notes, the stack, and the node against stand-ins for `comfy`), and Easy Ollama (against a local stand-in server that records what arrives, including requests with a `num_ctx` from 256 to 1,000,000).

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
imageload.py             shared image decoding for every loader: damaged-file tolerance, 16-bit scaling, transparency, EXIF, frames
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
  thumbs.py              thumbnail generation (unique temp file per request, then an atomic rename)
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
  clipchat.py            the CLIP backend: a text-LLM encoder of the graph as the kit's `chat` function (duck-typed, no ComfyUI import)
  nodes.py, routes.py    the node (saved-text-wins logic, outputs); POST /minimax_h3/generate
latenttrim/              WAN Latent Trim Start
  selection.py           pure frame math: pixel_frames(), latent_frames_to_trim(), plan_trim()
  nodes.py               the node (torch): slice samples and a per-frame mask, report what went
yue2/                    YuE2 nodes
  selection.py           pure logic: VAE choices, generate() kwargs, token budgets
  nodes.py               YuE2ModelLoader, YuE2Plan, YuE2Generate; pipeline cache, ABC/audio I/O
model_selector/           Model Selector (`ModelSelector`)
  model_info.py          safetensors / GGUF headers, the kind, family, precision and parameters of a file (no torch)
  files.py               finding the model files of every folder, ids, resolving them safely
  nodes.py, routes.py    the node (ComfyUI's loaders per kind, the GGUF borrow); /model_selector/list, /info
format_detector/          Format Detector (`FormatDetector`)
  selection.py           formats, the nearest-format search, the size for a number of megapixels, the crop box (no torch)
  nodes.py               the node; crops and scales the IMAGE with torch
simple_concat/            Simple concatenate (`BartSimpleConcatenate`, a V3 node with autogrow inputs)
  selection.py           turning values into text, the separator escapes, joining (no ComfyUI)
  nodes.py               the node
lora_selector/           Lora Selector (`LoraSelector`)
  metadata.py            safetensors header, family guess, sidecar files, my notes (no torch)
  selection.py           the stack of rows: parsing, checks, names output
  nodes.py, routes.py    the node; /lora_selector/list, /info, /preview, /notes
ollama_chat/             Easy Ollama (`OllamaChat`)
  client.py              address and settings parsing, the request, the HTTP call, the debug text (no torch)
  nodes.py               the node; IMAGE batch -> base64 JPEGs
voxcpm_tts/              VoxCPM speech nodes (not `voxcpm/`: it must not shadow the package it wraps)
  selection.py           pure logic: presets, the (description)text prompt, generate() kwargs, a stdlib WAV writer
  nodes.py               VoxCPMModelLoader, VoxCPMGenerate; model cache, AUDIO <-> temporary WAV
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
- The Lora Selector has been run with ComfyUI's real LoRA code on a tiny stand-in network, not on a real checkpoint (none was installed here); the application itself is ComfyUI's `load_lora_for_models`, driven in the same way as the stock Load LoRA.
- The Model Selector has loaded one real file (a tiny pixel-space VAE); checkpoints, diffusion models, text encoders, CLIP vision and GGUF through a real loader pack are covered by stand-ins and header-shaped sample files, not real downloads.
- Easy Ollama has been run against one small vision model; with the context left unset the server's own choice (here 262144, 33 GB) is not something the node can prevent, only report: keep `num_ctx` in the settings.
- The VoxCPM nodes have been run only against a stand-in `voxcpm` package: no audio from the real package and weights has been produced by this pack, and the package's pinned dependencies (gradio 6, datasets 3, Python < 3.13) may not fit your ComfyUI environment.
- The YuE2 nodes have run end to end on Apple MPS (slow: ~13 min for a 98 s track) but not on CUDA, and not inside a ComfyUI graph with the real `yue2` package installed.
- WAN Latent Trim Start has been checked against ComfyUI's own node and on empty latents, not on a real WAN generation (see its **Verified** row).
- The anatomy filter's judgement quality depends entirely on the vision model you pick; it has been exercised on a few synthetic images only. Calibrate on your own.
- Image Picker has not been tried on a physical touch device (see its **Verified** row), and it lists at most the first 5000 images of a folder (by name).
- Smart Load Image's crop editor has been driven with a mouse only; its touch handling (one pointer at a time, 32 px handle targets) is covered by the geometry tests and code reading, not by a finger on a screen.
- MiniMax H3 Prompt: Interrupt doesn't cancel a request already waiting on Ollama; its outputs have not been wired into the real MiniMax video nodes. The CLIP backend has been run with a real Qwen3-4B encoder for one short T2VA prompt (see its **Verified** row) and with a stand-in CLIP object and unit tests for the rest; how well small encoders handle `story`, `ref` or long prompts is unknown.
