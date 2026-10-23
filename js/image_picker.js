import { app } from "../../scripts/app.js";
import {
    IMAGE_ACCEPT,
    IMAGE_EXTENSIONS,
    fetchListing,
    joinPath,
    naturalCompare,
    openImageGallery,
    splitPath,
    thumbUrl,
    uploadToInput,
} from "./bart_image_gallery.js";

const NODE_NAME = "ImagePicker";

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

app.registerExtension({
    name: "comfyui.image_picker",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
            const node = this;
            const imageWidget = (node.widgets || []).find((w) => w.name === "image");
            if (!imageWidget) {
                console.warn("ImagePicker: the image widget was converted to an input; skipping the picker UI.");
                return result;
            }
            setWidgetHidden(imageWidget, true);

            // ---- DOM: preview + big buttons ---------------------------------
            const box = document.createElement("div");
            box.style.cssText = "display:flex;flex-direction:column;gap:6px;width:100%;height:100%;box-sizing:border-box;padding:2px 0;";
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
            row.append(prev, choose, next);
            const uploadRow = document.createElement("div");
            uploadRow.style.cssText = "display:flex;gap:6px;";
            const upload = makeButton("＋ Upload");
            upload.style.flex = "1";
            uploadRow.append(upload);
            const fileInput = document.createElement("input");
            fileInput.type = "file";
            fileInput.accept = IMAGE_ACCEPT;
            fileInput.style.display = "none";
            box.append(previewBox, label, row, uploadRow, fileInput);
            node.addDOMWidget("image_picker_ui", "image_picker", box, { serialize: false, getMinHeight: () => 250 });

            let sizeText = "";
            function refresh() {
                const path = imageWidget.value || "";
                if (!path) {
                    img.style.display = "none";
                    img.removeAttribute("src");
                    placeholder.style.display = "";
                    placeholder.textContent = "No image selected - tap to choose";
                    label.textContent = "";
                    return;
                }
                const { subfolder, filename } = splitPath(path);
                placeholder.style.display = "none";
                img.style.display = "";
                img.src = thumbUrl(subfolder, filename, 512, node.__imagePickerStamp || "");
                label.textContent = path + (sizeText ? " · " + sizeText : "");
                app.graph.setDirtyCanvas(true, true);
            }
            img.addEventListener("error", () => {
                img.style.display = "none";
                placeholder.style.display = "";
                placeholder.textContent = "Could not load " + (imageWidget.value || "the image");
            });

            function setImage(path) {
                imageWidget.value = path;
                if (imageWidget.callback) imageWidget.callback(path);
                node.__imagePickerStamp = String(Date.now()); // an upload may have replaced a same-named file
                sizeText = "";
                refresh();
            }

            function openPicker() {
                openImageGallery({ current: imageWidget.value || "", title: "Choose an image", onSelect: setImage });
            }
            // real DOM clicks: a finished click can't be re-delivered to whatever the
            // gallery draws under the finger, which is what kills the stock dropdown on touch
            choose.addEventListener("click", openPicker);
            previewBox.addEventListener("click", openPicker);

            // Taps on ◀ / ▶ queue up: each step starts from where the previous one ended (a second tap
            // while the first is still listing the folder would otherwise start from the same file).
            let stepping = Promise.resolve();
            function step(direction) {
                stepping = stepping.then(() => stepOnce(direction));
            }
            async function stepOnce(direction) {
                const { subfolder, filename } = splitPath(imageWidget.value || "");
                try {
                    const data = await fetchListing(subfolder);
                    const names = data.files.map((file) => file.name).sort(naturalCompare);
                    if (!names.length) return;
                    const index = names.indexOf(filename);
                    const target = index < 0 ? 0 : (index + direction + names.length) % names.length;
                    setImage(joinPath(subfolder, names[target]));
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
                const subfolder = splitPath(imageWidget.value || "").subfolder;
                let last = "";
                try {
                    for (const file of files) if (isImageFile(file)) last = await uploadToInput(file, subfolder);
                } catch (e) {
                    placeholder.style.display = "";
                    placeholder.textContent = e.message;
                    return;
                }
                if (last) setImage(last);
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

            node.imagePickerRefresh = refresh;
            node.imagePickerSetSize = (text) => {
                sizeText = text || "";
                refresh();
            };
            node.setSize([Math.max(node.size[0], 340), Math.max(node.size[1], 390)]);
            refresh();
            return result;
        };

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            if (onExecuted) onExecuted.apply(this, arguments);
            if (message && message.size && this.imagePickerSetSize) this.imagePickerSetSize(message.size[0]);
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
