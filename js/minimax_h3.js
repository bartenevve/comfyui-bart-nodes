import { app } from "../../scripts/app.js";

const NODE_NAME = "MiniMaxH3Prompt";

// Widgets sent to the server by the Generate button (everything the node reads).
const REQUEST_WIDGETS = [
    "ollama_url", "model", "request", "duration", "aspect", "mode", "variant", "seed",
    "triggers", "dialogue", "text", "image", "start", "end", "shots", "refs",
    "temperature", "num_ctx", "num_predict", "retries", "timeout", "think", "append_no_think", "short_side",
];
// The subset that decides WHAT is generated. Seed, retries, timeout and the
// server URL are left out on purpose: changing them doesn't make the saved text
// "out of date", and the seed changes on every press anyway.
const CONTENT_WIDGETS = [
    "model", "request", "duration", "aspect", "mode", "variant",
    "triggers", "dialogue", "text", "image", "start", "end", "shots", "refs",
    "temperature", "num_ctx", "num_predict", "think", "append_no_think",
];
const MAX_SEED = 0x7fffffff;

// Same trick as the 52prompts node: an unknown widget type is how LiteGraph
// hides a widget without removing it, so its value still serializes.
function setWidgetHidden(widget, hidden) {
    if (hidden) {
        if (widget.origType === undefined) {
            widget.origType = widget.type;
            widget.origComputeSize = widget.computeSize;
        }
        widget.type = "minimax_h3_hidden";
        widget.computeSize = () => [0, -4];
    } else if (widget.origType !== undefined) {
        widget.type = widget.origType;
        widget.computeSize = widget.origComputeSize;
        widget.origType = undefined;
        widget.origComputeSize = undefined;
    }
    const el = widget.element || widget.inputEl;
    if (el && el.style) {
        el.style.display = hidden ? "none" : "";
    }
    widget.hidden = hidden;
}

