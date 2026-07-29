import os
import urllib.parse

from .selection import resolve_index
from .sources import get_source
from .sources.base import IMAGE_EXTENSIONS

RANDOM_RETRIES = 5


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
):
    """Resolve a position into a post (and its local file), honoring the mode.

    Returns a dict with the post's metadata plus `index` (the position actually
    used) and `next_index` (what the widget should hold for the next run).
    Random mode retries on posts we can't decode (videos), since a fresh
    position is free there; the fixed/increment modes must not silently drift
    off the position the user asked for, so they raise instead.
    """
    source = get_source(source_name)
    tags = tags.strip()

    total = source.count(tags)
    if total <= 0:
        raise NoPostsError(f"no posts found for tags: {tags or '(any)'}")

    attempts = RANDOM_RETRIES if random_post else 1
    last_error = None
    for _ in range(attempts):
        chosen, next_index = resolve_index(
            total,
            random_post,
            increment_on_queue,
            index,
            unique_id=unique_id,
            search_key=search_key(source_name, tags),
        )
        post = source.get_post(tags, chosen)
        file_url = source.resolve_file_url(post.post_id)

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
            "path": source.download(file_url) if download else None,
        }

    raise last_error


def fetch_post_file(source_name, post_id):
    """Local path of a post's original file, by post id."""
    source = get_source(source_name)
    file_url = source.resolve_file_url(str(post_id))
    if not is_image_url(file_url):
        raise UnsupportedPostError(f"post {post_id} is not a still image: {file_url}")
    return source.download(file_url)
