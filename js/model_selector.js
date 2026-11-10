import { app } from "../../scripts/app.js";
import { fetchModels, openModelPicker } from "./bart_model_picker.js";

const NODE_NAME = "ModelSelector";
const OUTPUT_FOR = { MODEL: 0, CLIP: 1, VAE: 2, CLIP_VISION: 3 };

// hide a widget without removing it: an unknown type is not drawn, its value still serializes
function setWidgetHidden(widget, hidden) {
    if (hidden) {
        if (widget.origType === undefined) {
            widget.origType = widget.type;
            widget.origComputeSize = widget.computeSize;
        }
        widget.type = "model_selector_hidden";
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
        "min-height:44px;padding:0 12px;font-size:15px;border-radius:10px;border:1px solid #555;background:#2c2c2e;color:#eee;" +
        "cursor:pointer;touch-action:manipulation;-webkit-tap-highlight-color:transparent;" + extra;
    return b;
}

app.registerExtension({
    name: "comfyui.model_selector",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
            const node = this;
            const store = (node.widgets || []).find((w) => w.name === "model");
            if (!store) {
                console.warn("ModelSelector: the model widget was converted to an input; skipping the selector UI.");
                return result;
            }
            setWidgetHidden(store, true);

            let current = null; // what the server knows about the chosen file (summary), or null
            let missing = false;

            const box = document.createElement("div");
            box.style.cssText = "display:flex;flex-direction:column;gap:6px;width:100%;box-sizing:border-box;padding:2px 0;";
            const choose = button("＋ Choose a model…", "text-align:left;white-space:normal;line-height:1.25;padding:6px 12px;");
            const line = document.createElement("div");
            line.style.cssText = "font-size:12px;opacity:.8;padding:0 4px;min-height:16px;";
            box.append(choose, line);
            const domWidget = node.addDOMWidget("model_chooser", "model_chooser", box, { serialize: false, getMinHeight: () => 96 });
            // right after the hidden store: positions are saved by index, never reorder later
            node.widgets.splice(node.widgets.indexOf(domWidget), 1);
            node.widgets.splice(node.widgets.indexOf(store) + 1, 0, domWidget);

            // what the node gives is known from the file: the outputs it does not fill are drawn dimmed
            function markOutputs(outputs) {
                for (const [name, index] of Object.entries(OUTPUT_FOR)) {
                    const slot = (node.outputs || [])[index];
                    if (!slot) continue;
                    slot.color_off = slot.color_on = undefined;
                    const gives = !outputs || outputs.includes(name);
                    slot.label = gives ? undefined : slot.name + " (none)";
                }
            }

            function render() {
                if (!store.value) {
                    choose.textContent = "＋ Choose a model…";
                    line.textContent = "";
                    markOutputs(null);
                } else if (current) {
                    choose.textContent = current.name;
                    choose.title = current.id;
                    const facts = [current.kind, current.family, [current.format, current.precision, current.params_text].filter(Boolean).join(" ")];
                    line.textContent = facts.filter(Boolean).join(" · ") + (current.outputs && current.outputs.length ? "  →  " + current.outputs.join(", ") : "");
                    markOutputs(current.outputs);
                } else {
                    const shown = store.value.split("::").slice(1).join("::") || store.value;
                    choose.textContent = (missing ? "⚠ " : "") + shown;
                    choose.title = store.value;
                    line.textContent = missing ? "not found in the model folders" : "";
                    markOutputs(null);
                }
                choose.style.borderColor = missing ? "#d33" : "#555";
                node.setSize([Math.max(node.size[0], 380), Math.max(node.size[1], node.computeSize()[1])]);
                app.graph.setDirtyCanvas(true, true);
            }

            function commit(id, info) {
                store.value = id;
                if (store.callback) store.callback(id);
                current = info || null;
                missing = false;
                render();
            }

            async function refreshFromServer() {
                if (!store.value) {
                    current = null;
                    missing = false;
                    render();
                    return;
                }
                try {
                    const data = await fetchModels(false);
                    current = data.models.find((m) => m.id === store.value) || null;
                    missing = !current;
                } catch (e) {
                    current = null;
                    missing = false;
                }
                render();
            }

            choose.addEventListener("click", () => {
                openModelPicker({ current: store.value, onSelect: (id, info) => commit(id, info) });
            });

            node.modelSelectorRestore = () => {
                current = null;
                render();
                refreshFromServer();
            };
            node.setSize([Math.max(node.size[0], 380), node.size[1]]);
            node.modelSelectorRestore();
            return result;
        };

        // a loaded workflow applies widgets_values directly, bypassing callbacks
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const out = onConfigure ? onConfigure.apply(this, arguments) : undefined;
            if (this.modelSelectorRestore) this.modelSelectorRestore();
            return out;
        };
    },
});
