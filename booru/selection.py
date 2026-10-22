import random
import threading

_INCREMENT_STATE = {}
_INCREMENT_LOCK = threading.Lock()


def resolve_index(
    total,
    random_post,
    increment_on_queue,
    index,
    unique_id=None,
    search_key=None,
    state=None,
    rng=random,
    edit_serial="",
):
    """Returns (chosen, next_index) for a result list of `total` posts.

    `chosen` is the position loaded and sent downstream THIS run. `next_index`
    is pushed back into the widget after execution, becoming the starting
    point for the NEXT run - the advance always happens after the current post
    has already been output, never before.

    Increment mode keeps an in-memory pointer keyed by (unique_id, search_key)
    next to the `index` that run was given. Without a pointer, queuing several
    executions back-to-back (e.g. a batch count > 1) would have every one of
    them read the same `index` snapshotted at queue time and all load the same
    post instead of advancing. So a run arriving with the SAME `index` as the
    previous run is such a snapshot - follow the pointer. A different `index`
    means the widget moved since (manual pick, the frontend syncing in the
    advance, a reloaded workflow) and the widget wins. `search_key` (source +
    tags) is folded into the key since ComfyUI's unique_id is just a small
    per-graph integer, not globally unique - two unrelated workflows reusing
    the same node id would otherwise share (and corrupt) each other's pointer.

    `edit_serial` removes the guesswork from that rule. The frontend writes a fresh
    serial whenever the user changes the position by hand. With a serial set, a run
    carrying the same serial as the previous one has no hand edit in between, so the
    pointer is right whatever the widget says (a batch whose later items were
    serialized after the UI synced an earlier run's advance carries an in-between
    value no equality test could recognise); a different serial is a deliberate
    edit - even typing back the very number the previous run started with - and the
    widget wins. Callers that never set it (always "") keep the value-based rule above.
    """
    if total <= 0:
        raise ValueError("empty result list")
    if state is None:
        state = _INCREMENT_STATE

    if random_post:
        chosen = rng.randrange(total)
        return chosen, chosen

    if increment_on_queue:
        key = (unique_id, search_key)
        with _INCREMENT_LOCK:
            pointer, seen, seen_serial = state.get(key, (None, None, ""))
            if edit_serial:
                follow_pointer = edit_serial == seen_serial
            else:
                follow_pointer = seen == index and not seen_serial
            if _in_range(pointer, total) and follow_pointer:
                chosen = pointer
            elif _in_range(index, total):
                chosen = index
            else:
                chosen = pointer if _in_range(pointer, total) else 0
            next_index = (chosen + 1) % total
            state[key] = (next_index, index, edit_serial)
        return chosen, next_index

    chosen = index if _in_range(index, total) else 0
    return chosen, chosen


def snapshot_increment(unique_id, search_key, state=None):
    """The increment entry for this node + search as it is now (None when there is none yet)."""
    state = _INCREMENT_STATE if state is None else state
    with _INCREMENT_LOCK:
        return state.get((unique_id, search_key))


def restore_increment(unique_id, search_key, entry, state=None):
    """Put back what snapshot_increment() returned: a run that failed must not use up its position."""
    state = _INCREMENT_STATE if state is None else state
    key = (unique_id, search_key)
    with _INCREMENT_LOCK:
        if entry is None:
            state.pop(key, None)
        else:
            state[key] = entry


def _in_range(value, total):
    return isinstance(value, int) and 0 <= value < total
