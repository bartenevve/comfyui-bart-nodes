import { app } from "../../scripts/app.js";

const NODE_NAME = "SmartLoadImage";
const IMAGE_EXTENSIONS = /\.(png|jpe?g|webp|bmp|gif)$/i;
const MIN_SIDE = 8;
const CURSORS = {
    nw: "nwse-resize", se: "nwse-resize", ne: "nesw-resize", sw: "nesw-resize",
    n: "ns-resize", s: "ns-resize", e: "ew-resize", w: "ew-resize",
};

// dropped File.type comes from the OS's MIME registration, which is sometimes
// empty/wrong (older Windows + .webp) - fall back to the extension
function isImageFile(file) {
    return file.type.startsWith("image/") || IMAGE_EXTENSIONS.test(file.name);
}

const clamp = (value, low, high) => Math.min(Math.max(value, low), Math.max(low, high));

// ---- geometry, all in pixels of the ORIGINAL image ------------------------

function ratioOf(lock, width, height) {
    if (!lock || lock === "free") return null;
    if (lock === "original") return width / height;
    const [a, b] = lock.split(":").map(Number);
    return a / b;
}

// (width, height) on the snap grid, inside maxW x maxH, with a ratio close to
// `ratio`. 16:9 can't always be exact on a grid (896x504 isn't a multiple of 64),
// so among the pairs whose ratio error is within 2 points of the best one the
// one nearest `wantW` wins (or the largest when there is no wanted width) -
// snapping each side on its own could turn 16:9 into 2:1.
function snapPair(ratio, step, maxW, maxH, wantW) {
    const maxWi = Math.max(1, Math.floor(maxW / step));
    const maxHi = Math.max(1, Math.floor(maxH / step));
    const candidates = [];
    for (let wi = 1; wi <= maxWi; wi++) {
        const exact = (wi * step) / ratio / step;
        for (const hi of new Set([Math.floor(exact), Math.ceil(exact)])) {
            if (hi < 1 || hi > maxHi) continue;
            candidates.push({ w: wi * step, h: hi * step, error: Math.abs((wi * step) / (hi * step) / ratio - 1) });
        }
    }
    if (!candidates.length) return { w: maxWi * step, h: maxHi * step };
    const bestError = Math.min(...candidates.map((c) => c.error));
    const good = candidates.filter((c) => c.error <= bestError + 0.02);
    good.sort((a, b) =>
        wantW === undefined ? b.w * b.h - a.w * a.h : Math.abs(a.w - wantW) - Math.abs(b.w - wantW) || a.error - b.error
    );
    return { w: good[0].w, h: good[0].h };
}

// Largest box of `ratio` that fits `bounds`, centred on `center`. With a snap
// grid both sides are multiples of it; positions stay whole pixels.
function fitBox(bounds, center, ratio, snap) {
    let w = bounds.w;
    let h = w / ratio;
    if (h > bounds.h) {
        h = bounds.h;
        w = h * ratio;
    }
    if (snap > 1) {
        ({ w, h } = snapPair(ratio, snap, bounds.w, bounds.h));
    }
    return placeBox(center, w, h, bounds, snap);
}

function placeBox(center, w, h, bounds, snap) {
    const step = Math.max(snap, 1);
    w = Math.max(Math.min(MIN_SIDE, bounds.w), Math.floor(Math.min(w, bounds.w) / step) * step || Math.min(w, bounds.w));
    h = Math.max(Math.min(MIN_SIDE, bounds.h), Math.floor(Math.min(h, bounds.h) / step) * step || Math.min(h, bounds.h));
    w = Math.round(w);
    h = Math.round(h);
    const x = clamp(Math.round(center.x - w / 2), bounds.x, bounds.x + bounds.w - w);
    const y = clamp(Math.round(center.y - h / 2), bounds.y, bounds.y + bounds.h - h);
    return { x, y, w, h };
}

