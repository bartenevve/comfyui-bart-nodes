import hashlib
import os
import re

from .. import selection as sequential

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}

# thumbnail edge lengths the server will produce: a handful of fixed buckets, so
# the disk cache stays small however the frontend's size slider is set
THUMB_SIZES = (128, 192, 256, 384, 512)

# one listing is capped so a huge folder can't produce a megabyte of JSON
MAX_ENTRIES = 5000

# How the node picks its file: the one shown, a seeded random one from a folder, or the next one of a folder
MODES = ("fixed", "random", "sequential")
# the pool of random / sequential is capped too (a recursive walk over a whole disk must end)
MAX_POOL = 20000


class PathError(ValueError):
    """A subfolder/filename that is not a plain path inside the input folder."""


def clean_subfolder(subfolder):
    """Normalised 'a/b' (forward slashes, no empty or dot segments) or '' for the root.

    Anything that could leave the base folder - '..', absolute paths, drive
    letters, NUL - is refused rather than quietly resolved.
    """
    text = (subfolder or "").replace("\\", "/").strip()
    if "\x00" in text:
        raise PathError("invalid subfolder")
    if text.startswith("/"):
        raise PathError("subfolder must be relative to the input folder")
    # a drive letter ("C:/...") means something only on Windows; elsewhere "3:2 crops" is a normal folder name
    if os.name == "nt" and len(text) > 1 and text[1] == ":":
        raise PathError("subfolder must be relative to the input folder")
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise PathError("subfolder must not contain '..'")
    return "/".join(parts)


def clean_filename(filename):
    """A bare file name: no separators, no dot-only names, no NUL."""
    name = (filename or "").strip()
    if not name or name in (".", "..") or "/" in name or "\\" in name or "\x00" in name:
        raise PathError("invalid filename")
    return name


def split_image_path(value):
    """'a/b/c.png' -> ('a/b', 'c.png'); the part before the last slash is the subfolder."""
    text = (value or "").replace("\\", "/").strip()
    subfolder, _, filename = text.rpartition("/")
    return clean_subfolder(subfolder), clean_filename(filename)


def join_inside(base, subfolder, filename=""):
    """Path of subfolder/filename under `base`, guaranteed not to leave it.

    The check is lexical, not realpath: a symlinked collection placed inside
    the input folder is deliberately allowed (the stock Load Image and /view
    behave the same way), a '..' never is.
    """
    path = os.path.join(base, *clean_subfolder(subfolder).split("/")) if clean_subfolder(subfolder) else base
    if filename:
        path = os.path.join(path, clean_filename(filename))
    path = os.path.abspath(path)
    root = os.path.abspath(base)
    if path != root and not path.startswith(root + os.sep):
        raise PathError("path escapes the input folder")
    return path


def is_image_name(name):
    return os.path.splitext(name)[1].lower() in IMAGE_EXTENSIONS


def list_directory(base, subfolder):
    """One folder level: its subfolders and its image files (name, size, mtime).

    Dotfiles and dot-folders are skipped. Order is case-insensitive by name; when a
    folder holds more than MAX_ENTRIES images the FIRST ones in that order are kept.
    """
    directory = join_inside(base, subfolder)
    folders = []
    files = []
    with os.scandir(directory) as entries:
        for entry in entries:
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_dir():
                    folders.append(entry.name)
                elif entry.is_file() and is_image_name(entry.name):
                    stat = entry.stat()
                    files.append({"name": entry.name, "size": stat.st_size, "mtime": stat.st_mtime})
            except OSError:
                continue  # a broken symlink or a file that vanished mid-scan
    folders.sort(key=str.lower)
    # sorted BEFORE the cut: scandir order is arbitrary, and which files survive a cap must not be
    files.sort(key=lambda item: item["name"].lower())
    truncated = len(files) > MAX_ENTRIES
    return {"subfolder": clean_subfolder(subfolder), "folders": folders, "files": files[:MAX_ENTRIES], "truncated": truncated}


def thumb_size(requested):
    """Smallest bucket that is at least `requested` pixels, else the largest."""
    try:
        wanted = int(requested)
    except (TypeError, ValueError):
        wanted = THUMB_SIZES[2]
    for size in THUMB_SIZES:
        if size >= wanted:
            return size
    return THUMB_SIZES[-1]


def thumb_cache_name(relative_path, mtime_ns, file_size, size):
    """Cache file name for one thumbnail; a changed file (mtime/size) gets a new name."""
    key = f"{relative_path}|{mtime_ns}|{file_size}".encode("utf-8")
    return f"{hashlib.sha256(key).hexdigest()[:32]}_{size}.webp"


_DIGITS = re.compile(r"(\d+)")


def natural_key(name):
    """Sort key putting img2 before img10 (the gallery's own order, so stepping and sequential agree)."""
    return [int(part) if part.isdigit() else part for part in _DIGITS.split(name.lower())]


def list_pool(base, folder, recursive=False):
    """(paths, truncated): the images random / sequential choose from, as input-folder-relative paths.

    One folder level, or the whole tree with `recursive` (dot-folders skipped, symlinked sub-folders not
    followed so a link back up cannot loop). Sorted naturally by path; a pool over MAX_POOL images keeps
    the first ones in that walk order (folders visited alphabetically) and says so.
    """
    folder = clean_subfolder(folder)
    top = join_inside(base, folder)
    found = []
    truncated = False
    for root, dirs, names in os.walk(top):
        dirs[:] = sorted((d for d in dirs if not d.startswith(".")), key=str.lower)
        relative = os.path.relpath(root, top)
        prefix = folder if relative == "." else (folder + "/" if folder else "") + relative.replace(os.sep, "/")
        for name in sorted(names, key=str.lower):
            if name.startswith(".") or not is_image_name(name):
                continue
            if len(found) >= MAX_POOL:
                truncated = True
                break
            found.append(prefix + "/" + name if prefix else name)
        if truncated or not recursive:
            break
    found.sort(key=natural_key)
    return found, truncated


def pick_seeded(files, seed):
    """The image `seed` selects: the same seed always gives the same file, neighbouring seeds look unrelated."""
    digest = hashlib.sha256(str(int(seed)).encode("ascii")).digest()
    return files[int.from_bytes(digest[:8], "big") % len(files)]


def choose_image(files, mode, image, seed, unique_id=None, pool_key="", edit_serial="", state=None):
    """(path to load this run, path the widget should hold for the next run or None).

    fixed: `image` itself. random: seeded pick from `files`. sequential: the root pack's pointer logic
    (`selection.resolve_filenames`), so batch queues and hand edits behave as in Load Random Image.
    """
    if not files:
        raise FileNotFoundError("no images in the chosen folder")
    if mode == "random":
        return pick_seeded(files, seed), None
    if mode == "sequential":
        chosen, following = sequential.resolve_filenames(
            files, False, True, image, unique_id=unique_id, directory=pool_key, edit_serial=edit_serial, state=state
        )
        return chosen, following
    return image, None
