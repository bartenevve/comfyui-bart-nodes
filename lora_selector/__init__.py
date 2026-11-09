"""Bart's Lora Selector (`LoraSelector`): several LoRAs on one node, each with a switch and a strength,
chosen on a screen that shows what is known about every file - see ../README.md.

Deliberately empty of imports: the pack's top-level __init__.py pulls `lora_selector.nodes` and
`lora_selector.routes` in itself, so this package can be imported (by the tests, for instance) without
dragging torch or aiohttp along.
"""
