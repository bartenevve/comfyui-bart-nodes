import os
import random
import threading

VALID_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}

_SEQUENTIAL_STATE = {}
_SEQUENTIAL_LOCK = threading.Lock()


def list_images(directory):
    """Recursively list image files under directory, sorted case-insensitively."""
    files = []
    for root, _dirs, filenames in os.walk(directory):
        for name in filenames:
            if os.path.splitext(name)[1].lower() in VALID_EXTENSIONS:
                rel = os.path.relpath(os.path.join(root, name), directory)
                files.append(rel)
    files.sort(key=str.lower)
    return files


def resolve_filenames(
    files, randomize_on_queue, sequential_on_queue, filename, unique_id=None, directory=None, state=None
):
    """Returns (chosen, next_filename).

    `chosen` is loaded and sent downstream THIS run. `next_filename` is
    pushed back into the widget after execution, becoming the starting
    point for the NEXT run - the advance always happens after the current
    file has already been output, never before.

    Sequential mode keeps an in-memory pointer keyed by (unique_id, directory)
    next to the `filename` that run was given. Without a pointer, queuing
    several executions back-to-back (e.g. a batch count > 1) would have every
    one of them read the same `filename` snapshotted at queue time and all
    load the same file instead of advancing. So when a run arrives with the
    SAME `filename` as the previous run, it is such a snapshot - follow the
    pointer. When `filename` differs, the widget has moved since (a manual pick
    or dice roll, the frontend syncing in the advance, a reloaded workflow) and
    the widget wins: the file the user is looking at is the file that loads.
    `directory` is folded into the key since ComfyUI's unique_id is just a
    small per-graph integer, not globally unique - two unrelated workflows
    reusing the same node id would otherwise share (and corrupt) each other's
    pointer.
    """
    if state is None:
        state = _SEQUENTIAL_STATE

    if randomize_on_queue:
        chosen = random.choice(files)
        return chosen, chosen

    if sequential_on_queue:
        key = (unique_id, directory)
        with _SEQUENTIAL_LOCK:
            pointer, seen = state.get(key, (None, None))
            if pointer in files and seen == filename:
                chosen = pointer
            elif filename in files:
                chosen = filename
            else:
                chosen = pointer if pointer in files else files[0]
            next_filename = files[(files.index(chosen) + 1) % len(files)]
            state[key] = (next_filename, filename)
        return chosen, next_filename

    chosen = filename if (filename and filename in files) else files[0]
    return chosen, chosen
