from dataclasses import dataclass

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


@dataclass
class Post:
    post_id: str
    page_url: str
    thumb_url: str
    tags: str = ""
    rating: str = ""


class BooruSource:
    """A tag-searchable image board.

    Positions ("index") are 0-based offsets into the site's default ordering
    for a tag query. `page_size` posts share one listing request, and
    `max_positions` caps how deep the site lets an anonymous client page.
    """

    name = ""
    page_size = 1
    max_positions = 1

    def count(self, tags):
        """Number of addressable positions for `tags` (already capped)."""
        raise NotImplementedError

    def page(self, tags, pid):
        """Posts of the listing page starting at offset `pid`."""
        raise NotImplementedError

    def resolve_file_url(self, post_id):
        """Original (full-size) file URL for a post."""
        raise NotImplementedError

    def download(self, url):
        """Fetch `url` to disk, returning the local path."""
        raise NotImplementedError

    def get_post(self, tags, index):
        """The post at `index`, resolved through one listing request."""
        pid = (index // self.page_size) * self.page_size
        posts = self.page(tags, pid)
        if not posts:
            raise LookupError(f"no posts at position {index} for tags: {tags or '(any)'}")
        offset = index - pid
        if offset >= len(posts):
            # the count is an upper bound when the last page is unreachable,
            # so a position can land past the real end - clamp to the last
            # post actually present instead of failing the run
            offset = len(posts) - 1
        return posts[offset]
