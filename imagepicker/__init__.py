"""Touch-friendly image picker for ComfyUI's input folder (`ImagePicker`) - see ../README.md.

Deliberately empty of imports: the pack's top-level __init__.py pulls
`imagepicker.nodes` and `imagepicker.routes` in itself, so this package can be
imported (by the tests, for instance) without dragging torch/aiohttp along.
"""
