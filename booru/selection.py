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
):
    """Returns (chosen, next_index) for a result list of `total` posts.

    `chosen` is the position loaded and sent downstream THIS run. `next_index`
    is pushed back into the widget after execution, becoming the starting
    point for the NEXT run - the advance always happens after the current post
    has already been output, never before.

    Increment mode keeps an in-memory pointer keyed by (unique_id, search_key)
    as the source of truth once seeded from `index`. Without it, queuing
    several executions back-to-back (e.g. a batch count > 1) would have every
    one of them read the same `index` snapshotted at queue time and all load
    the same post instead of advancing - the in-memory pointer is only visible
    to executions that have actually run, so each one sees the real advance
    made by the one before it. `search_key` (source + tags) is folded into the
    key since ComfyUI's unique_id is just a small per-graph integer, not
    globally unique - two unrelated workflows reusing the same node id would
    otherwise share (and corrupt) each other's pointer.
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
            current = state.get(key)
            chosen = current if _in_range(current, total) else (index if _in_range(index, total) else 0)
            next_index = (chosen + 1) % total
            state[key] = next_index
        return chosen, next_index

    chosen = index if _in_range(index, total) else 0
    return chosen, chosen


def _in_range(value, total):
    return isinstance(value, int) and 0 <= value < total
