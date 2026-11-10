// The screen where a model is chosen: every model file of the model folders (checkpoints, diffusion models, text
// encoders, VAEs, CLIP vision, GGUF and pickle files too) as a card, filters by the kind of file, the model family
// and the format, a search over names and families, and a panel with the characteristics of the selected one.
// Shared module for js/model_selector.js, with no extension of its own.
//
// Like the other pickers of this pack it is opened from a real DOM <button> and ignores taps in its first
// moments, so the finger that opened it cannot choose anything.

const TAP_GUARD_MS = 350;
const LIST_TTL_MS = 30000;
const PREFS_KEY = "bart_model_picker_prefs";
const KINDS = ["checkpoint", "diffusion model", "text encoder", "VAE", "CLIP vision"];
const KIND_ICON = { "checkpoint": "📦", "diffusion model": "🧠", "text encoder": "🔤", "VAE": "🖼", "CLIP vision": "👁", unknown: "❔" };

let listCache = { at: 0, promise: null };

export function fetchModels(force = false) {
    if (!force && listCache.promise && Date.now() - listCache.at < LIST_TTL_MS) return listCache.promise;
    const promise = fetch("/model_selector/list").then(async (resp) => {
        const data = await resp.json();
        if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
        return data;
    });
    listCache = { at: Date.now(), promise };
    promise.catch(() => {
        if (listCache.promise === promise) listCache = { at: 0, promise: null };
    });
    return promise;
}

async function fetchInfo(id) {
    const resp = await fetch("/model_selector/info?" + new URLSearchParams({ id }).toString());
    const data = await resp.json();
    if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
    return data;
}

function loadPrefs() {
    try {
        return JSON.parse(localStorage.getItem(PREFS_KEY) || "{}") || {};
    } catch (e) {
        return {};
    }
}

function savePrefs(prefs) {
    try {
        localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
    } catch (e) {
        /* private mode: the screen just forgets its sort order */
    }
}

export function formatSize(bytes) {
    if (!bytes) return "";
    if (bytes >= 2 ** 30) return (bytes / 2 ** 30).toFixed(bytes >= 10 * 2 ** 30 ? 0 : 1) + " GB";
    if (bytes >= 2 ** 20) return (bytes / 2 ** 20).toFixed(0) + " MB";
    return Math.max(1, Math.round(bytes / 1024)) + " KB";
}

// a model matches when EVERY word of the query is found in its path, kind, family, format or precision
export function matchesQuery(model, query) {
    const words = (query || "").toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length) return true;
    const haystack = [model.name, model.kind, model.family, model.format, model.precision, model.quant, model.folder]
        .join("\n")
        .toLowerCase();
    return words.every((word) => haystack.includes(word));
}

export function kindOf(model) {
    return model.kind || "unknown";
}

export function familyOf(model) {
    return model.family || "unknown";
}

