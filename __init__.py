"""
This module is useful for those who like to play around with tiff images based
on floats, but don't want any dependencies.  As a pure-python program, this
will not be the fastest thing out there, but it get's the job done.
Most of the slowness comes from the lzw-compression; perhaps this can be
sped up with stock python; if you have ideas, please let me know :).
Currently a 640x480 image, 0.3 megapixel, 4 channels of float32, is about
5 MB of data. Louding this image takes about 2 seconds on my machine,
saving it takes 1.5 seconds.

This module depends on numpy. While not technically necessary,
it speeds up things a lot (the prediction-steps). In non-numpy python,
it will take easily 10 times as long. The actual step however of removing
numpy and writing that code as pure python, is not that hard.

Support for formats is limited to "what I need". At the moment, that is
images where each pixel is RGBA, each channel is float32; however I don't
promise to keep this description up to date when I add support for other
formats :)
"""
from tiff import read_tiff
from tiff import write_tiff

__all__ = [read_tiff, write_tiff]
