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
// source nodes whose `value` widget is the value they output
const PRIMITIVE_TYPES = new Set([
    "PrimitiveNode", "PrimitiveInt", "PrimitiveFloat", "PrimitiveString", "PrimitiveStringMultiline", "PrimitiveBoolean",
]);

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

            // A CLIP is a live object of the running graph: it can't be sent to the server route, so with
            // one linked the text is written when the graph runs, and the button only clears the old text.
            function clipLinked() {
                const input = (node.inputs || []).find((i) => i.name === "clip");
                return !!input && input.link != null;
            }

            function render() {
                const hasText = !!(generatedWidget.value || "").trim();
                const stale = hasText && keyWidget.value && keyWidget.value !== snapshotKey();
                if (clipLinked()) {
                    button.name = hasText ? "🗑 Clear (rewritten on run)" : "▶ Written when the graph runs";
                } else {
                    button.name = busy ? "⏳ Generating…" : hasText ? "🔄 Regenerate" : "✨ Generate";
                }
                const hint = stale
                    ? "⚠ inputs changed since this text was generated - it is kept as is; press Regenerate to redo it"
                    : "";
                infoEl.textContent = [hint, note].filter(Boolean).join("\n");
                app.graph.setDirtyCanvas(true, true);
            }

            // A widget fed by a link (converted to an input) keeps a stale value of its
            // own. The button runs outside the graph, so it can only know what a
            // Primitive node holds in its widget (the frontend's own, or core's PrimitiveInt /
            // PrimitiveString / ...), followed through any Reroutes; anything else (another
            // node's computed output - even one with a single widget) is unknowable until the
            // graph runs.
            function linkedValue(name) {
                const input = (node.inputs || []).find((i) => i.widget && i.widget.name === name);
                if (!input || input.link == null) return { linked: false };
                const graph = node.graph || app.graph;
                let linkId = input.link;
                for (let hops = 0; hops < 16; hops++) {
                    const links = graph.links;
                    const link = links && (links.get ? links.get(linkId) : links[linkId]);
                    const origin = link && graph.getNodeById(link.origin_id);
                    if (!origin) return { linked: true, known: false, from: "?" };
                    if (origin.type === "Reroute") {
                        const next = origin.inputs && origin.inputs[0] && origin.inputs[0].link;
                        if (next == null) return { linked: true, known: false, from: "Reroute" };
                        linkId = next;
                        continue;
                    }
                    if (PRIMITIVE_TYPES.has(origin.type) && link.origin_slot === 0) {
                        const source = (origin.widgets || []).find((w) => w.name === "value");
                        if (source && source.value !== undefined) {
                            return { linked: true, known: true, value: source.value };
                        }
                    }
                    return { linked: true, known: false, from: origin.title || origin.type };
                }
                return { linked: true, known: false, from: "Reroute chain" };
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
                if (clipLinked()) {
                    if ((generatedWidget.value || "").trim()) {
                        generatedWidget.value = "";
                        keyWidget.value = "";
                        if (!linkedValue("seed").linked) seedWidget.value = 1 + Math.floor(Math.random() * (MAX_SEED - 1));
                        note = "text cleared: run the graph and the linked CLIP writes a new take (new seed)";
                    } else {
                        note = "a CLIP is linked: run the graph, it writes the text (ollama_url and model are ignored)";
                    }
                    render();
                    return;
                }
                const { values, unknown } = collectValues();
                if (unknown.length) {
                    note = "error: linked to a node whose value is only known when the graph runs: " +
                        unknown.join(", ") + ". Use a Primitive node, or unlink it.";
                    render();
                    return;
                }
                busy = true;
                note = "generating - the model can take a minute…";
                // the key goes with what is sent: edits made while the model is thinking must still
                // show up as "inputs changed" when the answer lands
                const sentKey = snapshotKey();
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
                        keyWidget.value = sentKey;
                        note = data.report + "\nseed " + data.seed +
                            (linkedValue("seed").linked ? " (linked: Regenerate repeats the same take)" : "");
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
                node.setSize([node.size[0], Math.max(node.size[1], node.computeSize()[1])]);
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
            // the key for a graph run is built from what the server says it used, not from the widgets
            // as they are when the answer arrives (they may have been edited since the run was queued)
            node.minimaxH3KeyFromUsed = (used) => {
                const snapshot = CONTENT_WIDGETS.map((name) => {
                    const v = effectiveValue(name);
                    if (!v.present) return null;
                    if (v.unknown) return "linked:" + v.unknown;
                    return used && name in used ? used[name] : v.value;
                });
                return hashString(JSON.stringify(snapshot));
            };

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
                let used = null;
                try {
                    used = message.used && JSON.parse(message.used[0]);
                } catch (e) {
                    used = null;
                }
                if (keyWidget) keyWidget.value = used ? this.minimaxH3KeyFromUsed(used) : this.minimaxH3SnapshotKey();
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

        // a legacy Primitive node builds its `value` widget only once the whole graph is configured:
        // until then a linked input looks unknowable and the "inputs changed" hint would show wrongly
        const onAfterGraphConfigured = nodeType.prototype.onAfterGraphConfigured;
        nodeType.prototype.onAfterGraphConfigured = function () {
            const result = onAfterGraphConfigured ? onAfterGraphConfigured.apply(this, arguments) : undefined;
            if (this.minimaxH3Refresh) this.minimaxH3Refresh();
            return result;
        };
    },
});
