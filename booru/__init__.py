"""Booru-backed loader (`LoadRandomBooruImage`) - see ../README.md.

Deliberately empty of imports: the pack's top-level __init__.py pulls
`booru.nodes` and `booru.routes` in itself, so this package can be imported
(by the tests, for instance) without dragging torch/aiohttp along.
"""
