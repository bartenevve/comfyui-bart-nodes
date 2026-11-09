import { app } from "../../scripts/app.js";
import { fetchLoras, openLoraPicker } from "./bart_lora_picker.js";

const NODE_NAME = "LoraSelector";
const MAX_ROWS = 64;

// hide a widget without removing it: an unknown type is not drawn, its value still serializes
function setWidgetHidden(widget, hidden) {
    if (hidden) {
        if (widget.origType === undefined) {
            widget.origType = widget.type;
            widget.origComputeSize = widget.computeSize;
        }
        widget.type = "lora_selector_hidden";
        widget.computeSize = () => [0, -4];
    } else if (widget.origType !== undefined) {
        widget.type = widget.origType;
        widget.computeSize = widget.origComputeSize;
        widget.origType = undefined;
    }
    const el = widget.element || widget.inputEl;
    if (el && el.style) el.style.display = hidden ? "none" : "";
    widget.hidden = hidden;
}

function button(label, extra = "") {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.style.cssText =
        "min-height:44px;padding:0 10px;font-size:15px;border-radius:10px;border:1px solid #555;background:#2c2c2e;color:#eee;" +
        "cursor:pointer;touch-action:manipulation;-webkit-tap-highlight-color:transparent;" + extra;
    return b;
}

function numberInput(placeholder) {
    const input = document.createElement("input");
    input.type = "number";
    input.step = "0.05";
    input.min = "-100";
    input.max = "100";
    input.placeholder = placeholder;
    input.style.cssText =
        "width:64px;min-height:44px;box-sizing:border-box;font-size:15px;text-align:center;border-radius:10px;" +
        "border:1px solid #555;background:#2c2c2e;color:#eee;padding:0 4px;";
    return input;
}

// the rows as the server stores them: nothing for the empty row at the end
function toStack(rows) {
    return rows
        .filter((row) => row.name)
        .map((row) => ({
            name: row.name,
            enabled: row.enabled,
            strength_model: row.strength_model,
            strength_clip: row.strength_clip,
        }));
}

function fromStack(text) {
    let data = [];
    try {
        data = JSON.parse(text || "[]");
    } catch (e) {
        data = [];
    }
    if (!Array.isArray(data)) data = [];
    return data
        .filter((row) => row && typeof row.name === "string" && row.name)
        .slice(0, MAX_ROWS)
        .map((row) => ({
            name: row.name,
            enabled: row.enabled !== false,
            strength_model: Number.isFinite(Number(row.strength_model)) ? Number(row.strength_model) : 1,
            strength_clip: row.strength_clip === null || row.strength_clip === undefined || row.strength_clip === "" ? null : Number(row.strength_clip),
        }));
}