// New box while dragging. `handle` is "move", "new" or one of n/ne/e/se/s/sw/w/nw.
function dragBox(handle, start, p0, p, ratio, W, H, snap) {
    const step = Math.max(snap, 1);
    if (handle === "move") {
        return {
            x: Math.round(clamp(start.x + (p.x - p0.x), 0, W - start.w)),
            y: Math.round(clamp(start.y + (p.y - p0.y), 0, H - start.h)),
            w: start.w,
            h: start.h,
        };
    }

    // x-span [x1, x2] and y-span [y1, y2]: x1/y1 is the anchored end, x2/y2 the end
    // following the pointer; an axis the handle doesn't touch keeps the start box
    let x1, x2, y1, y2;
    let xMoves = true;
    let yMoves = true;
    if (handle === "new") {
        x1 = p0.x; y1 = p0.y; x2 = p.x; y2 = p.y;
    } else {
        const right = start.x + start.w;
        const bottom = start.y + start.h;
        if (handle.includes("e")) { x1 = start.x; x2 = p.x; }
        else if (handle.includes("w")) { x1 = right; x2 = p.x; }
        else { x1 = start.x; x2 = right; xMoves = false; }
        if (handle.includes("s")) { y1 = start.y; y2 = p.y; }
        else if (handle.includes("n")) { y1 = bottom; y2 = p.y; }
        else { y1 = start.y; y2 = bottom; yMoves = false; }
    }
    x2 = clamp(x2, 0, W);
    y2 = clamp(y2, 0, H);
    const sx = x2 >= x1 ? 1 : -1;
    const sy = y2 >= y1 ? 1 : -1;
    let w = Math.abs(x2 - x1);
    let h = Math.abs(y2 - y1);
    const cx = start.x + start.w / 2;
    const cy = start.y + start.h / 2;

    // room in the drag direction; an axis kept centred has room on both sides
    let maxW = sx > 0 ? W - x1 : x1;
    let maxH = sy > 0 ? H - y1 : y1;
    if (!xMoves) maxW = 2 * Math.min(cx, W - cx);
    if (!yMoves) maxH = 2 * Math.min(cy, H - cy);

    if (ratio) {
        if (xMoves && yMoves) w = Math.max(w, h * ratio);
        else if (xMoves) { /* width drives */ }
        else w = h * ratio;
        h = w / ratio;
        const f = Math.min(1, maxW / w, maxH / h);
        w *= f;
        h *= f;
    } else {
        w = Math.min(w, maxW);
        h = Math.min(h, maxH);
    }

    // snap sizes to the grid (rounded to nearest, but never past the room left)
    const snapSize = (size, room) => {
        let s = step > 1 ? Math.round(size / step) * step : Math.round(size);
        if (s > room) s = step > 1 ? Math.floor(room / step) * step : Math.floor(room);
        return Math.max(s, Math.min(Math.max(MIN_SIDE, step), Math.floor(room)));
    };
    if (ratio && step > 1) {
        ({ w, h } = snapPair(ratio, step, maxW, maxH, w));
    } else {
        w = snapSize(w, maxW);
        h = snapSize(h, maxH);
    }

    const x = xMoves ? (sx > 0 ? x1 : x1 - w) : (ratio ? cx - w / 2 : start.x);
    const y = yMoves ? (sy > 0 ? y1 : y1 - h) : (ratio ? cy - h / 2 : start.y);
    return {
        x: Math.round(clamp(x, 0, W - w)),
        y: Math.round(clamp(y, 0, H - h)),
        w: Math.round(w),
        h: Math.round(h),
    };
}

