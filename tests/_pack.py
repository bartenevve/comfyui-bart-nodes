"""Import pack submodules under a synthetic package name.

The repo directory is named with dashes (not importable) and its __init__.py
pulls in torch/aiohttp, so the namespace is built by hand here and only the
network-free submodules are imported from it. This mirrors how ComfyUI loads
the pack - as a package - which `booru/sources/*`'s `from .. import fetch`
needs, and it keeps `booru/selection.py` and the top-level `selection.py` in
separate module namespaces instead of fighting over the name `selection`.
"""

import importlib
import pathlib
import sys
import types

PACKAGE_NAME = "random_image_pack_under_test"
ROOT = pathlib.Path(__file__).resolve().parents[1]

if PACKAGE_NAME not in sys.modules:
    package = types.ModuleType(PACKAGE_NAME)
    package.__path__ = [str(ROOT)]
    sys.modules[PACKAGE_NAME] = package


def module(dotted_name):
    """Import e.g. "booru.selection" from the pack."""
    return importlib.import_module(f"{PACKAGE_NAME}.{dotted_name}")
