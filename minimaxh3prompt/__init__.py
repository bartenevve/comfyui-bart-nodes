"""MiniMax H3 prompt generator (`MiniMaxH3Prompt`) - see ../README.md.

Deliberately empty of imports: the pack's top-level __init__.py pulls
`minimaxh3prompt.nodes` and `minimaxh3prompt.routes` in itself, so this package
can be imported (by the tests, for instance) without dragging torch/aiohttp along.
`h3kit.py` is the prompt kit itself (stdlib only, usable as a CLI - see README_ru.md).
"""