app.registerExtension({
    name: "comfyui.lora_selector",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
            const node = this;
            const store = (node.widgets || []).find((w) => w.name === "loras");
            if (!store) {
                console.warn("LoraSelector: the loras widget was converted to an input; skipping the selector UI.");
                return result;
            }
            setWidgetHidden(store, true);

            let rows = [];
            let known = null; // names the server lists (to mark a missing file); null until the first answer

            const box = document.createElement("div");
            box.style.cssText = "display:flex;flex-direction:column;gap:6px;width:100%;box-sizing:border-box;padding:2px 0;";
            const domWidget = node.addDOMWidget("lora_rows", "lora_rows", box, {
                serialize: false,
                getMinHeight: () => 8 + (rows.length + 1) * 50,
            });
            // keep the rows right after the hidden store (positions are saved by index: never reorder later)
            node.widgets.splice(node.widgets.indexOf(domWidget), 1);
            node.widgets.splice(node.widgets.indexOf(store) + 1, 0, domWidget);

            // the CLIP strength field shows only when there is a CLIP and the LoRAs are meant for it
            const clipLinked = () => {
                const input = (node.inputs || []).find((i) => i.name === "clip");
                const toggle = (node.widgets || []).find((w) => w.name === "apply_to_clip");
                return !!input && input.link != null && (!toggle || toggle.value !== false);
            };
            let notes = []; // what the last run said about the LoRAs (compatibility, a CLIP they did not fit)

            function commit() {
                store.value = JSON.stringify(toStack(rows));
                if (store.callback) store.callback(store.value);
                app.graph.setDirtyCanvas(true, true);
            }

            function openFor(row) {
                openLoraPicker({
                    current: row.name,
                    taken: rows.map((r) => r.name).filter(Boolean),
                    onSelect: (name, info) => {
                        const fresh = !row.name;
                        row.name = name;
                        // a new row starts at the strength the LoRA's author recommends, when one is known
                        if (fresh && info && Number.isFinite(Number(info.strength)) && Number(info.strength) !== 0) {
                            row.strength_model = Number(info.strength);
                        }
                        render();
                        commit();
                    },
                });
            }

            // Drag a row by its handle to change the order (mouse, finger or pen). The dragged row follows the
            // pointer, a line shows where it will land, and the rows move when it is dropped.
            function attachDrag(handle, line, index) {
                handle.addEventListener("pointerdown", (event) => {
                    if (event.button !== undefined && event.button !== 0) return;
                    event.preventDefault();
                    const lines = [...box.children].slice(0, toStack(rows).length);
                    if (lines.length < 2) return;
                    handle.setPointerCapture(event.pointerId);
                    const centers = lines.map((el) => {
                        const rect = el.getBoundingClientRect();
                        return rect.top + rect.height / 2;
                    });
                    const startY = event.clientY;
                    let target = index;
                    line.style.opacity = "0.6";
                    line.style.position = "relative";
                    line.style.zIndex = "5";
                    const move = (e) => {
                        const dy = e.clientY - startY;
                        line.style.transform = `translateY(${dy}px)`;
                        const probe = centers[index] + dy;
                        target = centers.reduce((best, c, i) => (Math.abs(c - probe) < Math.abs(centers[best] - probe) ? i : best), index);
                        lines.forEach((el, i) => {
                            el.style.boxShadow = i === target && target !== index ? (target > index ? "0 3px 0 #4aa3ff" : "0 -3px 0 #4aa3ff") : "";
                        });
                    };
                    const finish = (e) => {
                        handle.removeEventListener("pointermove", move);
                        handle.removeEventListener("pointerup", finish);
                        handle.removeEventListener("pointercancel", finish);
                        if (e.type === "pointerup" && target !== index) {
                            const [moved] = rows.splice(index, 1);
                            rows.splice(target, 0, moved);
                            commit();
                        }
                        render();
                    };
                    handle.addEventListener("pointermove", move);
                    handle.addEventListener("pointerup", finish);
                    handle.addEventListener("pointercancel", finish);
                });
            }

            function makeRow(row, index) {
                const line = document.createElement("div");
                line.style.cssText = "display:flex;gap:6px;align-items:center;";
                if (!row.name) {
                    const add = button("＋ Add LoRA…", "flex:1;text-align:left;");
                    add.addEventListener("click", () => openFor(row));
                    line.appendChild(add);
                    return line;
                }
                const handle = document.createElement("div");
                handle.textContent = "⋮⋮";
                handle.title = "Drag to change the order";
                handle.style.cssText = "min-width:22px;min-height:44px;display:flex;align-items:center;justify-content:center;" +
                    "cursor:grab;opacity:.55;touch-action:none;user-select:none;-webkit-user-select:none;font-size:16px;";
                attachDrag(handle, line, index);
                const toggle = button(row.enabled ? "ON" : "OFF", "min-width:52px;padding:0 6px;font-weight:700;");
                toggle.style.background = row.enabled ? "#1d6f3a" : "#3a3a3c";
                toggle.style.borderColor = row.enabled ? "#4ad37a" : "#555";
                toggle.title = "Switch this LoRA on or off";
                toggle.addEventListener("click", () => {
                    row.enabled = !row.enabled;
                    render();
                    commit();
                });
                const short = row.name.replace(/\\/g, "/").split("/").pop().replace(/\.[^.]+$/, "");
                const missing = known !== null && !known.has(row.name);
                const name = button((missing ? "⚠ " : "") + short, "flex:1;min-width:0;text-align:left;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;");
                name.title = missing ? `${row.name}: not found in the loras folders` : row.name;
                if (missing) name.style.borderColor = "#d33";
                if (!row.enabled) name.style.opacity = "0.5";
                name.addEventListener("click", () => openFor(row));
                const strength = numberInput("strength");
                strength.value = row.strength_model;
                strength.title = "Strength (model)";
                strength.addEventListener("change", () => {
                    const value = Number(strength.value);
                    row.strength_model = Number.isFinite(value) ? Math.max(-100, Math.min(100, value)) : 1;
                    strength.value = row.strength_model;
                    commit();
                });
                line.append(handle, toggle, name, strength);
                if (clipLinked()) {
                    const clip = numberInput("= model");
                    clip.value = row.strength_clip === null ? "" : row.strength_clip;
                    clip.title = "Strength for the CLIP (empty = the same as the model strength)";
                    clip.addEventListener("change", () => {
                        const value = clip.value.trim() === "" ? null : Number(clip.value);
                        row.strength_clip = value === null || !Number.isFinite(value) ? null : Math.max(-100, Math.min(100, value));
                        clip.value = row.strength_clip === null ? "" : row.strength_clip;
                        commit();
                    });
                    line.appendChild(clip);
                }
                const remove = button("✕", "min-width:44px;padding:0;");
                remove.title = "Remove this LoRA";
                remove.addEventListener("click", () => {
                    rows.splice(index, 1);
                    render();
                    commit();
                });
                line.appendChild(remove);
                return line;
            }

            function render() {
                // the next row appears as soon as the last one has a LoRA in it
                rows = rows.filter((row, i) => row.name || i === rows.length - 1);
                if (!rows.length || rows[rows.length - 1].name) {
                    if (rows.length < MAX_ROWS) rows.push({ name: "", enabled: true, strength_model: 1, strength_clip: null });
                }
                box.replaceChildren(...rows.map(makeRow));
                const used = toStack(rows).filter((row) => row.enabled).length;
                if (used) {
                    const note = document.createElement("div");
                    note.style.cssText = "font-size:12px;opacity:.7;padding:0 4px;";
                    note.textContent = `${used} LoRA${used === 1 ? "" : "s"} on`;
                    box.appendChild(note);
                }
                for (const line of notes) {
                    const warning = document.createElement("div");
                    warning.style.cssText = "font-size:12px;color:#f0b44c;padding:0 4px;";
                    warning.textContent = "⚠ " + line;
                    box.appendChild(warning);
                }
                node.setSize([Math.max(node.size[0], 420), Math.max(node.size[1], node.computeSize()[1])]);
                app.graph.setDirtyCanvas(true, true);
            }

            // which of the saved names still exist (a missing file is marked, not silently dropped)
            async function checkNames() {
                try {
                    const data = await fetchLoras(false);
                    known = new Set(data.loras.map((l) => l.name));
                    render();
                } catch (e) {
                    known = null;
                }
            }

            const onConnectionsChange = node.onConnectionsChange;
            node.onConnectionsChange = function () {
                const out = onConnectionsChange ? onConnectionsChange.apply(this, arguments) : undefined;
                render();
                return out;
            };

            node.loraSelectorNotes = (lines) => {
                notes = Array.isArray(lines) ? lines.filter((l) => typeof l === "string") : [];
                render();
            };
            const toggleWidget = (node.widgets || []).find((w) => w.name === "apply_to_clip");
            if (toggleWidget) {
                const original = toggleWidget.callback;
                toggleWidget.callback = function () {
                    const out = original ? original.apply(this, arguments) : undefined;
                    render();
                    return out;
                };
            }
            node.loraSelectorRestore = () => {
                rows = fromStack(store.value);
                render();
                checkNames();
            };
            node.setSize([Math.max(node.size[0], 420), node.size[1]]);
            node.loraSelectorRestore();
            return result;
        };

        // what the run said about the LoRAs (a LoRA made for another model family, a CLIP it did not fit)
        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            if (onExecuted) onExecuted.apply(this, arguments);
            if (this.loraSelectorNotes) this.loraSelectorNotes(message && message.notes);
        };

        // a loaded workflow applies widgets_values directly, bypassing callbacks
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const out = onConfigure ? onConfigure.apply(this, arguments) : undefined;
            if (this.loraSelectorRestore) this.loraSelectorRestore();
            return out;
        };
    },
});
