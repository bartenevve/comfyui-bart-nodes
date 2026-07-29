import { app } from "../../scripts/app.js";

const NODE_NAME = "LoadRandomBooruImage";

app.registerExtension({
    name: "comfyui.random_booru",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
            const node = this;

            const sourceWidget = node.widgets.find((w) => w.name === "source");
            const tagsWidget = node.widgets.find((w) => w.name === "tags");
            const randomWidget = node.widgets.find((w) => w.name === "random_post");
            const incrementWidget = node.widgets.find((w) => w.name === "increment_on_queue");
            const indexWidget = node.widgets.find((w) => w.name === "index");
            const lastPostWidget = node.widgets.find((w) => w.name === "last_post_id");

            // any of these can be missing if the user did "Convert Widget to
            // Input" on one of them - in that case the value comes from a link
            // instead, and our preview/dice UI doesn't apply; bail out instead
            // of throwing partway through setup
            if (!sourceWidget || !tagsWidget || !randomWidget || !incrementWidget || !indexWidget || !lastPostWidget) {
                console.warn(
                    "LoadRandomBooruImage: one or more widgets were converted to inputs; skipping custom UI."
                );
                return result;
            }

            // last_post_id is persisted (serialized with the workflow) but not
            // user-facing - it exists only so the preview can show "what this
            // node actually output last run" again after reopening a workflow
            lastPostWidget.computeSize = () => [0, -4];

            const img = document.createElement("img");
            img.style.width = "100%";
            img.style.objectFit = "contain";
            node.addDOMWidget("random_booru_preview", "preview", img, { serialize: false });

            const infoEl = document.createElement("div");
            infoEl.style.fontSize = "11px";
            infoEl.style.opacity = "0.7";
            infoEl.style.textAlign = "center";
            infoEl.style.whiteSpace = "nowrap";
            infoEl.style.overflow = "hidden";
            infoEl.style.textOverflow = "ellipsis";
            node.addDOMWidget("random_booru_info", "info", infoEl, { serialize: false });

            function setInfo(text) {
                infoEl.textContent = text || "";
                app.graph.setDirtyCanvas(true, true);
            }

            node.updateBooruPreview = function (postId) {
                if (!postId) return;
                img.src =
                    "/random_booru/view?source=" + encodeURIComponent(sourceWidget.value) +
                    "&post_id=" + encodeURIComponent(postId);
            };

            function updateWidgetVisibility() {
                const auto = randomWidget.value;
                diceWidget.disabled = auto;
                indexWidget.disabled = auto;
                // whatever is currently shown is ignored the moment random_post
                // is on - a fresh pick happens at execute time regardless, so
                // showing anything here would be misleading. increment mode is
                // different: the shown post IS what the next run outputs, so it
                // stays visible.
                img.style.display = auto ? "none" : "";
            }
            node.updateWidgetVisibility = updateWidgetVisibility;

            function makeMutuallyExclusive(source, other) {
                const origCallback = source.callback;
                source.callback = function (value) {
                    if (value && other.value) {
                        other.value = false;
                    }
                    updateWidgetVisibility();
                    return origCallback ? origCallback.apply(this, arguments) : undefined;
                };
            }
            makeMutuallyExclusive(randomWidget, incrementWidget);
            makeMutuallyExclusive(incrementWidget, randomWidget);

            // guards against a slow pick for tags the user has since changed
            // away from resolving late and clobbering a newer pick
            let pickRequestId = 0;

            async function pickPost(mode) {
                const requestId = ++pickRequestId;
                setInfo("loading…");
                const query = new URLSearchParams({
                    source: sourceWidget.value,
                    tags: tagsWidget.value || "",
                    mode: mode,
                    index: String(indexWidget.value ?? 0),
                });
                try {
                    const resp = await fetch("/random_booru/pick?" + query.toString());
                    const data = await resp.json();
                    if (requestId !== pickRequestId) return;
                    if (!resp.ok || data.error) {
                        setInfo("error: " + (data.error || resp.status));
                        return;
                    }
                    indexWidget.value = data.index;
                    lastPostWidget.value = data.post_id;
                    node.updateBooruPreview(data.post_id);
                    setInfo(
                        "#" + data.post_id + " · " + data.index + " / " + data.total +
                        (data.rating ? " · " + data.rating : "")
                    );
                } catch (e) {
                    if (requestId === pickRequestId) {
                        console.error("random_booru pick failed:", e);
                        setInfo("request failed");
                    }
                }
            }

            const diceWidget = node.addWidget("button", "🎲 Random", null, () => pickPost("random"));
            node.addWidget("button", "↧ Load index", null, () => pickPost("index"));

            const origIndexCallback = indexWidget.callback;
            indexWidget.callback = function (value) {
                // don't auto-fetch on every spinner click - the site is remote
                // and each step would be a request; the button loads it
                setInfo("index " + value + " — press ↧ Load index to preview");
                return origIndexCallback ? origIndexCallback.apply(this, arguments) : undefined;
            };

            updateWidgetVisibility();
            if (lastPostWidget.value) {
                node.updateBooruPreview(lastPostWidget.value);
                setInfo("#" + lastPostWidget.value);
            }

            return result;
        };

        // after the node actually executes, sync the widgets + preview to
        // whatever post really got loaded - regardless of which mode chose it
        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            if (onExecuted) onExecuted.apply(this, arguments);
            if (!message) return;

            // seeds the widget for the NEXT run - not what this run loaded
            const nextIndex = message.next_index && message.next_index[0];
            if (nextIndex !== undefined && nextIndex !== null) {
                const indexWidget = this.widgets.find((w) => w.name === "index");
                if (indexWidget) indexWidget.value = nextIndex;
            }

            // what this run actually sent downstream - persisted so it survives
            // a workflow save/reopen, unlike the live <img> itself
            const postId = message.post_id && message.post_id[0];
            if (postId) {
                const lastPostWidget = this.widgets.find((w) => w.name === "last_post_id");
                if (lastPostWidget) lastPostWidget.value = postId;
                if (this.updateBooruPreview) this.updateBooruPreview(postId);
                const usedIndex = message.index && message.index[0];
                const total = message.total && message.total[0];
                const info = this.widgets.find((w) => w.name === "random_booru_info");
                if (info && info.element) {
                    info.element.textContent =
                        "#" + postId + (usedIndex !== undefined ? " · " + usedIndex : "") +
                        (total !== undefined ? " / " + total : "");
                }
            }
            // re-applies AFTER the src update above, so the preview stays
            // hidden if random_post is (still) on even though a real result
            // just came in
            if (this.updateWidgetVisibility) this.updateWidgetVisibility();
        };

        // a loaded/hand-edited workflow.json applies widgets_values directly
        // during configure, bypassing widget .callback entirely - the JS
        // mutual-exclusion above never sees it, so correct it here too
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = onConfigure ? onConfigure.apply(this, arguments) : undefined;
            const randomW = this.widgets.find((w) => w.name === "random_post");
            const incrementW = this.widgets.find((w) => w.name === "increment_on_queue");
            if (randomW && incrementW && randomW.value && incrementW.value) {
                incrementW.value = false;
            }
            if (this.updateWidgetVisibility) this.updateWidgetVisibility();
            return result;
        };
    },
});