app.registerExtension({
    name: "comfyui.smart_load_image",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
            const node = this;
            const byName = (name) => (node.widgets || []).find((w) => w.name === name);

            const imageWidget = byName("image");
            const cropWidgets = {
                x: byName("crop_x"), y: byName("crop_y"), w: byName("crop_width"), h: byName("crop_height"),
            };
            const lockWidget = byName("aspect_lock");
            const snapWidget = byName("snap_to");
            if (!imageWidget || !lockWidget || !snapWidget || Object.values(cropWidgets).some((w) => !w)) {
                console.warn("SmartLoadImage: a widget was converted to an input; skipping the crop editor.");
                return result;
            }

            // ---- DOM: image + crop overlay ------------------------------------
            const stage = document.createElement("div");
            stage.style.cssText =
                "position:relative;width:100%;height:100%;min-height:200px;display:flex;" +
                "align-items:center;justify-content:center;overflow:hidden;user-select:none;touch-action:none;";
            const img = document.createElement("img");
            img.style.cssText = "display:block;max-width:100%;max-height:100%;object-fit:contain;";
            img.draggable = false;
            const overlay = document.createElement("div");
            overlay.style.cssText = "position:absolute;cursor:crosshair;display:none;";
            const rectEl = document.createElement("div");
            rectEl.style.cssText =
                "position:absolute;box-sizing:border-box;border:1px solid #fff;cursor:move;" +
                "box-shadow:0 0 0 9999px rgba(0,0,0,0.55);" +
                "background-image:linear-gradient(to right,transparent 33.2%,rgba(255,255,255,.35) 33.3%,transparent 33.5%," +
                "transparent 66.5%,rgba(255,255,255,.35) 66.6%,transparent 66.8%)," +
                "linear-gradient(to bottom,transparent 33.2%,rgba(255,255,255,.35) 33.3%,transparent 33.5%," +
                "transparent 66.5%,rgba(255,255,255,.35) 66.6%,transparent 66.8%);";
            const handlePlace = {
                nw: [0, 0], n: [50, 0], ne: [100, 0], e: [100, 50], se: [100, 100], s: [50, 100], sw: [0, 100], w: [0, 50],
            };
            for (const [name, [left, top]] of Object.entries(handlePlace)) {
                const handle = document.createElement("div");
                handle.dataset.handle = name;
                handle.style.cssText =
                    `position:absolute;left:${left}%;top:${top}%;width:10px;height:10px;margin:-5px 0 0 -5px;` +
                    `background:#fff;border:1px solid #222;box-sizing:border-box;cursor:${CURSORS[name]};`;
                rectEl.appendChild(handle);
            }
            overlay.appendChild(rectEl);
            stage.appendChild(img);
            stage.appendChild(overlay);

            const infoEl = document.createElement("div");
            infoEl.style.cssText = "font-size:11px;opacity:0.75;text-align:center;padding:2px 4px;";

            let natW = 0;
            let natH = 0;

            // ---- state <-> widgets --------------------------------------------
            const snap = () => parseInt(snapWidget.value, 10) || 1;
            const full = () => ({ x: 0, y: 0, w: natW, h: natH });

            // zero width/height = "no crop"; anything else is clamped into the image
            function getBox() {
                const w = Number(cropWidgets.w.value) || 0;
                const h = Number(cropWidgets.h.value) || 0;
                if (!natW || w <= 0 || h <= 0) return full();
                const x = clamp(Math.round(Number(cropWidgets.x.value) || 0), 0, natW - 1);
                const y = clamp(Math.round(Number(cropWidgets.y.value) || 0), 0, natH - 1);
                return { x, y, w: Math.min(w, natW - x), h: Math.min(h, natH - y) };
            }

            function setBox(box) {
                const isFull = box.x === 0 && box.y === 0 && box.w >= natW && box.h >= natH;
                cropWidgets.x.value = isFull ? 0 : box.x;
                cropWidgets.y.value = isFull ? 0 : box.y;
                cropWidgets.w.value = isFull ? 0 : box.w;
                cropWidgets.h.value = isFull ? 0 : box.h;
                render();
            }

            let serverSize = "";
            function render() {
                if (!natW) {
                    overlay.style.display = "none";
                    infoEl.textContent = "";
                    return;
                }
                // overlay covers exactly the displayed image, wherever flex put it
                overlay.style.display = "";
                overlay.style.left = img.offsetLeft + "px";
                overlay.style.top = img.offsetTop + "px";
                overlay.style.width = img.clientWidth + "px";
                overlay.style.height = img.clientHeight + "px";
                const box = getBox();
                rectEl.style.left = (box.x / natW) * 100 + "%";
                rectEl.style.top = (box.y / natH) * 100 + "%";
                rectEl.style.width = (box.w / natW) * 100 + "%";
                rectEl.style.height = (box.h / natH) * 100 + "%";
                const cropped = box.w < natW || box.h < natH;
                const ratio = (box.w / box.h).toFixed(3);
                infoEl.textContent =
                    `${natW}×${natH}` +
                    (cropped ? ` → ${box.w}×${box.h} at (${box.x}, ${box.y}) · ${ratio}` : " · no crop") +
                    (serverSize ? ` · last run: ${serverSize}` : "");
                app.graph.setDirtyCanvas(true, true);
            }

            // ---- pointer interaction ------------------------------------------
            function toSource(event) {
                const bounds = img.getBoundingClientRect();
                return {
                    x: clamp(((event.clientX - bounds.left) / bounds.width) * natW, 0, natW),
                    y: clamp(((event.clientY - bounds.top) / bounds.height) * natH, 0, natH),
                };
            }

            let drag = null;
            overlay.addEventListener("pointerdown", (event) => {
                if (!natW || event.button !== 0) return;
                event.preventDefault();
                event.stopPropagation();
                const start = getBox();
                // with nothing cropped the box IS the whole image: dragging inside it
                // can only mean "draw a new one" (moving it would do nothing)
                const wholeImage = start.w >= natW && start.h >= natH;
                const handle =
                    event.target.dataset.handle || (rectEl.contains(event.target) && !wholeImage ? "move" : "new");
                overlay.setPointerCapture(event.pointerId);
                drag = { handle, start, p0: toSource(event) };
            });
            overlay.addEventListener("pointermove", (event) => {
                if (!drag) return;
                const ratio = ratioOf(lockWidget.value, natW, natH);
                const box = dragBox(drag.handle, drag.start, drag.p0, toSource(event), ratio, natW, natH, snap());
                setBox(box);
            });
            const endDrag = (event) => {
                if (!drag) return;
                // a click on empty space (no drag) draws a zero-size box: treat it as "keep what was there"
                const box = getBox();
                if (drag.handle === "new" && (box.w < MIN_SIDE || box.h < MIN_SIDE)) setBox(drag.start);
                drag = null;
                try { overlay.releasePointerCapture(event.pointerId); } catch (e) { /* already released */ }
            };
            overlay.addEventListener("pointerup", endDrag);
            overlay.addEventListener("pointercancel", endDrag);

            // ---- image selection, upload, preview -----------------------------
            function previewUrl(name) {
                const slash = name.lastIndexOf("/");
                const params = new URLSearchParams({
                    filename: slash >= 0 ? name.slice(slash + 1) : name,
                    type: "input",
                    subfolder: slash >= 0 ? name.slice(0, slash) : "",
                    t: String(Date.now()),
                });
                return "/view?" + params.toString();
            }

            function loadPreview() {
                natW = 0;
                natH = 0;
                if (!imageWidget.value) {
                    img.removeAttribute("src");
                    render();
                    return;
                }
                img.src = previewUrl(imageWidget.value);
            }
            img.addEventListener("load", () => {
                natW = img.naturalWidth;
                natH = img.naturalHeight;
                render();
            });
            img.addEventListener("error", () => {
                natW = 0;
                natH = 0;
                render();
                infoEl.textContent = "could not load " + imageWidget.value;
            });
            if (typeof ResizeObserver !== "undefined") {
                new ResizeObserver(() => render()).observe(stage);
            }

            function resetCrop() {
                cropWidgets.x.value = 0;
                cropWidgets.y.value = 0;
                cropWidgets.w.value = 0;
                cropWidgets.h.value = 0;
                serverSize = "";
            }

            const origImageCallback = imageWidget.callback;
            imageWidget.callback = function () {
                const value = origImageCallback ? origImageCallback.apply(this, arguments) : undefined;
                resetCrop();
                loadPreview();
                return value;
            };

            async function uploadFile(file) {
                try {
                    const body = new FormData();
                    body.append("image", file);
                    const resp = await fetch("/upload/image", { method: "POST", body });
                    if (resp.status !== 200) {
                        console.error("smart_load_image upload failed:", resp.status, resp.statusText);
                        return;
                    }
                    const data = await resp.json();
                    const name = data.subfolder ? data.subfolder + "/" + data.name : data.name;
                    const values = (imageWidget.options && imageWidget.options.values) || [];
                    if (!values.includes(name)) values.push(name);
                    imageWidget.value = name;
                    resetCrop();
                    loadPreview();
                } catch (e) {
                    console.error("smart_load_image upload failed:", e);
                }
            }

            const fileInput = document.createElement("input");
            fileInput.type = "file";
            fileInput.accept = "image/*";
            fileInput.style.display = "none";
            fileInput.addEventListener("change", () => {
                for (const file of fileInput.files) if (isImageFile(file)) uploadFile(file);
                fileInput.value = "";
            });
            document.body.appendChild(fileInput);
            const onRemoved = node.onRemoved;
            node.onRemoved = function () {
                fileInput.remove();
                return onRemoved ? onRemoved.apply(this, arguments) : undefined;
            };

            // dropping on the DOM stage lands on the stage, not on the canvas node
            stage.addEventListener("dragover", (e) => {
                e.preventDefault();
                stage.style.outline = "2px dashed #5af";
            });
            stage.addEventListener("dragleave", () => { stage.style.outline = ""; });
            stage.addEventListener("drop", (e) => {
                e.preventDefault();
                stage.style.outline = "";
                for (const file of e.dataTransfer.files) if (isImageFile(file)) uploadFile(file);
            });
            node.onDragOver = (e) =>
                !!(e.dataTransfer && e.dataTransfer.items &&
                    [...e.dataTransfer.items].some((i) => i.kind === "file" && i.type.startsWith("image/")));
            node.onDragDrop = (e) => {
                let handled = false;
                for (const file of e.dataTransfer.files) {
                    if (isImageFile(file)) { uploadFile(file); handled = true; }
                }
                return handled;
            };

            // ---- widgets: numbers, aspect lock, buttons -----------------------
            for (const widget of Object.values(cropWidgets)) {
                const original = widget.callback;
                widget.callback = function () {
                    const value = original ? original.apply(this, arguments) : undefined;
                    render();
                    return value;
                };
            }

            // picking a lock reshapes the current box around its centre (shrinking, never growing)
            function applyLock() {
                if (!natW) return;
                const ratio = ratioOf(lockWidget.value, natW, natH);
                if (!ratio) return;
                const box = getBox();
                const center = { x: box.x + box.w / 2, y: box.y + box.h / 2 };
                let w = box.w;
                let h = w / ratio;
                if (h > box.h) {
                    h = box.h;
                    w = h * ratio;
                }
                setBox(placeBox(center, w, h, full(), snap()));
            }
            const origLockCallback = lockWidget.callback;
            lockWidget.callback = function () {
                const value = origLockCallback ? origLockCallback.apply(this, arguments) : undefined;
                applyLock();
                return value;
            };

            const uploadButton = node.addWidget("button", "📁 Upload image", null, () => fileInput.click());
            const domWidget = node.addDOMWidget("smart_load_image_stage", "stage", stage, {
                serialize: false,
                getMinHeight: () => 220,
            });
            node.addWidget("button", "⤢ Full image", null, () => {
                if (natW) setBox(full());
            });
            node.addWidget("button", "▣ Fit aspect (largest, centred)", null, () => {
                if (!natW) return;
                const ratio = ratioOf(lockWidget.value, natW, natH);
                if (!ratio) {
                    infoEl.textContent = "pick an aspect_lock first (it is 'free')";
                    return;
                }
                setBox(fitBox(full(), { x: natW / 2, y: natH / 2 }, ratio, snap()));
            });
            node.addDOMWidget("smart_load_image_info", "info", infoEl, { serialize: false, getMinHeight: () => 18 });

            // upload button right under the file combo, the editor after the numbers
            const imageIndex = node.widgets.indexOf(imageWidget);
            node.widgets.splice(node.widgets.indexOf(uploadButton), 1);
            node.widgets.splice(imageIndex + 1, 0, uploadButton);

            node.smartLoadRefresh = () => {
                loadPreview();
            };
            node.smartLoadSetServerSize = (text) => {
                serverSize = text || "";
                render();
            };
            node.smartLoadStage = domWidget;

            node.setSize([Math.max(node.size[0], 380), Math.max(node.size[1], 640)]);
            loadPreview();
            return result;
        };

        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            if (onExecuted) onExecuted.apply(this, arguments);
            if (message && message.size && this.smartLoadSetServerSize) {
                this.smartLoadSetServerSize(message.size[0]);
            }
        };

        // a loaded workflow applies widgets_values directly, bypassing callbacks
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = onConfigure ? onConfigure.apply(this, arguments) : undefined;
            if (this.smartLoadRefresh) this.smartLoadRefresh();
            return result;
        };
    },
});