// small string hash (cyrb53): the snapshot is only compared, never decoded
function hashString(text) {
    let h1 = 0xdeadbeef;
    let h2 = 0x41c6ce57;
    for (let i = 0; i < text.length; i++) {
        const ch = text.charCodeAt(i);
        h1 = Math.imul(h1 ^ ch, 2654435761);
        h2 = Math.imul(h2 ^ ch, 1597334677);
    }
    h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
    h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
    return (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(16);
}

app.registerExtension({
    name: "comfyui.minimax_h3",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
            const node = this;
            const byName = (name) => (node.widgets || []).find((w) => w.name === name);

            const generatedWidget = byName("generated");
            const keyWidget = byName("generated_key");
            const seedWidget = byName("seed");
            if (!generatedWidget || !keyWidget || !seedWidget) {
                console.warn("MiniMaxH3Prompt: generated/seed widgets are missing; skipping custom UI.");
                return result;
            }
            setWidgetHidden(keyWidget, true);

            const infoEl = document.createElement("div");
            infoEl.style.fontSize = "11px";
            infoEl.style.lineHeight = "1.35";
            infoEl.style.opacity = "0.8";
            infoEl.style.whiteSpace = "pre-wrap";
            infoEl.style.overflowY = "auto";
            infoEl.style.maxHeight = "96px";
            infoEl.style.padding = "2px 6px";
            const infoWidget = node.addDOMWidget("minimax_h3_info", "info", infoEl, {
                serialize: false,
                getMinHeight: () => 24,
            });

            let busy = false;
            let note = ""; // last report / error, shown under the button
            const button = node.addWidget("button", "✨ Generate", null, () => generate());

            function render() {
                const hasText = !!(generatedWidget.value || "").trim();
                const stale = hasText && keyWidget.value && keyWidget.value !== snapshotKey();
                button.name = busy ? "⏳ Generating…" : hasText ? "🔄 Regenerate" : "✨ Generate";
                const hint = stale
                    ? "⚠ inputs changed since this text was generated - it is kept as is; press Regenerate to redo it"
                    : "";
                infoEl.textContent = [hint, note].filter(Boolean).join("\n");
                app.graph.setDirtyCanvas(true, true);
            }

            // A widget fed by a link (converted to an input) keeps a stale value of its
            // own. The button runs outside the graph, so it can only know what a
            // Primitive-style source node holds in its widget; anything else
            // (another node's computed output) is unknowable until the graph runs.
            function linkedValue(name) {
                const input = (node.inputs || []).find((i) => i.widget && i.widget.name === name);
                if (!input || input.link == null) return { linked: false };
                const links = app.graph.links;
                const link = links && (links.get ? links.get(input.link) : links[input.link]);
                const origin = link && app.graph.getNodeById(link.origin_id);
                if (!origin) return { linked: true, known: false, from: "?" };
                const sourceWidgets = origin.widgets || [];
                const source =
                    sourceWidgets.find((w) => w.name === "value") ||
                    (sourceWidgets.length === 1 ? sourceWidgets[0] : null);
                if (source && source.value !== undefined) {
                    return { linked: true, known: true, value: source.value };
                }
                return { linked: true, known: false, from: origin.title || origin.type };
            }

            function effectiveValue(name) {
                const widget = byName(name);
                if (!widget) return { present: false };
                const link = linkedValue(name);
                if (link.linked && link.known) return { present: true, value: link.value };
                if (link.linked) return { present: true, unknown: link.from };
                return { present: true, value: widget.value };
            }

            function snapshotKey() {
                const snapshot = CONTENT_WIDGETS.map((name) => {
                    const v = effectiveValue(name);
                    return v.present ? (v.unknown ? "linked:" + v.unknown : v.value) : null;
                });
                return hashString(JSON.stringify(snapshot));
            }

            function collectValues() {
                const values = {};
                const unknown = [];
                for (const name of REQUEST_WIDGETS) {
                    const v = effectiveValue(name);
                    if (!v.present) continue;
                    if (v.unknown) unknown.push(name + " (from " + v.unknown + ")");
                    else values[name] = v.value;
                }
                return { values, unknown };
            }

            async function generate() {
                if (busy) return;
                const { values, unknown } = collectValues();
                if (unknown.length) {
                    note = "error: linked to a node whose value is only known when the graph runs: " +
                        unknown.join(", ") + ". Use a Primitive node, or unlink it.";
                    render();
                    return;
                }
                busy = true;
                note = "generating - the model can take a minute…";
                // a fresh seed on every press is what makes Regenerate give a different take
                // (a linked seed can't be changed from here: it is sent as it is)
                if (!linkedValue("seed").linked) {
                    seedWidget.value = 1 + Math.floor(Math.random() * (MAX_SEED - 1));
                    values.seed = seedWidget.value;
                }
                render();
                try {
                    const resp = await fetch("/minimax_h3/generate", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(values),
                    });
                    const data = await resp.json();
                    if (!resp.ok || data.error) {
                        note = "error: " + (data.error || resp.status);
                    } else {
                        generatedWidget.value = data.generated;
                        keyWidget.value = snapshotKey();
                        note = data.report + "\nseed " + data.seed;
                    }
                } catch (e) {
                    console.error("minimax_h3 generate failed:", e);
                    note = "request failed (see the browser console)";
                } finally {
                    busy = false;
                    render();
                }
            }

            // keep the order: button, info line, then the result it fills
            const resultIndex = node.widgets.indexOf(generatedWidget);
            for (const widget of [infoWidget, button]) {
                node.widgets.splice(node.widgets.indexOf(widget), 1);
                node.widgets.splice(resultIndex, 0, widget);
            }

            function applyMode() {
                const mode = (byName("mode") || {}).value;
                const variant = (byName("variant") || {}).value;
                const fields = {
                    image: mode === "I2VA",
                    start: mode === "FL2VA",
                    end: mode === "FL2VA" || mode === "L2VA",
                    refs: variant === "auto" || variant === "ref",
                };
                for (const [name, visible] of Object.entries(fields)) {
                    const widget = byName(name);
                    if (widget) setWidgetHidden(widget, !visible);
                }
                node.setSize([node.size[0], node.computeSize()[1]]);
            }

            for (const name of CONTENT_WIDGETS) {
                const widget = byName(name);
                if (!widget) continue;
                const original = widget.callback;
                widget.callback = function () {
                    const value = original ? original.apply(this, arguments) : undefined;
                    if (name === "mode" || name === "variant") applyMode();
                    render();
                    return value;
                };
                // multiline STRING widgets are textareas; typing doesn't always go through callback
                const el = widget.element || widget.inputEl;
                if (el && el.addEventListener) el.addEventListener("input", render);
            }
            const generatedEl = generatedWidget.element || generatedWidget.inputEl;
            if (generatedEl && generatedEl.addEventListener) generatedEl.addEventListener("input", render);

            const onConnectionsChange = node.onConnectionsChange;
            node.onConnectionsChange = function () {
                const out = onConnectionsChange ? onConnectionsChange.apply(this, arguments) : undefined;
                render();
                return out;
            };

            node.minimaxH3Refresh = () => {
                applyMode();
                render();
            };
            node.minimaxH3SetNote = (text) => {
                note = text || "";
                render();
            };
            node.minimaxH3SnapshotKey = snapshotKey;

            node.setSize([Math.max(node.size[0], 420), node.size[1]]);
            applyMode();
            render();
            return result;
        };

        // a run that had to generate (nothing saved yet) fills the widgets, so the
        // result is saved with the workflow and shown right away
        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            if (onExecuted) onExecuted.apply(this, arguments);
            if (!message || !this.minimaxH3Refresh) return;
            const byName = (name) => (this.widgets || []).find((w) => w.name === name);
            const generated = message.generated && message.generated[0];
            if (generated) {
                const generatedWidget = byName("generated");
                const keyWidget = byName("generated_key");
                if (generatedWidget) generatedWidget.value = generated;
                if (keyWidget) keyWidget.value = this.minimaxH3SnapshotKey();
            }
            this.minimaxH3SetNote(message.report && message.report[0]);
        };

        // a loaded workflow applies widgets_values directly, bypassing callbacks
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = onConfigure ? onConfigure.apply(this, arguments) : undefined;
            if (this.minimaxH3Refresh) this.minimaxH3Refresh();
            return result;
        };
    },
});
