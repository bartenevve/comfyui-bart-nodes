// Full-screen image gallery for ComfyUI's input folder, built for touch screens.
//
// Why not the stock dropdown: on a phone, tapping a LiteGraph combo opens its menu
// on pointerdown and the finger-up that follows lands on the menu's backdrop and
// closes it again. This gallery is opened from a real DOM <button> (a finished
// `click`, nothing left to bounce) and ignores any tap in its first moments, so
// the opening gesture can't select or dismiss anything. Scrolling is the
// browser's own (momentum, overscroll contained); a scroll never fires `click`,
// so only a deliberate tap picks an image.
//
// Shared module: imported by js/image_picker.js, with no extension of its own.

const PREFS_KEY = "bart_image_gallery_prefs";
const TAP_GUARD_MS = 350; // taps this soon after opening are the opening gesture's echo
const CHUNK = 120; // cells rendered per step; the rest are added as the user scrolls
const THUMB_BUCKETS = [128, 192, 256, 384, 512]; // keep in step with the server's THUMB_SIZES

export function thumbBucket(pixels) {
    return THUMB_BUCKETS.find((bucket) => bucket >= pixels) || THUMB_BUCKETS[THUMB_BUCKETS.length - 1];
}

export function naturalCompare(a, b) {
    return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
}

// "a/b/c.png" -> { subfolder: "a/b", filename: "c.png" }
export function splitPath(path) {
    const text = (path || "").replace(/\\/g, "/");
    const slash = text.lastIndexOf("/");
    return slash < 0
        ? { subfolder: "", filename: text }
        : { subfolder: text.slice(0, slash), filename: text.slice(slash + 1) };
}

export function joinPath(subfolder, filename) {
    return subfolder ? subfolder + "/" + filename : filename;
}

export function thumbUrl(subfolder, filename, size, stamp) {
    const params = new URLSearchParams({ subfolder, filename, size: String(size) });
    if (stamp) params.set("t", String(stamp));
    return "/image_picker/thumb?" + params.toString();
}

export async function fetchListing(subfolder) {
    const resp = await fetch("/image_picker/list?" + new URLSearchParams({ subfolder }).toString());
    const data = await resp.json();
    if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
    return data;
}

export async function uploadToInput(file, subfolder) {
    const body = new FormData();
    body.append("image", file);
    body.append("type", "input");
    if (subfolder) body.append("subfolder", subfolder);
    const resp = await fetch("/upload/image", { method: "POST", body });
    if (resp.status !== 200) throw new Error("upload failed: HTTP " + resp.status);
    const data = await resp.json();
    return joinPath(data.subfolder || "", data.name);
}

function loadPrefs() {
    try {
        return JSON.parse(localStorage.getItem(PREFS_KEY)) || {};
    } catch (e) {
        return {};
    }
}

function savePrefs(prefs) {
    try {
        localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
    } catch (e) {
        /* private mode / storage disabled: the gallery just forgets its settings */
    }
}

const SORTS = {
    "name-asc": (a, b) => naturalCompare(a.name, b.name),
    "name-desc": (a, b) => naturalCompare(b.name, a.name),
    newest: (a, b) => b.mtime - a.mtime || naturalCompare(a.name, b.name),
    oldest: (a, b) => a.mtime - b.mtime || naturalCompare(a.name, b.name),
};

