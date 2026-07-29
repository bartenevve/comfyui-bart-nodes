import { app } from "../../scripts/app.js";

const NODE_NAME = "LoadRandom52Prompt";
const FIELD_WIDGETS = ["input_1", "input_2", "input_3", "choice_list"];

// One fetch per browser session, shared by every node of this type: the list is
// a static table on the Python side, so per-node requests would be pure noise.
let catalogPromise = null;

function loadCatalog() {
    if (!catalogPromise) {
        catalogPromise = fetch("/random_prompts52/generators")
            .then((resp) => resp.json())
            .then((data) => {
                const byLabel = {};
                for (const entry of data.generators || []) {
                    byLabel[entry.label] = entry;
                }
                return byLabel;
            })
            .catch((e) => {
                console.error("random_prompts52: could not load the generator list:", e);
                catalogPromise = null; // let a later node retry
                return {};
            });
    }
    return catalogPromise;
}

// LiteGraph draws whatever widget types it knows; handing it one it doesn't
// know is how a widget gets hidden without being removed (its value still
// serializes, which is what we want - the user's names shouldn't vanish just
// because they looked at another generator).
function setWidgetHidden(widget, hidden) {
    if (hidden) {
        if (widget.origType === undefined) {
            widget.origType = widget.type;
            widget.origComputeSize = widget.computeSize;
        }
        widget.type = "random_prompts52_hidden";
        widget.computeSize = () => [0, -4];
    } else if (widget.origType !== undefined) {
        widget.type = widget.origType;
        widget.computeSize = widget.origComputeSize;
        widget.origType = undefined;
        widget.origComputeSize = undefined;
    }
    // multiline STRING widgets are DOM overlays, unaffected by the type swap
    if (widget.element) {
        widget.element.style.display = hidden ? "none" : "";
    }
    widget.hidden = hidden;
}

