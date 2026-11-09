// The screen where a LoRA is chosen: every file found in the loras folders as a card (preview, name, model
// family, trigger words), a filter by model family, a search over names and trigger words, and a detail
// panel with everything known about the selected one (triggers, recommended settings, training data, your own
// notes). Shared module for js/lora_selector.js, with no extension of its own.
//
// Like the image gallery it is opened from a real DOM <button> and ignores taps in its first moments, so
// the finger that opened it cannot choose anything.

const TAP_GUARD_MS = 350;
const LIST_TTL_MS = 30000;
const PREFS_KEY = "bart_lora_picker_prefs";

let listCache = { at: 0, promise: null };

export function fetchLoras(force = false) {
    if (!force && listCache.promise && Date.now() - listCache.at < LIST_TTL_MS) return listCache.promise;
    const promise = fetch("/lora_selector/list").then(async (resp) => {
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

async function fetchInfo(name) {
    const resp = await fetch("/lora_selector/info?" + new URLSearchParams({ name }).toString());
    const data = await resp.json();
    if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
    return data;
}

async function saveNote(name, note) {
    const resp = await fetch("/lora_selector/notes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, ...note }),
    });
    const data = await resp.json();
    if (!resp.ok || data.error) throw new Error(data.error || "HTTP " + resp.status);
    return data;
}

export function previewUrl(name, size, stamp) {
    const params = new URLSearchParams({ name, size: String(size) });
    if (stamp) params.set("t", String(Math.round(stamp)));
    return "/lora_selector/preview?" + params.toString();
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
    if (bytes >= 2 ** 30) return (bytes / 2 ** 30).toFixed(1) + " GB";
    if (bytes >= 2 ** 20) return (bytes / 2 ** 20).toFixed(0) + " MB";
    return Math.max(1, Math.round(bytes / 1024)) + " KB";
}

// a LoRA matches when EVERY word of the query is found in its name, family, base model, trigger words
// or frequent training tags (case does not matter)
export function matchesQuery(lora, query) {
    const words = (query || "").toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length) return true;
    const haystack = [lora.name, lora.family, lora.base_model, ...(lora.triggers || []), ...(lora.frequent_tags || [])]
        .join("\n")
        .toLowerCase();
    return words.every((word) => haystack.includes(word));
}

export function familyOf(lora) {
    return lora.family || "unknown";
}

const SORTS = {
    name: (a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" }),
    newest: (a, b) => b.mtime - a.mtime || a.name.localeCompare(b.name),
    size: (a, b) => b.size - a.size || a.name.localeCompare(b.name),
};

const STYLE = `
.blp-overlay{position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,.86);display:flex;justify-content:center;
  font-family:system-ui,-apple-system,sans-serif;color:#eee}
.blp-panel{display:flex;flex-direction:column;width:100%;height:100%;max-width:1400px;background:#1c1c1e;min-height:0}
@media (min-width:900px){.blp-overlay{padding:3vh 3vw}.blp-panel{border-radius:14px;overflow:hidden;box-shadow:0 10px 50px rgba(0,0,0,.6)}}
.blp-head,.blp-filters{display:flex;align-items:center;gap:8px;padding:8px 10px;border-bottom:1px solid #333}
.blp-head{padding-top:calc(8px + env(safe-area-inset-top))}
.blp-filters{flex-wrap:wrap}
.blp-btn{min-height:44px;min-width:44px;padding:0 14px;font-size:15px;border-radius:10px;border:1px solid #484848;background:#2c2c2e;
  color:#eee;cursor:pointer;touch-action:manipulation;-webkit-tap-highlight-color:transparent;white-space:nowrap}
.blp-btn:active{background:#3a3a3c}
.blp-btn.on{background:#1d4f86;border-color:#4aa3ff}
.blp-btn.primary{background:#1d6f3a;border-color:#4ad37a}
.blp-chip{min-height:36px;padding:0 12px;font-size:14px;border-radius:18px}
.blp-head input[type=search],.blp-filters select,.blp-note input,.blp-note textarea{font-size:16px;min-height:44px;padding:0 12px;border-radius:10px;
  border:1px solid #484848;background:#2c2c2e;color:#eee;box-sizing:border-box}
.blp-head input[type=search]{flex:1;min-width:0}
.blp-chips{display:flex;gap:6px;flex-wrap:wrap;flex:1}
.blp-body{flex:1;min-height:0;display:flex}
.blp-list{flex:1;min-width:0;overflow-y:auto;-webkit-overflow-scrolling:touch;overscroll-behavior:contain;padding:10px;
  display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));grid-auto-rows:max-content;gap:10px;align-content:start}
.blp-card{display:flex;flex-direction:column;padding:0;background:#262628;border:2px solid transparent;border-radius:10px;color:inherit;
  cursor:pointer;text-align:left;touch-action:manipulation;-webkit-tap-highlight-color:transparent;overflow:hidden;font:inherit;
  user-select:none;-webkit-user-select:none}
.blp-card.current{border-color:#4ad37a}
.blp-card.selected{border-color:#4aa3ff}
.blp-thumb{position:relative;width:100%;height:0;padding-top:70%;background:#111}
.blp-thumb img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.blp-ph{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:26px;opacity:.5}
.blp-card .t{padding:6px 8px 0;font-size:13px;font-weight:600;word-break:break-all;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.blp-card .s{padding:2px 8px 8px;font-size:12px;opacity:.75;display:flex;flex-wrap:wrap;gap:4px 8px}
.blp-badge{background:#34343a;border-radius:6px;padding:0 6px}
@media (max-width:520px){.blp-list{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;padding:8px}.blp-card .s{font-size:11px}}
.blp-detail{width:420px;max-width:45%;border-left:1px solid #333;overflow-y:auto;-webkit-overflow-scrolling:touch;padding:12px;font-size:14px;line-height:1.4}
@media (max-width:899px){.blp-detail{position:absolute;inset:0;width:auto;max-width:none;background:#1c1c1e;z-index:2}.blp-detail.hidden{display:none}}
.blp-detail h3{margin:0 0 4px;font-size:16px;word-break:break-all}
.blp-detail h4{margin:14px 0 4px;font-size:12px;text-transform:uppercase;letter-spacing:.06em;opacity:.65}
.blp-detail img.big{width:100%;max-height:240px;object-fit:contain;background:#111;border-radius:8px}
.blp-words{display:flex;flex-wrap:wrap;gap:6px}
.blp-word{border:1px solid #484848;background:#2c2c2e;color:#eee;border-radius:14px;padding:4px 10px;font-size:13px;cursor:pointer;min-height:30px}
.blp-word:active{background:#3a3a3c}
.blp-kv{display:grid;grid-template-columns:auto 1fr;gap:2px 10px}
.blp-kv span:nth-child(odd){opacity:.6}
.blp-note{display:flex;flex-direction:column;gap:6px}
.blp-note input,.blp-note textarea{padding:8px 12px;width:100%}
.blp-muted{opacity:.6}
.blp-empty{grid-column:1/-1;padding:24px;text-align:center;opacity:.7}
.blp-foot{padding:6px 12px calc(6px + env(safe-area-inset-bottom));font-size:12px;opacity:.75;border-top:1px solid #333}
`;

function injectStyle() {
    if (document.getElementById("blp-style")) return;
    const style = document.createElement("style");
    style.id = "blp-style";
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

/**
 * Open the screen. `current` is the LoRA the row already holds (highlighted), `taken` the names already on
 * the node; `onSelect(name, info)` gets the chosen one (info = what the server knows, for a default strength).
 */
export function openLoraPicker({ current = "", taken = [], onSelect }) {
    if (openPicker) openPicker.close();
    injectStyle();
    let guardFrom = performance.now();
    const guarded = () => performance.now() - guardFrom < TAP_GUARD_MS;
    const prefs = loadPrefs();
    const state = {
        loras: [],
        family: "",
        query: "",
        sort: SORTS[prefs.sort] ? prefs.sort : "name",
        selected: null,
        loading: true,
        error: "",
    };

    const overlay = el("div", "blp-overlay");
    const panel = el("div", "blp-panel");
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "Choose a LoRA");
    const closeButton = el("button", "blp-btn", "✕");
    closeButton.type = "button";
    const search = el("input");
    search.type = "search";
    search.placeholder = "Search by name or trigger word";
    search.autocomplete = "off";
    const refresh = el("button", "blp-btn", "⟳");
    refresh.type = "button";
    refresh.title = "Rescan the loras folders";
    const head = el("div", "blp-head");
    head.append(closeButton, search, refresh);

    const chips = el("div", "blp-chips");
    const sort = el("select");
    for (const [value, label] of [["name", "Name"], ["newest", "Newest"], ["size", "Largest"]]) {
        const option = el("option", "", label);
        option.value = value;
        sort.appendChild(option);
    }
    sort.value = state.sort;
    const filters = el("div", "blp-filters");
    filters.append(chips, sort);

    const list = el("div", "blp-list");
    const detail = el("div", "blp-detail hidden");
    const body = el("div", "blp-body");
    body.style.position = "relative";
    body.append(list, detail);
    const foot = el("div", "blp-foot");
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
    function choose(lora, info) {
        close();
        if (onSelect) onSelect(lora.name, info || lora);
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
        return state.loras
            .filter((lora) => (!state.family || familyOf(lora) === state.family) && matchesQuery(lora, state.query))
            .sort(SORTS[state.sort]);
    }

    function renderChips() {
        const counts = new Map();
        for (const lora of state.loras) counts.set(familyOf(lora), (counts.get(familyOf(lora)) || 0) + 1);
        const families = [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
        chips.replaceChildren();
        const make = (label, value) => {
            const chip = el("button", "blp-btn blp-chip" + (state.family === value ? " on" : ""), label);
            chip.type = "button";
            chip.addEventListener("click", () => {
                state.family = value;
                renderChips();
                renderList();
            });
            chips.appendChild(chip);
        };
        make(`All (${state.loras.length})`, "");
        for (const [family, count] of families) make(`${family} (${count})`, family);
    }

    function makeCard(lora) {
        const card = el("button", "blp-card");
        card.type = "button";
        if (lora.name === current) card.classList.add("current");
        if (state.selected && state.selected.name === lora.name) card.classList.add("selected");
        card.title = lora.name;
        const thumb = el("div", "blp-thumb");
        if (lora.has_preview) {
            const img = el("img");
            img.loading = "lazy";
            img.decoding = "async";
            img.alt = "";
            img.draggable = false;
            img.src = previewUrl(lora.name, 256, lora.mtime);
            img.addEventListener("error", () => {
                img.remove();
                thumb.appendChild(el("div", "blp-ph", "🎨"));
            });
            thumb.appendChild(img);
        } else {
            thumb.appendChild(el("div", "blp-ph", "🎨"));
        }
        const title = el("div", "t", lora.file);
        const sub = el("div", "s");
        sub.appendChild(el("span", "blp-badge", familyOf(lora)));
        if (lora.size) sub.appendChild(el("span", "", formatSize(lora.size)));
        if (taken.includes(lora.name) && lora.name !== current) sub.appendChild(el("span", "", "✓ on the node"));
        if (lora.triggers && lora.triggers.length) {
            const words = lora.triggers.slice(0, 3).join(", ") + (lora.triggers.length > 3 ? "…" : "");
            sub.appendChild(el("span", "", "🔑 " + words));
        }
        card.append(thumb, title, sub);
        card.addEventListener("click", (event) => {
            if (!guarded() && event.detail <= 1) select(lora);
        });
        card.addEventListener("dblclick", () => {
            if (!guarded()) choose(lora);
        });
        return card;
    }

    function renderList() {
        const shown = visible();
        list.replaceChildren();
        if (state.loading) list.appendChild(el("div", "blp-empty", "Loading…"));
        else if (state.error) list.appendChild(el("div", "blp-empty", "Could not read the LoRAs: " + state.error));
        else if (!state.loras.length) list.appendChild(el("div", "blp-empty", "No LoRA files found in the loras folders."));
        else if (!shown.length) list.appendChild(el("div", "blp-empty", "Nothing matches."));
        for (const lora of shown) list.appendChild(makeCard(lora));
        foot.textContent = state.loading ? "" : `${shown.length} of ${state.loras.length} LoRAs`;
    }

    // ---- the detail panel ----------------------------------------------------------------------
    let detailToken = 0;
    async function select(lora) {
        state.selected = lora;
        renderList();
        const token = ++detailToken;
        detail.classList.remove("hidden");
        detail.replaceChildren(el("div", "blp-muted", "Loading…"));
        try {
            const info = await fetchInfo(lora.name);
            if (token !== detailToken || closed) return;
            renderDetail(info);
        } catch (e) {
            if (token !== detailToken || closed) return;
            detail.replaceChildren(el("div", "blp-muted", "Could not read this LoRA: " + e.message));
        }
    }

    function words(list, onClick) {
        const box = el("div", "blp-words");
        for (const word of list) {
            const chip = el("button", "blp-word", word);
            chip.type = "button";
            chip.title = "Copy";
            chip.addEventListener("click", () => onClick(word, chip));
            box.appendChild(chip);
        }
        return box;
    }

    async function copy(text, chip) {
        try {
            await navigator.clipboard.writeText(text);
            const old = chip.textContent;
            chip.textContent = "copied";
            setTimeout(() => (chip.textContent = old), 900);
        } catch (e) {
            window.prompt("Copy:", text);
        }
    }

    function section(title, content) {
        detail.append(el("h4", "", title), content);
    }

    function kv(pairs) {
        const grid = el("div", "blp-kv");
        for (const [key, value] of pairs) grid.append(el("span", "", key), el("span", "", String(value)));
        return grid;
    }

    function renderDetail(info) {
        detail.replaceChildren();
        const back = el("button", "blp-btn", "← Back");
        back.type = "button";
        back.style.display = window.matchMedia("(min-width: 900px)").matches ? "none" : "";
        back.addEventListener("click", () => detail.classList.add("hidden"));
        detail.appendChild(back);
        if (info.has_preview) {
            const img = el("img", "big");
            img.alt = "";
            img.src = previewUrl(info.name, 512, info.mtime);
            detail.appendChild(img);
        }
        detail.appendChild(el("h3", "", info.file));
        detail.appendChild(el("div", "blp-muted", info.name));
        const facts = [["model", info.family || "unknown"]];
        if (info.base_model && info.base_model !== info.family) facts.push(["base", info.base_model]);
        facts.push(["file", `${info.format || "?"} · ${formatSize(info.size)}`]);
        if (!info.readable) facts.push(["metadata", "none (not a safetensors file)"]);
        detail.appendChild(kv(facts));

        const use = el("button", "blp-btn primary", current === info.name ? "Keep this LoRA" : "Use this LoRA");
        use.type = "button";
        use.style.cssText = "width:100%;margin-top:10px";
        use.addEventListener("click", () => {
            if (!guarded()) choose(info, info);
        });
        detail.appendChild(use);

        if (info.triggers.length) {
            section("Trigger words" + (info.triggers_source ? ` (${info.triggers_source})` : ""), words(info.triggers, (w, c) => copy(w, c)));
            const all = el("button", "blp-btn", "Copy all");
            all.type = "button";
            all.style.cssText = "margin-top:6px;min-height:36px";
            all.addEventListener("click", () => copy(info.triggers.join(", "), all));
            detail.appendChild(all);
        } else {
            section("Trigger words", el("div", "blp-muted", "None known. Add yours under My notes below."));
        }
        if (info.frequent_tags.length) {
            section("Frequent training tags", words(info.frequent_tags, (w, c) => copy(w, c)));
        }

        const recommended = [];
        if (info.strength) recommended.push(["strength", `${info.strength}` + (info.strength_source ? ` (${info.strength_source})` : "")]);
        for (const [key, value] of Object.entries(info.settings || {})) recommended.push([key, value]);
        if (info.negative) recommended.push(["negative", info.negative]);
        section("Recommended settings", recommended.length ? kv(recommended) : el("div", "blp-muted", "None known."));

        if (Object.keys(info.civitai || {}).length) section("Civitai", kv(Object.entries(info.civitai)));
        if (info.description) section("Description", el("div", "", info.description));
        if (Object.keys(info.training || {}).length) section("Training", kv(Object.entries(info.training)));

        // ---- the user's own notes
        const form = el("div", "blp-note");
        const triggers = el("input");
        triggers.placeholder = "trigger words, separated by commas";
        triggers.value = (info.notes.triggers || []).join(", ");
        const strength = el("input");
        strength.type = "number";
        strength.step = "0.05";
        strength.placeholder = "recommended strength";
        strength.value = info.notes.strength === null || info.notes.strength === undefined ? "" : info.notes.strength;
        const text = el("textarea");
        text.rows = 3;
        text.placeholder = "notes";
        text.value = info.notes.text || "";
        const status = el("div", "blp-muted");
        const save = el("button", "blp-btn", "Save my notes");
        save.type = "button";
        save.addEventListener("click", async () => {
            status.textContent = "saving…";
            try {
                await saveNote(info.name, { triggers: triggers.value, strength: strength.value, text: text.value });
                status.textContent = "saved";
                fetchLoras(true).then((data) => {
                    if (closed) return;
                    state.loras = data.loras;
                    renderChips();
                    renderList();
                }).catch(() => {});
            } catch (e) {
                status.textContent = "not saved: " + e.message;
            }
        });
        form.append(triggers, strength, text, save, status);
        section("My notes (kept in ComfyUI's user folder)", form);
    }

    // ---- wiring ---------------------------------------------------------------------------------
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
            const data = await fetchLoras(force);
            if (closed) return;
            state.loras = data.loras;
        } catch (e) {
            if (closed) return;
            state.error = e.message;
        }
        state.loading = false;
        renderChips();
        renderList();
        const here = state.loras.find((lora) => lora.name === current);
        if (here) {
            // wide screen: show the current one's details; on a phone they would cover the list
            if (window.matchMedia("(min-width: 900px)").matches) select(here);
            const card = list.querySelector(".blp-card.current");
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
    renderChips();
    load(false);
    return { close };
}