const STYLE = `
.bgal-overlay{position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,.86);display:flex;justify-content:center;
  font-family:system-ui,-apple-system,sans-serif;color:#eee;-webkit-text-size-adjust:100%}
.bgal-panel{display:flex;flex-direction:column;width:100%;height:100%;max-width:1280px;background:#1c1c1e;min-height:0}
@media (min-width:900px){.bgal-overlay{padding:3vh 3vw}.bgal-panel{border-radius:14px;overflow:hidden;box-shadow:0 10px 50px rgba(0,0,0,.6)}}
.bgal-head,.bgal-tools{display:flex;align-items:center;gap:8px;padding:8px 10px;border-bottom:1px solid #333}
.bgal-head{padding-top:calc(8px + env(safe-area-inset-top))}
.bgal-tools{flex-wrap:wrap}
.bgal-btn{min-height:44px;min-width:44px;padding:0 14px;font-size:16px;border-radius:10px;border:1px solid #484848;
  background:#2c2c2e;color:#eee;cursor:pointer;touch-action:manipulation;-webkit-tap-highlight-color:transparent;white-space:nowrap}
.bgal-btn:active{background:#3a3a3c}
.bgal-btn.on{background:#1d4f86;border-color:#4aa3ff}
.bgal-crumbs{flex:1;display:flex;gap:6px;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none}
.bgal-crumbs .bgal-btn{flex:0 0 auto;min-height:40px}
.bgal-tools input[type=search],.bgal-tools select{font-size:16px;min-height:44px;padding:0 12px;border-radius:10px;
  border:1px solid #484848;background:#2c2c2e;color:#eee;box-sizing:border-box}
.bgal-tools input[type=search]{flex:1 1 180px;min-width:0}
.bgal-size{display:flex;align-items:center;gap:8px;flex:1 1 260px}
.bgal-size input[type=range]{flex:1;min-width:80px;min-height:44px;touch-action:pan-x}
.bgal-size .bgal-btn{min-width:40px;padding:0 8px}
.bgal-grid{flex:1;min-height:0;overflow-y:auto;-webkit-overflow-scrolling:touch;overscroll-behavior:contain;padding:10px;
  display:grid;grid-template-columns:repeat(auto-fill,minmax(var(--bgal-size,160px),1fr));grid-auto-rows:max-content;gap:10px;align-content:start}
.bgal-cell{display:flex;flex-direction:column;gap:4px;padding:0;background:#262628;border:2px solid transparent;border-radius:10px;
  color:inherit;cursor:pointer;text-align:center;touch-action:manipulation;-webkit-tap-highlight-color:transparent;overflow:hidden;font:inherit}
.bgal-cell:active{background:#34343a}
.bgal-cell.current{border-color:#4aa3ff}
.bgal-thumb{position:relative;width:100%;height:0;padding-top:100%;background:#111;flex:0 0 auto}
.bgal-thumb img{position:absolute;inset:0;margin:auto;max-width:100%;max-height:100%;object-fit:contain;display:block}
.bgal-icon{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:calc(var(--bgal-size,160px)*.42)}
.bgal-name{font-size:12px;line-height:1.25;padding:0 6px 6px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;
  -webkit-box-orient:vertical;word-break:break-all}
.bgal-note{grid-column:1/-1;padding:24px;text-align:center;opacity:.7}
.bgal-foot{padding:6px 12px calc(6px + env(safe-area-inset-bottom));font-size:12px;opacity:.75;border-top:1px solid #333}
`;

function injectStyle() {
    if (document.getElementById("bgal-style")) return;
    const style = document.createElement("style");
    style.id = "bgal-style";
    style.textContent = STYLE;
    document.head.appendChild(style);
}

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

/**
 * Open the gallery. `current` is the selected path ("sub/name.png" or ""), `onSelect(path)`
 * gets the chosen one. Returns { close }.
 */
