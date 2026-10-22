import { app } from "../../scripts/app.js";

const NODE_NAME = "LoadRandomImage";
const IMAGE_EXTENSIONS = /\.(png|jpe?g|webp|bmp|gif)$/i;

// dropped File.type comes from the OS's MIME registration for the extension,
// which is sometimes empty/wrong (older Windows + .webp is a known case) -
// fall back to the extension itself so a genuinely supported image isn't
// silently rejected
function isImageFile(file) {
    return file.type.startsWith("image/") || IMAGE_EXTENSIONS.test(file.name);
}

app.registerExtension({
    name: "comfyui.random_image",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
            const node = this;

            const dirWidget = node.widgets.find((w) => w.name === "directory");
            const filenameWidget = node.widgets.find((w) => w.name === "filename");
            const lastLoadedWidget = node.widgets.find((w) => w.name === "last_loaded");
            const randomWidget = node.widgets.find((w) => w.name === "randomize_on_queue");
            const sequentialWidget = node.widgets.find((w) => w.name === "sequential_on_queue");

            // any of these can be missing if the user did "Convert Widget to
            // Input" on one of them - in that case the value comes from a
            // link instead, and our dropdown/preview/dice UI doesn't apply;
            // bail out instead of throwing partway through setup
            if (!dirWidget || !filenameWidget || !lastLoadedWidget || !randomWidget || !sequentialWidget) {
                console.warn(
                    "LoadRandomImage: one or more widgets were converted to inputs; skipping custom UI."
                );
                return result;
            }

            // last_loaded is persisted (serialized with the workflow) but not
            // user-facing - it exists only so the preview can show "what this
            // node actually output last run" again after reopening a workflow,
            // separately from `filename` which tracks the NEXT pick
            lastLoadedWidget.computeSize = () => [0, -4];

            // edit_serial tells the server "the user picked this file by hand" (a fresh value
            // per pick), so that re-picking the very file the previous run started with isn't
            // mistaken for a queued duplicate of that run. Hidden and persisted like last_loaded;
            // absent on a build of the node without it, in which case there is nothing to signal.
            const editSerialWidget = node.widgets.find((w) => w.name === "edit_serial");
            if (editSerialWidget) editSerialWidget.computeSize = () => [0, -4];
            function markHandPicked() {
                if (editSerialWidget) {
                    editSerialWidget.value = Date.now() + "-" + Math.random().toString(36).slice(2, 8);
                }
            }

            // turn the plain STRING widget into a dropdown of files found
            // in `directory`, same idea as core LoadImage's file combo
            filenameWidget.type = "combo";
            filenameWidget.options = filenameWidget.options || {};
            filenameWidget.options.values = [];

            const img = document.createElement("img");
            img.style.width = "100%";
            img.style.objectFit = "contain";

            // the <img> is a real DOM element sitting on top of the graph
            // canvas - native drag events land on IT, not on the canvas, so
            // LiteGraph's node.onDragOver/onDragDrop never see them unless
            // we also listen here directly
            img.addEventListener("dragover", (e) => {
                e.preventDefault();
                img.style.outline = "2px dashed #5af";
            });
            img.addEventListener("dragleave", () => {
                img.style.outline = "";
            });
            img.addEventListener("drop", (e) => {
                e.preventDefault();
                img.style.outline = "";
                for (const file of e.dataTransfer.files) {
                    if (isImageFile(file)) {
                        uploadFile(file);
                    }
                }
            });

            node.addDOMWidget("random_image_preview", "preview", img, { serialize: false });

            const fileCountEl = document.createElement("div");
            fileCountEl.style.fontSize = "11px";
            fileCountEl.style.opacity = "0.7";
            fileCountEl.style.textAlign = "center";
            node.addDOMWidget("random_image_file_count", "file_count", fileCountEl, { serialize: false });

            node.updateRandomImagePreview = function (filename) {
                if (!filename || !dirWidget.value) return;
                img.src =
                    "/random_image/view?dir=" + encodeURIComponent(dirWidget.value) +
                    "&filename=" + encodeURIComponent(filename) +
                    "&t=" + Date.now();
            };

            // guards against a slow fetch for a directory the user has since
            // changed away from resolving late and clobbering a newer pick
            let fileListRequestId = 0;
            async function refreshFileList() {
                const requestId = ++fileListRequestId;
                if (!dirWidget.value) {
                    filenameWidget.options.values = [];
                    fileCountEl.textContent = "";
                    return;
                }
                try {
                    const resp = await fetch("/random_image/list?dir=" + encodeURIComponent(dirWidget.value));
                    const data = await resp.json();
                    if (requestId !== fileListRequestId) return;
                    if (data.error) {
                        console.error("random_image list error:", data.error);
                        filenameWidget.options.values = [];
                        fileCountEl.textContent = "";
                        return;
                    }
                    filenameWidget.options.values = data.files || [];
                    if (!filenameWidget.options.values.includes(filenameWidget.value)) {
                        filenameWidget.value = filenameWidget.options.values[0] || "";
                    }
                    const count = filenameWidget.options.values.length;
                    fileCountEl.textContent = count + (count === 1 ? " file found" : " files found");
                    app.graph.setDirtyCanvas(true, true);
                } catch (e) {
                    if (requestId === fileListRequestId) {
                        console.error("random_image list failed:", e);
                        fileCountEl.textContent = "";
                    }
                }
            }

            function updateWidgetVisibility() {
                const auto = randomWidget.value || sequentialWidget.value;
                diceWidget.disabled = auto;
                filenameWidget.disabled = auto;
                // whatever is currently shown is ignored the moment
                // randomize_on_queue is on - a fresh pick happens at execute
                // time regardless, so showing anything here would be
                // misleading. sequential mode is different: the currently
                // shown file IS exactly what the next run will output, so it
                // stays visible.
                img.style.display = randomWidget.value ? "none" : "";
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
            makeMutuallyExclusive(randomWidget, sequentialWidget);
            makeMutuallyExclusive(sequentialWidget, randomWidget);

            const origFilenameCallback = filenameWidget.callback;
            filenameWidget.callback = function (value) {
                markHandPicked();
                node.updateRandomImagePreview(value);
                return origFilenameCallback ? origFilenameCallback.apply(this, arguments) : undefined;
            };

            const origDirCallback = dirWidget.callback;
            dirWidget.callback = function (value) {
                refreshFileList();
                return origDirCallback ? origDirCallback.apply(this, arguments) : undefined;
            };

            const diceWidget = node.addWidget("button", "🎲 Randomize", null, async () => {
                if (!dirWidget.value) return;
                try {
                    const resp = await fetch("/random_image/pick?dir=" + encodeURIComponent(dirWidget.value));
                    const data = await resp.json();
                    if (data.error) {
                        console.error("random_image pick error:", data.error);
                        return;
                    }
                    if (!filenameWidget.options.values.includes(data.filename)) {
                        filenameWidget.options.values.push(data.filename);
                    }
                    filenameWidget.value = data.filename;
                    markHandPicked();
                    node.updateRandomImagePreview(data.filename);
                } catch (e) {
                    console.error("random_image pick failed:", e);
                }
            });

            async function uploadFile(file) {
                try {
                    const body = new FormData();
                    body.append("image", file);
                    const resp = await fetch("/upload/image", { method: "POST", body });
                    if (resp.status !== 200) {
                        console.error("random_image upload failed:", resp.status, resp.statusText);
                        return;
                    }
                    const data = await resp.json();

                    const dirResp = await fetch(
                        "/random_image/input_dir?subfolder=" + encodeURIComponent(data.subfolder || "")
                    );
                    if (!dirResp.ok) {
                        console.error("random_image input_dir lookup failed:", dirResp.status, dirResp.statusText);
                        return;
                    }
                    const dirData = await dirResp.json();
                    if (dirData.error) {
                        console.error("random_image input_dir error:", dirData.error);
                        return;
                    }

                    dirWidget.value = dirData.directory;
                    await refreshFileList();
                    if (!filenameWidget.options.values.includes(data.name)) {
                        filenameWidget.options.values.push(data.name);
                    }
                    filenameWidget.value = data.name;
                    markHandPicked();
                    node.updateRandomImagePreview(data.name);
                } catch (e) {
                    console.error("random_image upload failed:", e);
                }
            }

            // drop an image straight onto the node - uploads to ComfyUI's
            // managed input dir and selects it, same end result as LoadImage
            node.onDragOver = function (e) {
                if (e.dataTransfer && e.dataTransfer.items) {
                    return [...e.dataTransfer.items].some(
                        (i) => i.kind === "file" && i.type.startsWith("image/")
                    );
                }
                return false;
            };

            node.onDragDrop = function (e) {
                let handled = false;
                for (const file of e.dataTransfer.files) {
                    if (isImageFile(file)) {
                        uploadFile(file);
                        handled = true;
                    }
                }
                return handled;
            };

            // Needed twice: here for a fresh node, and from onConfigure for a node loaded from a
            // workflow - LiteGraph creates it first (this function, widgets still at their
            // defaults, so no directory to list) and only then applies the saved values.
            node.restoreRandomImage = function () {
                // a node (or an old workflow) that has no serial yet gets one now, so the server
                // treats every later run as "no hand edit since the last run" until the user edits
                if (editSerialWidget && !editSerialWidget.value) markHandPicked();
                updateWidgetVisibility();
                if (dirWidget.value) {
                    refreshFileList();
                }
                // prefer the persisted "what actually loaded last run" value;
                // fall back to `filename` only for a node that never ran yet
                if (lastLoadedWidget.value) {
                    node.updateRandomImagePreview(lastLoadedWidget.value);
                } else if (filenameWidget.value) {
                    node.updateRandomImagePreview(filenameWidget.value);
                }
            };
            node.restoreRandomImage();

            return result;
        };

        // after the node actually executes, sync the widget + preview to
        // whatever file really got loaded - regardless of which mode chose it
        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            if (onExecuted) onExecuted.apply(this, arguments);
            if (!message) return;

            // seeds the widget for the NEXT run - not what this run loaded
            const nextFilename = message.filename && message.filename[0];
            if (nextFilename) {
                const filenameWidget = this.widgets.find((w) => w.name === "filename");
                if (filenameWidget) filenameWidget.value = nextFilename;
            }

            // what this run actually sent downstream - persisted so it
            // survives a workflow save/reopen, unlike the live <img> itself
            const lastLoaded = message.last_loaded && message.last_loaded[0];
            if (lastLoaded) {
                const lastLoadedWidget = this.widgets.find((w) => w.name === "last_loaded");
                if (lastLoadedWidget) lastLoadedWidget.value = lastLoaded;
                if (this.updateRandomImagePreview) this.updateRandomImagePreview(lastLoaded);
            }
            // re-applies AFTER the src update above, so the preview stays
            // hidden if randomize_on_queue is (still) on even though a real
            // result just came in
            if (this.updateWidgetVisibility) this.updateWidgetVisibility();
        };

        // a loaded/hand-edited workflow.json applies widgets_values directly
        // during configure, bypassing widget .callback entirely - the JS
        // mutual-exclusion above never sees it, so correct it here too
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = onConfigure ? onConfigure.apply(this, arguments) : undefined;
            const randomW = this.widgets.find((w) => w.name === "randomize_on_queue");
            const sequentialW = this.widgets.find((w) => w.name === "sequential_on_queue");
            if (randomW && sequentialW && randomW.value && sequentialW.value) {
                sequentialW.value = false;
            }
            if (this.restoreRandomImage) this.restoreRandomImage();
            else if (this.updateWidgetVisibility) this.updateWidgetVisibility();
            return result;
        };
    },
});
