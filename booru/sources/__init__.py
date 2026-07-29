from .gelbooru import Gelbooru

_SOURCE_CLASSES = {
    Gelbooru.name: Gelbooru,
}

# instantiated once each: the backends are stateless apart from module-level
# caches, and the node/routes both want the same objects
_INSTANCES = {name: cls() for name, cls in _SOURCE_CLASSES.items()}

SOURCE_NAMES = list(_INSTANCES)
DEFAULT_SOURCE = Gelbooru.name


def get_source(name):
    source = _INSTANCES.get(name)
    if source is None:
        raise KeyError(f"unknown booru source: {name}")
    return source


def max_positions():
    """Largest position count across all sources - the `index` widget's ceiling."""
    return max(source.max_positions for source in _INSTANCES.values())


__all__ = ["SOURCE_NAMES", "DEFAULT_SOURCE", "get_source", "max_positions"]
