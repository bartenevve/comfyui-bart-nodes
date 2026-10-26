import { app } from "../../scripts/app.js";
import {
    IMAGE_ACCEPT,
    IMAGE_EXTENSIONS,
    fetchListing,
    fetchPool,
    joinPath,
    naturalCompare,
    openImageGallery,
    splitPath,
    thumbUrl,
    uploadToInput,
} from "./bart_image_gallery.js";

const NODE_NAME = "ImagePicker";
const MODES = [
    ["fixed", "Fixed"],
    ["random", "🎲 Random"],
    ["sequential", "➡ Sequential"],
];
const MAX_SEED = 0x7fffffff;

// the extension decides (the server only lists and decodes these), not File.type
function isImageFile(file) {
    return IMAGE_EXTENSIONS.test(file.name);
}

// hide a widget without removing it: an unknown type is not drawn, its value still serializes
function setWidgetHidden(widget, hidden) {
    if (hidden) {
        if (widget.origType === undefined) {
            widget.origType = widget.type;
            widget.origComputeSize = widget.computeSize;
        }
        widget.type = "image_picker_hidden";
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

function makeButton(label) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.style.cssText =
        "min-height:44px;padding:0 12px;font-size:16px;border-radius:10px;border:1px solid #555;background:#2c2c2e;" +
        "color:#eee;cursor:pointer;touch-action:manipulation;-webkit-tap-highlight-color:transparent;";
    return button;
}

// `display` is what the element shows as: "" keeps the default, a flex row needs "flex" (an empty
// string would drop the inline `display:flex` that makes it a row)
function show(element, visible, display = "") {
    element.style.display = visible ? display : "none";
}

app.registerExtension({
    name: "comfyui.image_picker",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
            const node = this;
            const byName = (name) => (node.widgets || []).find((w) => w.name === name);
            const imageWidget = byName("image");
            const modeWidget = byName("mode");
            const folderWidget = byName("folder");
            const subWidget = byName("include_subfolders");
            const seedWidget = byName("seed");
            const serialWidget = byName("edit_serial");
            if (!imageWidget || !modeWidget || !folderWidget || !subWidget || !seedWidget || !serialWidget) {
                console.warn("ImagePicker: a widget was converted to an input; skipping the picker UI.");
                return result;
            }
            for (const widget of [imageWidget, modeWidget, folderWidget, subWidget, serialWidget]) setWidgetHidden(widget, true);

            const mode = () => (MODES.some(([value]) => value === modeWidget.value) ? modeWidget.value : "fixed");

            // ---- DOM: modes, pool, preview, big buttons ------------------------
            const box = document.createElement("div");
            box.style.cssText = "display:flex;flex-direction:column;gap:6px;width:100%;height:100%;box-sizing:border-box;padding:2px 0;";

            const seg = document.createElement("div");
            seg.style.cssText = "display:flex;gap:6px;";
            const segButtons = MODES.map(([value, text]) => {
                const button = makeButton(text);
                button.style.flex = "1";
                button.style.fontSize = "14px";
                button.style.padding = "0 6px";
                button.addEventListener("click", () => setMode(value));
                seg.appendChild(button);
                return [value, button];
            });

            const poolRow = document.createElement("div");
            poolRow.style.cssText = "display:flex;gap:6px;align-items:center;";
            const poolChip = makeButton("");
            poolChip.style.cssText += "flex:1;min-width:0;text-align:left;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;";
            const subLabel = document.createElement("label");
            subLabel.style.cssText = "display:flex;align-items:center;gap:6px;min-height:44px;font-size:14px;white-space:nowrap;cursor:pointer;";
            const subBox = document.createElement("input");
            subBox.type = "checkbox";
            subBox.style.cssText = "width:20px;height:20px;margin:0;";
            subLabel.append(subBox, "subfolders");
            poolRow.append(poolChip, subLabel);

            const previewBox = document.createElement("div");
            previewBox.style.cssText =
                "flex:1;min-height:120px;display:flex;align-items:center;justify-content:center;background:#111;" +
                "border-radius:8px;overflow:hidden;cursor:pointer;position:relative;";
            const img = document.createElement("img");
            img.style.cssText = "max-width:100%;max-height:100%;object-fit:contain;display:none;";
            img.draggable = false;
            const placeholder = document.createElement("div");
            placeholder.style.cssText = "padding:16px;text-align:center;font-size:14px;opacity:.7;";
            previewBox.append(img, placeholder);
            const label = document.createElement("div");
            label.style.cssText = "font-size:12px;opacity:.8;text-align:center;word-break:break-all;min-height:16px;";
            const row = document.createElement("div");
            row.style.cssText = "display:flex;gap:6px;";
            const prev = makeButton("◀");
            const choose = makeButton("🖼 Choose image");
            choose.style.flex = "1";
            const next = makeButton("▶");
            const dice = makeButton("🎲");
            row.append(prev, choose, next, dice);
            const uploadRow = document.createElement("div");
            uploadRow.style.cssText = "display:flex;gap:6px;";
            const upload = makeButton("＋ Upload");
            upload.style.flex = "1";
            uploadRow.append(upload);
            const fileInput = document.createElement("input");
            fileInput.type = "file";
            fileInput.accept = IMAGE_ACCEPT;
            fileInput.style.display = "none";
            box.append(seg, poolRow, previewBox, label, row, uploadRow, fileInput);
            const domWidget = node.addDOMWidget("image_picker_ui", "image_picker", box, {
                serialize: false,
                // the stacked controls (the pool row makes it taller) must not overflow into the native widgets below
                getMinHeight: () => (mode() === "fixed" ? 300 : 350),
            });
            // The frontend saves this widget too (as ""), by position. Workflows from before the modes
            // existed hold [image, ""], so it must stay the second widget: the new ones then load as
            // mode = fixed instead of reading that "" as a mode. The hidden widgets take no room, so the
            // picker still draws above the seed.
            node.widgets.splice(node.widgets.indexOf(domWidget), 1);
            node.widgets.splice(node.widgets.indexOf(imageWidget) + 1, 0, domWidget);

            // ---- state ----------------------------------------------------------
            let sizeText = "";
            let pool = { count: null, pick: null, files: null, truncated: false, error: "" };
            let poolToken = 0;

            // A fresh serial on every hand edit of what the node loads: the server then knows a changed widget is a
            // deliberate pick, and an unchanged one means "queued before the previous run's advance arrived".
            function markHand() {
                serialWidget.value = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
            }
            function ensureSerial() {
                if (!serialWidget.value) markHand();
            }

            function inPool(path) {
                const folder = folderWidget.value || "";
                const sub = splitPath(path).subfolder;
                if (subWidget.value) return folder === "" || sub === folder || sub.startsWith(folder + "/");
                return sub === folder;
            }

            function poolText() {
                const folder = folderWidget.value || "";
                const where = folder || "input folder";
                if (pool.error) return "📁 " + where + " · " + pool.error;
                const count = pool.count === null ? "…" : pool.count + (pool.truncated ? "+" : "");
                return "📁 " + where + " · " + count + " image" + (pool.count === 1 ? "" : "s");
            }

            function showPlaceholder(text) {
                img.style.display = "none";
                img.removeAttribute("src");
                placeholder.style.display = "";
                placeholder.textContent = text;
            }

            function showImage(path) {
                const { subfolder, filename } = splitPath(path);
                placeholder.style.display = "none";
                img.style.display = "";
                img.src = thumbUrl(subfolder, filename, 512, node.__imagePickerStamp || "");
            }

            function refresh() {
                const current = mode();
                poolChip.textContent = poolText();
                const path = current === "random" ? pool.pick || "" : imageWidget.value || "";
                if (current === "random" && !path) {
                    showPlaceholder(pool.error ? "Could not read the folder" : pool.count === 0 ? "No images in this folder" : "…");
                    label.textContent = "";
                } else if (!path) {
                    showPlaceholder(
                        current === "sequential" ? "Starts at the first image of the folder - tap to choose another" : "No image selected - tap to choose"
                    );
                    label.textContent = "";
                } else {
                    showImage(path);
                    if (current === "random") label.textContent = "🎲 seed " + seedWidget.value + " → " + path;
                    else if (current === "sequential") label.textContent = "next run: " + path;
                    else label.textContent = path + (sizeText ? " · " + sizeText : "");
                }
                app.graph.setDirtyCanvas(true, true);
            }
            img.addEventListener("error", () => {
                const path = mode() === "random" ? pool.pick : imageWidget.value;
                showPlaceholder("Could not load " + (path || "the image"));
            });

            // what the next run can choose from (and, for the random mode, which file the current seed selects)
            async function refreshPool() {
                const token = ++poolToken;
                if (mode() === "fixed") {
                    pool = { count: null, pick: null, files: null, truncated: false, error: "" };
                    refresh();
                    return;
                }
                try {
                    const data = await fetchPool(folderWidget.value || "", !!subWidget.value, mode() === "random" ? seedWidget.value : null);
                    if (token !== poolToken) return;
                    pool = { count: data.count, pick: data.pick, files: null, truncated: !!data.truncated, error: "" };
                } catch (e) {
                    if (token !== poolToken) return;
                    pool = { count: null, pick: null, files: null, truncated: false, error: e.message };
                }
                refresh();
            }
            let previewTimer = null;
            function schedulePool() {
                clearTimeout(previewTimer);
                previewTimer = setTimeout(refreshPool, 150);
            }

            function applyMode() {
                const current = mode();
                for (const [value, button] of segButtons) {
                    const on = value === current;
                    button.style.background = on ? "#1d4f86" : "#2c2c2e";
                    button.style.borderColor = on ? "#4aa3ff" : "#555";
                }
                show(poolRow, current !== "fixed", "flex");
                show(prev, current !== "random");
                show(next, current !== "random");
                show(dice, current === "random");
                choose.textContent = current === "random" ? "🖼 Choose folder" : "🖼 Choose image";
                subBox.checked = !!subWidget.value;
                // the seed only matters for the random mode (the picker itself shows what it selects)
                const seedControl = byName("control_after_generate");
                setWidgetHidden(seedWidget, current !== "random");
                if (seedControl) setWidgetHidden(seedControl, current !== "random");
                node.setSize([node.size[0], Math.max(node.size[1], node.computeSize()[1])]);
            }

            function setMode(value) {
                if (value === mode()) return;
                modeWidget.value = value;
                if (modeWidget.callback) modeWidget.callback(value);
                // a pool starts where the user already is
                if (value !== "fixed" && !folderWidget.value) folderWidget.value = splitPath(imageWidget.value || "").subfolder;
                markHand();
                applyMode();
                refreshPool();
                refresh();
            }

            function setFolder(folder) {
                folderWidget.value = folder;
                if (folderWidget.callback) folderWidget.callback(folder);
                markHand();
                refreshPool();
                refresh();
            }

            function setImage(path) {
                imageWidget.value = path;
                if (imageWidget.callback) imageWidget.callback(path);
                markHand();
                node.__imagePickerStamp = String(Date.now()); // an upload may have replaced a same-named file
                sizeText = "";
                // a file outside the pool moves the pool to its folder, so what you pick is always reachable
                if (mode() !== "fixed" && !inPool(path)) setFolder(splitPath(path).subfolder);
                refresh();
            }

            function openPicker() {
                const current = mode();
                openImageGallery({
                    current: imageWidget.value || "",
                    folder: current === "fixed" ? null : folderWidget.value || "",
                    title:
                        current === "fixed"
                            ? "Choose an image"
                            : current === "random"
                              ? "Choose the folder to pick from"
                              : "Choose the folder, or the image to start from",
                    onSelect: setImage,
                    onUseFolder: current === "fixed" ? null : setFolder,
                });
            }
            // real DOM clicks: a finished click can't be re-delivered to whatever the
            // gallery draws under the finger, which is what kills the stock dropdown on touch
            choose.addEventListener("click", openPicker);
            previewBox.addEventListener("click", openPicker);
            poolChip.addEventListener("click", openPicker);

            subBox.addEventListener("change", () => {
                subWidget.value = subBox.checked;
                if (subWidget.callback) subWidget.callback(subWidget.value);
                markHand();
                refreshPool();
            });

            dice.addEventListener("click", () => {
                seedWidget.value = 1 + Math.floor(Math.random() * (MAX_SEED - 1));
                if (seedWidget.callback) seedWidget.callback(seedWidget.value);
                lastSeed = seedWidget.value;
                refreshPool();
            });
            // the seed changes by itself after every queued run (control after generate), and by hand
            let lastSeed = seedWidget.value;
            const seedWatch = setInterval(() => {
                if (mode() === "random" && seedWidget.value !== lastSeed) {
                    lastSeed = seedWidget.value;
                    schedulePool();
                }
            }, 500);
            const onRemoved = node.onRemoved;
            node.onRemoved = function () {
                clearInterval(seedWatch);
                clearTimeout(previewTimer);
                return onRemoved ? onRemoved.apply(this, arguments) : undefined;
            };
            const seedCallback = seedWidget.callback;
            seedWidget.callback = function () {
                const out = seedCallback ? seedCallback.apply(this, arguments) : undefined;
                lastSeed = seedWidget.value;
                schedulePool();
                return out;
            };

            // Taps on ◀ / ▶ queue up: each step starts from where the previous one ended (a second tap
            // while the first is still listing the folder would otherwise start from the same file).
            let stepping = Promise.resolve();
            function step(direction) {
                stepping = stepping.then(() => stepOnce(direction));
            }
            async function stepOnce(direction) {
                try {
                    let paths;
                    if (mode() === "sequential") {
                        // through the whole pool, in the order the server walks it
                        const data = await fetchPool(folderWidget.value || "", !!subWidget.value, null, true);
                        paths = data.files;
                    } else {
                        const { subfolder } = splitPath(imageWidget.value || "");
                        const data = await fetchListing(subfolder);
                        paths = data.files.map((file) => file.name).sort(naturalCompare).map((name) => joinPath(subfolder, name));
                    }
                    if (!paths.length) return;
                    const index = paths.indexOf(imageWidget.value || "");
                    const target = index < 0 ? 0 : (index + direction + paths.length) % paths.length;
                    setImage(paths[target]);
                } catch (e) {
                    placeholder.style.display = "";
                    placeholder.textContent = "Could not list the folder: " + e.message;
                }
            }
            prev.addEventListener("click", () => step(-1));
            next.addEventListener("click", () => step(1));

            async function uploadFiles(files) {
                files = files.filter(isImageFile);
                if (!files.length) {
                    placeholder.style.display = "";
                    placeholder.textContent = "Not an image this node can load (png, jpg, webp, bmp, gif)";
                    return;
                }
                const subfolder = mode() === "fixed" ? splitPath(imageWidget.value || "").subfolder : folderWidget.value || "";
                let last = "";
                try {
                    for (const file of files) if (isImageFile(file)) last = await uploadToInput(file, subfolder);
                } catch (e) {
                    placeholder.style.display = "";
                    placeholder.textContent = e.message;
                    return;
                }
                if (last) setImage(last);
                if (mode() !== "fixed") refreshPool(); // the pool just grew
            }
            upload.addEventListener("click", () => fileInput.click());
            fileInput.addEventListener("change", () => {
                uploadFiles([...fileInput.files]);
                fileInput.value = "";
            });
            // an image file dropped on the preview or on the node
            previewBox.addEventListener("dragover", (e) => e.preventDefault());
            previewBox.addEventListener("drop", (e) => {
                e.preventDefault();
                uploadFiles([...e.dataTransfer.files]);
            });
            node.onDragOver = (e) =>
                !!(e.dataTransfer && e.dataTransfer.items &&
                    [...e.dataTransfer.items].some((i) => i.kind === "file" && i.type.startsWith("image/")));
            node.onDragDrop = (e) => {
                const files = [...e.dataTransfer.files].filter(isImageFile);
                if (files.length) uploadFiles(files);
                return files.length > 0;
            };

            // everything the saved widgets decide, drawn again (after a load, or when a widget changed from outside)
            node.imagePickerRefresh = () => {
                ensureSerial();
                lastSeed = seedWidget.value;
                applyMode();
                refreshPool();
                refresh();
            };
            // the sequential mode advanced: the widget holds the file the NEXT run starts from
            node.imagePickerAdvance = (path) => {
                if (mode() !== "sequential" || !path) return;
                imageWidget.value = path;
                refresh();
            };
            node.imagePickerSetSize = (text) => {
                sizeText = text || "";
                refresh();
            };
            node.setSize([Math.max(node.size[0], 340), Math.max(node.size[1], 440)]);
            node.imagePickerRefresh();
            return result;
        };

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            if (onExecuted) onExecuted.apply(this, arguments);
            if (!message) return;
            if (message.size && this.imagePickerSetSize) this.imagePickerSetSize(message.size[0]);
            if (message.next && this.imagePickerAdvance) this.imagePickerAdvance(message.next[0]);
        };

        // a loaded workflow applies widgets_values directly, bypassing callbacks
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = onConfigure ? onConfigure.apply(this, arguments) : undefined;
            if (this.imagePickerRefresh) this.imagePickerRefresh();
            return result;
        };
    },
});
