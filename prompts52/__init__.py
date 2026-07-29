"""Text-prompt loader backed by 52prompts.com (`LoadRandom52Prompt`).

Deliberately empty of imports: the pack's top-level __init__.py pulls
`prompts52.nodes` and `prompts52.routes` in itself, so this package can be
imported (by the tests, for instance) without dragging aiohttp along.
"""