export function openImageGallery({ current = "", title = "Choose an image", onSelect }) {
    injectStyle();
    const openedAt = performance.now();
    const guarded = () => performance.now() - openedAt < TAP_GUARD_MS;

    const prefs = loadPrefs();
    const state = {
        subfolder: splitPath(current).subfolder,
        currentPath: current,
        folders: [],
        files: [],
        truncated: false,
        query: "",
        sort: SORTS[prefs.sort] ? prefs.sort : "name-asc",
        size: Math.min(400, Math.max(90, Number(prefs.size) || 160)),
        visible: [],
        rendered: 0,
        loading: false,
    };

    // ---- DOM --------------------------------------------------------------
    const overlay = el("div", "bgal-overlay");
    const panel = el("div", "bgal-panel");
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", title);

    const closeButton = el("button", "bgal-btn", "✕");
    closeButton.type = "button";
    closeButton.title = "Close";
    const crumbs = el("div", "bgal-crumbs");
    const uploadButton = el("button", "bgal-btn", "＋ Upload");
    uploadButton.type = "button";
    const fileInput = el("input");
    fileInput.type = "file";
    fileInput.accept = "image/*";
    fileInput.multiple = true;
    fileInput.style.display = "none";
    const head = el("div", "bgal-head");
    head.append(closeButton, crumbs, uploadButton, fileInput);

    const search = el("input");
    search.type = "search";
    search.placeholder = "Search by name";
    search.autocomplete = "off";
    search.setAttribute("enterkeyhint", "search");
    const sort = el("select");
    for (const [value, label] of [["name-asc", "Name A→Z"], ["name-desc", "Name Z→A"], ["newest", "Newest first"], ["oldest", "Oldest first"]]) {
        const option = el("option", "", label);
        option.value = value;
        sort.appendChild(option);
    }
    sort.value = state.sort;
    const sizeBox = el("div", "bgal-size");
    const range = el("input");
    range.type = "range";
    range.min = "90";
    range.max = "400";
    range.step = "10";
    range.value = String(state.size);
    range.setAttribute("aria-label", "Thumbnail size");
    const presets = [["S", 100], ["M", 160], ["L", 260]].map(([label, px]) => {
        const button = el("button", "bgal-btn", label);
        button.type = "button";
        button.addEventListener("click", () => {
            range.value = String(px);
            setSize(px, true);
        });
        return button;
    });
    sizeBox.append(...presets, range);
    const tools = el("div", "bgal-tools");
    tools.append(search, sort, sizeBox);

    const grid = el("div", "bgal-grid");
    const foot = el("div", "bgal-foot");
    panel.append(head, tools, grid, foot);
    overlay.appendChild(panel);

    // ---- behaviour --------------------------------------------------------
    let closed = false;
    function close() {
        if (closed) return;
        closed = true;
        observer.disconnect();
        document.removeEventListener("keydown", onKey, true);
        overlay.remove();
    }
    function choose(path) {
        close();
        if (onSelect) onSelect(path);
    }
    function onKey(event) {
        if (event.key === "Escape") {
            event.stopPropagation();
            close();
        }
    }
    document.addEventListener("keydown", onKey, true);
    closeButton.addEventListener("click", () => {
        if (!guarded()) close();
    });
    // a tap on the dark margin (desktop only: on a phone the panel fills the screen)
    overlay.addEventListener("click", (event) => {
        if (event.target === overlay && !guarded()) close();
    });

    const observer = new IntersectionObserver(
        (entries) => {
            if (entries.some((entry) => entry.isIntersecting)) appendMore();
        },
        { root: grid, rootMargin: "600px" }
    );
    const sentinel = el("div");
    sentinel.style.cssText = "grid-column:1/-1;height:1px";

    function pixelsForThumb() {
        return state.size * Math.min(window.devicePixelRatio || 1, 2);
    }

    function makeCell(item) {
        const cell = el("button", "bgal-cell");
        cell.type = "button";
        const thumb = el("div", "bgal-thumb");
        const name = el("div", "bgal-name", item.name);
        cell.title = item.name;
        if (item.kind === "folder") {
            cell.classList.add("bgal-folder");
            thumb.appendChild(el("div", "bgal-icon", "📁"));
            cell.addEventListener("click", () => {
                if (!guarded()) go(joinPath(state.subfolder, item.name));
            });
        } else {
            const path = joinPath(state.subfolder, item.name);
            if (path === state.currentPath) cell.classList.add("current");
            const img = el("img");
            img.loading = "lazy";
            img.decoding = "async";
            img.alt = "";
            img.draggable = false;
            img.dataset.name = item.name;
            img.dataset.stamp = String(Math.round(item.mtime || 0));
            img.src = thumbUrl(state.subfolder, item.name, thumbBucket(pixelsForThumb()), img.dataset.stamp);
            img.addEventListener("error", () => {
                img.remove();
                thumb.appendChild(el("div", "bgal-icon", "⚠️"));
            });
            thumb.appendChild(img);
            cell.addEventListener("click", () => {
                if (!guarded()) choose(path);
            });
        }
        cell.append(thumb, name);
        return cell;
    }

    function appendMore() {
        if (state.rendered >= state.visible.length) return;
        observer.unobserve(sentinel);
        sentinel.remove();
        const next = state.visible.slice(state.rendered, state.rendered + CHUNK);
        grid.append(...next.map(makeCell));
        state.rendered += next.length;
        if (state.rendered < state.visible.length) {
            grid.appendChild(sentinel);
            observer.observe(sentinel);
        }
    }

    function render() {
        const query = state.query.trim().toLowerCase();
        const match = (name) => !query || name.toLowerCase().includes(query);
        const folders = state.folders.filter(match).map((name) => ({ kind: "folder", name }));
        const files = state.files
            .filter((file) => match(file.name))
            .sort(SORTS[state.sort])
            .map((file) => ({ kind: "file", ...file }));
        state.visible = [...folders, ...files];
        state.rendered = 0;
        observer.unobserve(sentinel);
        grid.replaceChildren();
        if (state.loading) {
            grid.appendChild(el("div", "bgal-note", "Loading…"));
        } else if (!state.visible.length) {
            const empty = !state.folders.length && !state.files.length;
            grid.appendChild(el("div", "bgal-note", empty ? "This folder has no images." : "Nothing matches “" + state.query + "”."));
        } else {
            appendMore();
            // the selected image must exist in the DOM to be highlighted and scrolled to,
            // however far down the list it is
            const currentIndex = state.visible.findIndex(
                (item) => item.kind === "file" && joinPath(state.subfolder, item.name) === state.currentPath
            );
            while (currentIndex >= state.rendered && state.rendered < state.visible.length) appendMore();
        }
        foot.textContent =
            state.files.length + " image" + (state.files.length === 1 ? "" : "s") +
            (state.folders.length ? " · " + state.folders.length + " folder" + (state.folders.length === 1 ? "" : "s") : "") +
            (query ? " · " + files.length + " shown" : "") +
            (state.truncated ? " · list cut off, use search or subfolders" : "") +
            (state.currentPath ? " · selected: " + state.currentPath : "");
    }

    function renderCrumbs() {
        crumbs.replaceChildren();
        const segments = state.subfolder ? state.subfolder.split("/") : [];
        const add = (label, path, last) => {
            const button = el("button", "bgal-btn" + (last ? " on" : ""), label);
            button.type = "button";
            button.addEventListener("click", () => {
                if (!guarded() && path !== state.subfolder) go(path);
            });
            crumbs.appendChild(button);
        };
        add("🏠 input", "", segments.length === 0);
        segments.forEach((segment, index) => add(segment, segments.slice(0, index + 1).join("/"), index === segments.length - 1));
        crumbs.scrollLeft = crumbs.scrollWidth;
    }

    let navigation = 0;
    async function go(subfolder) {
        const id = ++navigation;
        state.subfolder = subfolder;
        state.loading = true;
        renderCrumbs();
        render();
        try {
            const data = await fetchListing(subfolder);
            if (id !== navigation || closed) return;
            state.folders = data.folders;
            state.files = data.files;
            state.truncated = !!data.truncated;
            state.loading = false;
            render();
            grid.scrollTop = 0;
            const current = grid.querySelector(".bgal-cell.current");
            if (current) current.scrollIntoView({ block: "center" });
        } catch (e) {
            if (id !== navigation || closed) return;
            state.loading = false;
            state.folders = [];
            state.files = [];
            grid.replaceChildren(el("div", "bgal-note", "Could not load this folder: " + e.message));
            foot.textContent = "";
        }
    }

    function setSize(px, commit) {
        state.size = px;
        grid.style.setProperty("--bgal-size", px + "px");
        if (commit) {
            savePrefs({ ...loadPrefs(), size: px, sort: state.sort });
            // a bigger cell may want a sharper thumbnail bucket
            const bucket = thumbBucket(pixelsForThumb());
            for (const img of grid.querySelectorAll("img[data-name]")) {
                img.src = thumbUrl(state.subfolder, img.dataset.name, bucket, img.dataset.stamp);
            }
        }
    }
    grid.style.setProperty("--bgal-size", state.size + "px");
    range.addEventListener("input", () => setSize(Number(range.value), false));
    range.addEventListener("change", () => setSize(Number(range.value), true));

    sort.addEventListener("change", () => {
        state.sort = sort.value;
        savePrefs({ ...loadPrefs(), size: state.size, sort: state.sort });
        render();
    });
    search.addEventListener("input", () => {
        state.query = search.value;
        render();
    });

    uploadButton.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", async () => {
        const picked = [...fileInput.files];
        fileInput.value = "";
        if (!picked.length) return;
        foot.textContent = "Uploading " + picked.length + " file" + (picked.length === 1 ? "" : "s") + "…";
        const uploaded = [];
        try {
            for (const file of picked) uploaded.push(await uploadToInput(file, state.subfolder));
        } catch (e) {
            foot.textContent = e.message;
            return;
        }
        if (uploaded.length === 1) choose(uploaded[0]);
        else go(state.subfolder);
    });

    document.body.appendChild(overlay);
    go(state.subfolder);
    return { close };
}