app.registerExtension({
    name: "comfyui.random_prompts52",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
            const node = this;

            const generatorWidget = node.widgets.find((w) => w.name === "generator");
            const randomizeWidget = node.widgets.find((w) => w.name === "randomize");
            const seedWidget = node.widgets.find((w) => w.name === "seed");
            const lastPromptWidget = node.widgets.find((w) => w.name === "last_prompt");
            const fieldWidgets = {};
            for (const name of FIELD_WIDGETS) {
                fieldWidgets[name] = node.widgets.find((w) => w.name === name);
            }

            // any of these can be missing if the user did "Convert Widget to
            // Input" on one of them - the value then comes from a link instead
            // and our preview UI doesn't apply; bail out rather than throwing
            // partway through setup
            if (
                !generatorWidget || !randomizeWidget || !seedWidget || !lastPromptWidget ||
                FIELD_WIDGETS.some((name) => !fieldWidgets[name])
            ) {
                console.warn(
                    "LoadRandom52Prompt: one or more widgets were converted to inputs; skipping custom UI."
                );
                return result;
            }

            // last_prompt is persisted (serialized with the workflow) but never
            // user-facing: it exists only so the display below can show what
            // this node last output after a workflow is reopened
            setWidgetHidden(lastPromptWidget, true);

            const promptEl = document.createElement("div");
            promptEl.style.fontSize = "12px";
            promptEl.style.lineHeight = "1.35";
            promptEl.style.padding = "4px 6px";
            promptEl.style.whiteSpace = "pre-wrap";
            promptEl.style.overflowY = "auto";
            promptEl.style.opacity = "0.9";
            node.addDOMWidget("random_prompts52_prompt", "prompt", promptEl, { serialize: false });

            const infoEl = document.createElement("div");
            infoEl.style.fontSize = "11px";
            infoEl.style.opacity = "0.7";
            infoEl.style.textAlign = "center";
            infoEl.style.whiteSpace = "nowrap";
            infoEl.style.overflow = "hidden";
            infoEl.style.textOverflow = "ellipsis";
            node.addDOMWidget("random_prompts52_info", "info", infoEl, { serialize: false });

            function setInfo(text) {
                infoEl.textContent = text || "";
                app.graph.setDirtyCanvas(true, true);
            }

            node.setPrompt52Text = function (text) {
                promptEl.textContent = text || "";
                app.graph.setDirtyCanvas(true, true);
            };

            let catalog = {};

            function applyGenerator() {
                const entry = catalog[generatorWidget.value];
                const used = new Map();
                for (const field of (entry && entry.fields) || []) {
                    used.set(field.widget, field);
                }
                for (const name of FIELD_WIDGETS) {
                    const widget = fieldWidgets[name];
                    const field = used.get(name);
                    setWidgetHidden(widget, !field);
                    if (field) {
                        widget.label = field.label;
                        if (field.default && !widget.value) widget.value = field.default;
                    }
                }
                // the seed only decides anything when randomize is off
                seedWidget.disabled = randomizeWidget.value;
                node.setSize([node.size[0], node.computeSize()[1]]);
                app.graph.setDirtyCanvas(true, true);
            }
            node.applyPrompt52Generator = applyGenerator;

            loadCatalog().then((byLabel) => {
                catalog = byLabel;
                applyGenerator();
            });

            const origGeneratorCallback = generatorWidget.callback;
            generatorWidget.callback = function () {
                const value = origGeneratorCallback
                    ? origGeneratorCallback.apply(this, arguments)
                    : undefined;
                applyGenerator();
                setInfo("");
                return value;
            };

            const origRandomizeCallback = randomizeWidget.callback;
            randomizeWidget.callback = function () {
                const value = origRandomizeCallback
                    ? origRandomizeCallback.apply(this, arguments)
                    : undefined;
                applyGenerator();
                return value;
            };

            // guards against a slow pick for a generator the user has since
            // changed away from resolving late and clobbering a newer one
            let pickRequestId = 0;

            async function pickPrompt(useSeed) {
                const requestId = ++pickRequestId;
                setInfo("loading…");
                const query = new URLSearchParams({ generator: generatorWidget.value });
                if (useSeed) query.set("seed", String(seedWidget.value ?? 0));
                for (const name of FIELD_WIDGETS) {
                    const widget = fieldWidgets[name];
                    if (!widget.hidden && widget.value) query.set(name, widget.value);
                }
                try {
                    const resp = await fetch("/random_prompts52/pick?" + query.toString());
                    const data = await resp.json();
                    if (requestId !== pickRequestId) return;
                    if (!resp.ok || data.error) {
                        setInfo("error: " + (data.error || resp.status));
                        return;
                    }
                    seedWidget.value = data.seed;
                    lastPromptWidget.value = data.prompt;
                    node.setPrompt52Text(data.prompt);
                    setInfo(data.generator + " · seed " + data.seed);
                } catch (e) {
                    if (requestId === pickRequestId) {
                        console.error("random_prompts52 pick failed:", e);
                        setInfo("request failed");
                    }
                }
            }

            node.addWidget("button", "🎲 Generate", null, () => pickPrompt(false));
            node.addWidget("button", "↧ Load seed", null, () => pickPrompt(true));

            applyGenerator();
            if (lastPromptWidget.value) {
                node.setPrompt52Text(lastPromptWidget.value);
            }

            return result;
        };

        // after the node executes, show what it actually produced and hand back
        // the seed that produced it, so turning randomize off reproduces it
        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            if (onExecuted) onExecuted.apply(this, arguments);
            if (!message) return;

            const prompt = message.prompt && message.prompt[0];
            const seed = message.seed && message.seed[0];

            if (seed !== undefined && seed !== null) {
                const seedWidget = this.widgets.find((w) => w.name === "seed");
                if (seedWidget) seedWidget.value = seed;
            }
            if (prompt) {
                const lastPromptWidget = this.widgets.find((w) => w.name === "last_prompt");
                if (lastPromptWidget) lastPromptWidget.value = prompt;
                if (this.setPrompt52Text) this.setPrompt52Text(prompt);
                const info = this.widgets.find((w) => w.name === "random_prompts52_info");
                if (info && info.element) {
                    info.element.textContent =
                        (message.generator && message.generator[0]) ||
                        (seed !== undefined ? "seed " + seed : "");
                }
            }
        };

        // a loaded workflow.json applies widgets_values directly during
        // configure, bypassing widget .callback entirely - so the field
        // visibility for the saved generator has to be re-derived here
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = onConfigure ? onConfigure.apply(this, arguments) : undefined;
            if (this.applyPrompt52Generator) this.applyPrompt52Generator();
            const lastPromptWidget = this.widgets && this.widgets.find((w) => w.name === "last_prompt");
            if (lastPromptWidget && lastPromptWidget.value && this.setPrompt52Text) {
                this.setPrompt52Text(lastPromptWidget.value);
            }
            return result;
        };
    },
});
