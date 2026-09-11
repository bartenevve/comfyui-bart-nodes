"""YuE2-3B music generation wrapper (`YuE2ModelLoader`, `YuE2Plan`,
`YuE2Generate`) - see ../README.md.

Deliberately empty of imports, same reason as booru/prompts52: the pack's
top-level __init__.py pulls `yue2.nodes` in itself, so this package can be
imported (by tests) without dragging torch/the optional `yue2` pip package
along. `yue2.nodes` itself is markedly heavier than the other sub-packages -
it needs the `yue2` inference package (not on PyPI, see ../README.md for the
manual wheel install) and a CUDA GPU with 24GB+ VRAM to actually run - so the
top-level __init__.py imports it defensively and disables just this node if
it's missing, rather than letting the whole pack fail to load.
"""
