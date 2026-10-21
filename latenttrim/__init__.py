"""Trim frames off the start of a WAN video latent (`WanLatentTrim`) - see ../README.md.

Deliberately empty of imports: the pack's top-level __init__.py pulls
`latenttrim.nodes` in itself, so this package can be imported (by the tests,
for instance) without dragging torch along.
"""
