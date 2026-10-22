import os
import threading
import urllib.parse
from collections import OrderedDict

from . import fetch
from .selection import resolve_index, restore_increment, snapshot_increment
from .sources import get_source
from .sources.base import IMAGE_EXTENSIONS

RANDOM_RETRIES = 5

# post -> original file URL, remembered from the pick that resolved it: showing a post that is
# already on disk (every preview, every reload) then costs no request to the board at all
_FILE_URLS = OrderedDict()
_FILE_URLS_LOCK = threading.Lock()
_FILE_URLS_MAX = 512


def remember_file_url(source_name, post_id, url):
    with _FILE_URLS_LOCK:
        _FILE_URLS[(source_name, str(post_id))] = url
        _FILE_URLS.move_to_end((source_name, str(post_id)))
        while len(_FILE_URLS) > _FILE_URLS_MAX:
            _FILE_URLS.popitem(last=False)


def known_file_url(source_name, post_id):
    with _FILE_URLS_LOCK:
        return _FILE_URLS.get((source_name, str(post_id)))


class NoPostsError(RuntimeError):
    pass


class UnsupportedPostError(RuntimeError):
    pass


def search_key(source_name, tags):
    # length-prefixed so ("gel", "a b") and ("gel a", "b") can't collide
    return f"{len(source_name)}:{source_name}|{tags}"


def is_image_url(url):
    extension = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
    return extension in IMAGE_EXTENSIONS


def pick(
    source_name,
    tags,
    random_post=True,
    increment_on_queue=False,
    index=0,
    unique_id=None,
    download=True,
    edit_serial="",
):
    """Resolve a position into a post (and its local file), honoring the mode.

    Returns a dict with the post's metadata plus `index` (the position actually
    used) and `next_index` (what the widget should hold for the next run).
    Random and increment modes skip posts we can't decode (videos) and try
    another position - a random one, or the next in line. Skipping is the point
    of increment mode: stopping with an error on every video would leave the
    pointer, which has already stepped past it, and the user at a dead end.
    Only fixed mode, where the user named an exact position, must not drift
    off it, so it raises instead.
    """
    source = get_source(source_name)
    tags = tags.strip()

    total = source.count(tags)
    if total <= 0:
        raise NoPostsError(f"no posts found for tags: {tags or '(any)'}")

    key = search_key(source_name, tags)
    # a run that dies on a flaky network must not use up its position: step back and the
    # next queue tries the same post (a post that is gone for good still moves on)
    previous = snapshot_increment(unique_id, key) if increment_on_queue else None

    attempts = RANDOM_RETRIES if (random_post or increment_on_queue) else 1
    last_error = None
    for _ in range(attempts):
        chosen, next_index = resolve_index(
            total,
            random_post,
            increment_on_queue,
            index,
            unique_id=unique_id,
            search_key=key,
            edit_serial=edit_serial,
        )
        try:
            post = source.get_post(tags, chosen)
            file_url = source.resolve_file_url(post.post_id)
            remember_file_url(source_name, post.post_id, file_url)
            if is_image_url(file_url):
                path = source.download(file_url) if download else None
        except fetch.FetchError as exc:
            if increment_on_queue and exc.transient:
                restore_increment(unique_id, key, previous)
            raise

        if not is_image_url(file_url):
            last_error = UnsupportedPostError(
                f"post {post.post_id} is not a still image ({file_url.rsplit('.', 1)[-1]}); "
                "add -animated -video to the tags to exclude these"
            )
            continue

        return {
            "post_id": post.post_id,
            "index": chosen,
            "next_index": next_index,
            "total": total,
            "tags": post.tags,
            "rating": post.rating,
            "page_url": post.page_url,
            "thumb_url": post.thumb_url,
            "file_url": file_url,
            "path": path,
        }

    raise last_error


def fetch_post_file(source_name, post_id):
    """Local path of a post's original file, by post id."""
    source = get_source(source_name)
    known = known_file_url(source_name, post_id)
    if known:
        try:
            return source.download(known)  # served from disk when it is already there
        except (fetch.FetchError, LookupError):
            pass  # a stale link: ask the board again below
    file_url = source.resolve_file_url(str(post_id))
    if not is_image_url(file_url):
        raise UnsupportedPostError(f"post {post_id} is not a still image: {file_url}")
    remember_file_url(source_name, post_id, file_url)
    return source.download(file_url)
