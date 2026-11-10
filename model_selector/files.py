"""Finding the model files: every model file of the folders ComfyUI loads models from, whatever its format and
whatever sub-folder it lies in, and the way back from an id to a path. Pure Python (the folder lists are passed in)."""
import os

from .model_info import MODEL_EXTENSIONS

# the folder keys of ComfyUI (and of the GGUF loader packs) that hold models a loader can read
SCAN_KEYS = ("checkpoints", "diffusion_models", "unet", "unet_gguf", "text_encoders", "clip", "clip_gguf", "vae", "clip_vision")
SEPARATOR = "::"
MAX_FILES = 20000


def collect_roots(get_folder_paths):
    """[(folder key, directory)] for the model folders, each real directory once (the first key that has it)."""
    roots, seen = [], set()
    for key in SCAN_KEYS:
        try:
            directories = get_folder_paths(key)
        except Exception:  # a key this ComfyUI does not know
            continue
        for directory in directories or []:
            real = os.path.realpath(directory)
            if real in seen or not os.path.isdir(real):
                continue
            seen.add(real)
            roots.append((key, directory))
    return roots


def make_id(key, relative):
    return f"{key}{SEPARATOR}{relative}"


def split_id(model_id):
    """(folder key, relative path) from an id, or None when it is not a plain `key::relative/path`."""
    if not isinstance(model_id, str) or SEPARATOR not in model_id or "\x00" in model_id or len(model_id) > 1000:
        return None
    key, _, relative = model_id.partition(SEPARATOR)
    relative = relative.replace("\\", "/")
    parts = relative.split("/")
    if not key or not relative or relative.startswith("/") or any(part in ("", ".", "..") for part in parts):
        return None
    if os.path.splitext(relative)[1].lower() not in MODEL_EXTENSIONS:
        return None
    return key, relative


def scan(roots):
    """[{id, key, rel, path}] of every model file under the roots (hidden files and folders skipped, symbolic
    links to folders followed once), sorted by relative path. At most MAX_FILES."""
    found, seen_files, seen_dirs = [], set(), set()
    for key, root in roots:
        for current, directories, names in os.walk(root, followlinks=True):
            real = os.path.realpath(current)
            if real in seen_dirs:
                directories[:] = []
                continue
            seen_dirs.add(real)
            directories[:] = sorted(d for d in directories if not d.startswith("."))
            for name in sorted(names):
                if name.startswith(".") or os.path.splitext(name)[1].lower() not in MODEL_EXTENSIONS:
                    continue
                path = os.path.join(current, name)
                real_file = os.path.realpath(path)
                if real_file in seen_files or not os.path.isfile(path):
                    continue
                seen_files.add(real_file)
                relative = os.path.relpath(path, root).replace(os.sep, "/")
                found.append({"id": make_id(key, relative), "key": key, "rel": relative, "path": path})
                if len(found) >= MAX_FILES:
                    return sorted(found, key=lambda item: item["rel"].lower())
    return sorted(found, key=lambda item: item["rel"].lower())


def resolve(model_id, roots):
    """The absolute path of an id inside the roots of its folder key, or None (unknown, missing, or trying to leave)."""
    parts = split_id(model_id)
    if parts is None:
        return None
    key, relative = parts
    for root_key, root in roots:
        if root_key != key:
            continue
        # lexical, not realpath: a symbolic link to a model collection inside the folder is allowed (as in ComfyUI
        # itself); the id has no `..` (see split_id), so the path cannot leave the root by itself
        base = os.path.abspath(root)
        path = os.path.abspath(os.path.join(root, *relative.split("/")))
        try:
            inside = os.path.commonpath([base, path]) == base
        except ValueError:
            inside = False
        if inside and os.path.isfile(path):
            return path
    return None
