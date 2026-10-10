"""Anatomy-defect filter (`AnatomyDefectFilter`) - see ../README.md.

Deliberately empty of imports, same reason as the other sub-packages: the
pack's top-level __init__.py pulls `anatomy.nodes` in itself, so `selection`
and `ollama` (stdlib only) can be imported by the tests without torch/PIL.
"""