const SORTS = {
    name: (a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" }),
    newest: (a, b) => b.mtime - a.mtime || a.name.localeCompare(b.name),
    size: (a, b) => b.size - a.size || a.name.localeCompare(b.name),
};

const STYLE = `
.bmp-overlay{position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,.86);display:flex;justify-content:center;
  font-family:system-ui,-apple-system,sans-serif;color:#eee}
.bmp-panel{display:flex;flex-direction:column;width:100%;height:100%;max-width:1400px;background:#1c1c1e;min-height:0}
@media (min-width:900px){.bmp-overlay{padding:3vh 3vw}.bmp-panel{border-radius:14px;overflow:hidden;box-shadow:0 10px 50px rgba(0,0,0,.6)}}
.bmp-head,.bmp-filters{display:flex;align-items:center;gap:8px;padding:8px 10px;border-bottom:1px solid #333}
.bmp-head{padding-top:calc(8px + env(safe-area-inset-top))}
.bmp-filters{flex-wrap:wrap}
.bmp-row{display:flex;gap:6px;flex-wrap:wrap;align-items:center;width:100%}
.bmp-row .label{font-size:12px;opacity:.6;min-width:54px}
.bmp-btn{min-height:44px;min-width:44px;padding:0 14px;font-size:15px;border-radius:10px;border:1px solid #484848;background:#2c2c2e;
  color:#eee;cursor:pointer;touch-action:manipulation;-webkit-tap-highlight-color:transparent;white-space:nowrap}
.bmp-btn:active{background:#3a3a3c}
.bmp-btn.on{background:#1d4f86;border-color:#4aa3ff}
.bmp-btn.primary{background:#1d6f3a;border-color:#4ad37a}
.bmp-chip{min-height:34px;padding:0 12px;font-size:14px;border-radius:17px}
.bmp-head input[type=search],.bmp-filters select{font-size:16px;min-height:44px;padding:0 12px;border-radius:10px;
  border:1px solid #484848;background:#2c2c2e;color:#eee;box-sizing:border-box}
.bmp-head input[type=search]{flex:1;min-width:0}
.bmp-body{flex:1;min-height:0;display:flex;position:relative}
.bmp-list{flex:1;min-width:0;overflow-y:auto;-webkit-overflow-scrolling:touch;overscroll-behavior:contain;padding:10px;
  display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));grid-auto-rows:max-content;gap:10px;align-content:start}
.bmp-card{display:flex;gap:10px;padding:10px;background:#262628;border:2px solid transparent;border-radius:10px;color:inherit;
  cursor:pointer;text-align:left;touch-action:manipulation;-webkit-tap-highlight-color:transparent;font:inherit;
  user-select:none;-webkit-user-select:none}
.bmp-card.current{border-color:#4ad37a}
.bmp-card.selected{border-color:#4aa3ff}
.bmp-icon{font-size:26px;line-height:1;width:34px;text-align:center;flex:0 0 auto}
.bmp-card .t{font-size:13px;font-weight:600;word-break:break-all;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.bmp-card .s{margin-top:4px;font-size:12px;opacity:.8;display:flex;flex-wrap:wrap;gap:4px 6px}
.bmp-badge{background:#34343a;border-radius:6px;padding:0 6px}
.bmp-badge.out{background:#1d4f86}
.bmp-detail{width:430px;max-width:46%;border-left:1px solid #333;overflow-y:auto;-webkit-overflow-scrolling:touch;padding:12px;font-size:14px;line-height:1.4}
@media (max-width:899px){.bmp-detail{position:absolute;inset:0;width:auto;max-width:none;background:#1c1c1e;z-index:2}.bmp-detail.hidden{display:none}}
@media (max-width:520px){.bmp-list{grid-template-columns:minmax(0,1fr)}}
.bmp-detail h3{margin:0 0 4px;font-size:16px;word-break:break-all}
.bmp-detail h4{margin:14px 0 4px;font-size:12px;text-transform:uppercase;letter-spacing:.06em;opacity:.65}
.bmp-kv{display:grid;grid-template-columns:auto 1fr;gap:2px 12px}
.bmp-kv span:nth-child(odd){opacity:.6}
.bmp-kv span:nth-child(even){word-break:break-word}
.bmp-muted{opacity:.6}
.bmp-warn{color:#f0b44c}
.bmp-empty{grid-column:1/-1;padding:24px;text-align:center;opacity:.7}
.bmp-foot{padding:6px 12px calc(6px + env(safe-area-inset-bottom));font-size:12px;opacity:.75;border-top:1px solid #333}
`;

function injectStyle() {
    if (document.getElementById("bmp-style")) return;
    const style = document.createElement("style");
    style.id = "bmp-style";
    style.textContent = STYLE;
    document.head.appendChild(style);
}

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

let openPicker = null;

/** Open the screen. `current` is the id the node holds (highlighted); `onSelect(id, info)` gets the chosen one. */
export function openModelPicker({ current = "", onSelect }) {
    if (openPicker) openPicker.close();
    injectStyle();
    let guardFrom = performance.now();
    const guarded = () => performance.now() - guardFrom < TAP_GUARD_MS;
    const prefs = loadPrefs();
    const state = {
        models: [],
        kind: "",
        family: "",
        format: "",
        query: "",
        sort: SORTS[prefs.sort] ? prefs.sort : "name",
        selected: null,
        loading: true,
        error: "",
    };

    const overlay = el("div", "bmp-overlay");
    const panel = el("div", "bmp-panel");
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "Choose a model");
    const closeButton = el("button", "bmp-btn", "✕");
    closeButton.type = "button";
    const search = el("input");
    search.type = "search";
    search.placeholder = "Search by name, family, format";
    search.autocomplete = "off";
    const refresh = el("button", "bmp-btn", "⟳");
    refresh.type = "button";
    refresh.title = "Rescan the model folders";
    const head = el("div", "bmp-head");
    head.append(closeButton, search, refresh);

    const kindRow = el("div", "bmp-row");
    const familyRow = el("div", "bmp-row");
    const formatRow = el("div", "bmp-row");
    const sort = el("select");
    for (const [value, label] of [["name", "Name"], ["newest", "Newest"], ["size", "Largest"]]) {
        const option = el("option", "", label);
        option.value = value;
        sort.appendChild(option);
    }
    sort.value = state.sort;
    formatRow.appendChild(sort);
    const filters = el("div", "bmp-filters");
    filters.append(kindRow, familyRow, formatRow);

    const list = el("div", "bmp-list");
    const detail = el("div", "bmp-detail hidden");
    const body = el("div", "bmp-body");
    body.append(list, detail);
    const foot = el("div", "bmp-foot");
    panel.append(head, filters, body, foot);
    overlay.appendChild(panel);

    let closed = false;
    function close() {
        if (closed) return;
        closed = true;
        if (openPicker && openPicker.close === close) openPicker = null;
        document.removeEventListener("keydown", onKey, true);
        overlay.remove();
    }
    function choose(model, info) {
        close();
        if (onSelect) onSelect(model.id, info || model);
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
    overlay.addEventListener("click", (event) => {
        if (event.target === overlay && !guarded()) close();
    });

    function visible() {
        return state.models
            .filter(
                (m) =>
                    (!state.kind || kindOf(m) === state.kind) &&
                    (!state.family || familyOf(m) === state.family) &&
                    (!state.format || m.format === state.format) &&
                    matchesQuery(m, state.query)
            )
            .sort(SORTS[state.sort]);
    }

    function chipRow(row, title, entries, key) {
        row.replaceChildren(el("span", "label", title));
        const make = (label, value) => {
            const chip = el("button", "bmp-btn bmp-chip" + (state[key] === value ? " on" : ""), label);
            chip.type = "button";
            chip.addEventListener("click", () => {
                state[key] = value;
                renderFilters();
                renderList();
            });
            row.appendChild(chip);
        };
        make(`All (${entries.reduce((sum, [, count]) => sum + count, 0)})`, "");
        for (const [value, count] of entries) make(`${value} (${count})`, value);
    }

    function counts(pick, order) {
        const map = new Map();
        for (const model of state.models) map.set(pick(model), (map.get(pick(model)) || 0) + 1);
        const entries = [...map.entries()];
        if (order) return entries.sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]));
        return entries.sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    }

    function renderFilters() {
        chipRow(kindRow, "Type", counts(kindOf, [...KINDS, "unknown"]), "kind");
        chipRow(familyRow, "Model", counts(familyOf), "family");
        chipRow(formatRow, "Format", counts((m) => m.format || "?"), "format");
        formatRow.appendChild(sort);
    }

    function makeCard(model) {
        const card = el("button", "bmp-card");
        card.type = "button";
        if (model.id === current) card.classList.add("current");
        if (state.selected && state.selected.id === model.id) card.classList.add("selected");
        card.title = model.id;
        card.appendChild(el("div", "bmp-icon", KIND_ICON[kindOf(model)] || "❔"));
        const text = el("div");
        text.appendChild(el("div", "t", model.name));
        const sub = el("div", "s");
        sub.appendChild(el("span", "bmp-badge", kindOf(model)));
        if (model.family) sub.appendChild(el("span", "bmp-badge", model.family));
        sub.appendChild(el("span", "", [model.format, model.precision, model.params_text, formatSize(model.size)].filter(Boolean).join(" · ")));
        text.appendChild(sub);
        const gives = el("div", "s");
        for (const out of model.outputs || []) gives.appendChild(el("span", "bmp-badge out", out));
        text.appendChild(gives);
        card.appendChild(text);
        card.addEventListener("click", (event) => {
            if (!guarded() && event.detail <= 1) select(model);
        });
        card.addEventListener("dblclick", () => {
            if (!guarded()) choose(model);
        });
        return card;
    }

    function renderList() {
        const shown = visible();
        list.replaceChildren();
        if (state.loading) list.appendChild(el("div", "bmp-empty", "Scanning the model folders…"));
        else if (state.error) list.appendChild(el("div", "bmp-empty", "Could not read the models: " + state.error));
        else if (!state.models.length) list.appendChild(el("div", "bmp-empty", "No model files found in the model folders."));
        else if (!shown.length) list.appendChild(el("div", "bmp-empty", "Nothing matches."));
        for (const model of shown) list.appendChild(makeCard(model));
        foot.textContent = state.loading ? "" : `${shown.length} of ${state.models.length} models`;
    }

    // ---- the characteristics panel -----------------------------------------------------------
    let detailToken = 0;
    async function select(model) {
        state.selected = model;
        renderList();
        const token = ++detailToken;
        detail.classList.remove("hidden");
        detail.replaceChildren(el("div", "bmp-muted", "Reading…"));
        try {
            const info = await fetchInfo(model.id);
            if (token !== detailToken || closed) return;
            renderDetail(info);
        } catch (e) {
            if (token !== detailToken || closed) return;
            detail.replaceChildren(el("div", "bmp-muted", "Could not read this model: " + e.message));
        }
    }

    function section(title, content) {
        detail.append(el("h4", "", title), content);
    }

    function kv(pairs) {
        const grid = el("div", "bmp-kv");
        for (const [key, value] of pairs) grid.append(el("span", "", key), el("span", "", String(value)));
        return grid;
    }

    function renderDetail(info) {
        detail.replaceChildren();
        const back = el("button", "bmp-btn", "← Back");
        back.type = "button";
        back.style.display = window.matchMedia("(min-width: 900px)").matches ? "none" : "";
        back.addEventListener("click", () => detail.classList.add("hidden"));
        detail.appendChild(back);
        detail.appendChild(el("h3", "", `${KIND_ICON[kindOf(info)] || ""} ${info.stem}`));
        detail.appendChild(el("div", "bmp-muted", info.location));

        const use = el("button", "bmp-btn primary", current === info.id ? "Keep this model" : "Use this model");
        use.type = "button";
        use.style.cssText = "width:100%;margin-top:10px";
        use.disabled = info.can_load === false || info.kind === "unknown";
        use.addEventListener("click", () => {
            if (!guarded()) choose(info, info);
        });
        detail.appendChild(use);
        if (info.can_load === false) detail.appendChild(el("div", "bmp-warn", "⚠ Needs " + info.needs + "; this file cannot be used until then."));

        const gives = el("div", "bmp-row");
        for (const out of info.outputs || []) gives.appendChild(el("span", "bmp-badge out", out));
        if (!(info.outputs || []).length) gives.appendChild(el("span", "bmp-muted", "nothing: the kind of this file is not recognised"));
        section("Gives on its outputs", gives);

        const facts = [["type", kindOf(info) + (info.kind_source === "folder" ? " (from its folder)" : "")]];
        facts.push(["model", info.family || "unknown"]);
        facts.push(["format", info.format || "?"]);
        if (info.precision) facts.push([info.format === "gguf" ? "quantisation" : "precision", info.precision]);
        if (info.params_text) facts.push(["parameters", info.params_text]);
        if (info.tensors) facts.push(["tensors", info.tensors]);
        facts.push(["size", formatSize(info.size)]);
        facts.push(["folder", info.folder]);
        if (info.mtime) facts.push(["modified", new Date(info.mtime * 1000).toLocaleDateString()]);
        section("Characteristics", kv(facts));

        if (info.needs && info.can_load !== false) section("Needs", el("div", "bmp-muted", info.needs));
        const extras = Object.entries(info.extras || {});
        if (extras.length) section("Metadata", kv(extras));
        if (!info.readable && info.format !== "ckpt" && info.format !== "pt" && info.format !== "pth" && info.format !== "bin") {
            section("Note", el("div", "bmp-muted", "The header of this file could not be read: type and model are guessed from its folder and name."));
        }
    }

    // ---- wiring -------------------------------------------------------------------------------
    search.addEventListener("input", () => {
        state.query = search.value;
        renderList();
    });
    sort.addEventListener("change", () => {
        state.sort = sort.value;
        savePrefs({ ...loadPrefs(), sort: state.sort });
        renderList();
    });
    async function load(force) {
        state.loading = true;
        state.error = "";
        renderList();
        try {
            const data = await fetchModels(force);
            if (closed) return;
            state.models = data.models;
        } catch (e) {
            if (closed) return;
            state.error = e.message;
        }
        state.loading = false;
        renderFilters();
        renderList();
        const here = state.models.find((m) => m.id === current);
        if (here) {
            if (window.matchMedia("(min-width: 900px)").matches) select(here);
            const card = list.querySelector(".bmp-card.current");
            if (card) card.scrollIntoView({ block: "center" });
        }
    }
    refresh.addEventListener("click", () => {
        if (!guarded()) load(true);
    });

    document.body.appendChild(overlay);
    overlay.tabIndex = -1;
    search.focus({ preventScroll: true });
    openPicker = { close };
    renderFilters();
    load(false);
    return { close };
}
