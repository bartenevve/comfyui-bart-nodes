"""Bart's Format Detector (`FormatDetector`): picks a video format (from a list, or by the proportions of an image)
and gives the width and height for a number of megapixels, with the image cropped and scaled to fill it - see
../README.md.

Deliberately empty of imports: the pack's top-level __init__.py pulls `format_detector.nodes` in itself, so this
package can be imported (by the tests, for instance) without dragging torch along.
"""
