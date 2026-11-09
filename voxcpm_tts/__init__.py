"""VoxCPM text-to-speech (`VoxCPMModelLoader`, `VoxCPMGenerate`) - see ../README.md.

Deliberately empty of imports: the pack's top-level __init__.py pulls `voxcpm_tts.nodes` in itself,
so this package can be imported (by the tests, for instance) without dragging torch along.
It is not called `voxcpm` so that it can never shadow the real `voxcpm` package it wraps.
"""
