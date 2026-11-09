"""A minimal Ollama chat wrapper (`OllamaChat`): address, model, prompt, optional images, a JSON of options.

Deliberately empty of imports: the pack's top-level __init__.py pulls `ollama_chat.nodes` in itself, so
this package can be imported (by the tests, for instance) without dragging torch along.
"""
