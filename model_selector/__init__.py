"""Bart's Model Selector (`ModelSelector`): one node that loads a model whatever its format and wherever it lies
(checkpoint, diffusion model, text encoder, VAE, CLIP vision; safetensors, pickle files, GGUF) and hands out what
the file holds - see ../README.md.

Deliberately empty of imports: the pack's top-level __init__.py pulls `model_selector.nodes` and
`model_selector.routes` in itself, so this package can be imported (by the tests, for instance) without dragging
torch or aiohttp along.
"""
