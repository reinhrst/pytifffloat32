# helper libary to (pure-python) read and save tiff files
# Only tiff files with 3 or 4 channels, 32 bit float per channel, and lzw
# compression are supported (for now).
import os
import logging
import struct
import lzw
import numpy
import math

_MYDIR = os.path.dirname(os.path.realpath(__file__))
log = logging.getLogger()

VALUETYPE = {
    1: ["c",  1, lambda x: "".join(x)],  # BYTE
    2: ["c",  1, lambda x: "".join(x[:-1]).split("\x00")],  # ASCII
    3: ["H",  2, lambda x: list(x)],  # SHORT
    4: ["I",  4, lambda x: list(x)],  # LONG (actually int32)
    # RATIONAL: (two int32s, first num, second denom)
    5: ["ii", 8, lambda x: zip(x[::2], x[1::2])],
}


def _single_param(v):
    assert len(v) == 1
    return v[0]


def _id(v):
    return v

FIELD = [
    #  name                        id       transform    acceptable values
    ("width",                     0x100, _single_param),
    ("height",                    0x101, _single_param),
    ("bitspersample",             0x102, _id,           [[32, 32, 32, 32]]),
    # compression == 5: lzw
    ("compression",               0x103, _single_param, [5]),
    # photometricinterpretation == 2: RGB data
    ("photometricinterpreration", 0x106, _single_param, [2]),
    ("stripoffsets",              0x111, _id),
    ("orientation",               0x112, _single_param, [1]),
    ("samplesperpixel",           0x115, _single_param, [4]),
    ("rowsperstrip",              0x116, _single_param),
    ("stripbytecounts",           0x117, _id),
    ("planarconfig",              0x11C, _single_param, [1]),
    ("xposition",                 0x11E, _single_param, [(0, 1)]),
    ("yposition",                 0x11F, _single_param, [(0, 1)]),
    ("datetime",                  0x132, _single_param),
    # predictor == 3: float predictor: http://chriscox.org/TIFFTN3d1.pdf
    ("predictor",                 0x13D, _single_param, [3]),
    # extrasamples == 1: fourth channel = alpha
    ("extrasamples",              0x152, _single_param, [1]),
    # sampleformat 3 means float
    ("sampleformat",              0x153, _id, [[3, 3, 3, 3]]),
    ("xml",                       0x2bc, _id),
]

__FIELD_BY_ID_MAP = {values[1]: values for values in FIELD}


def read_uint32(f):
    """
    reads a singe uint32 (little endian) from a file. Filepointer progresses
    4 bytes.
    """
    return struct.unpack("<I", f.read(4))[0]


def read_uint16(f):
    return struct.unpack("<H", f.read(2))[0]


def read_tiff(filename):
    DIRECTORY_ENTRY_LENGTH = 12
    with open(filename) as tifffile:
        header = tifffile.read(4)
        assert header == '\x49\x49\x2a\x00', "TIFF header not found"
        directorystart = read_uint32(tifffile)
        log.debug("directory start at 0x%x", directorystart)
        tifffile.seek(directorystart)
        directorylength = read_uint16(tifffile)
        log.debug("directory length: %d", directorylength)
        directory = {}
        for i in range(directorylength):
            tifffile.seek(directorystart + 2 + DIRECTORY_ENTRY_LENGTH * i)
            tag = read_uint16(tifffile)
            valuetype = read_uint16(tifffile)
            length = read_uint32(tifffile)
            typelen = VALUETYPE[valuetype][1]
            if length * typelen > 4:
                pointer = read_uint32(tifffile)
                tifffile.seek(pointer)
            raw_values = struct.unpack("<" + length * VALUETYPE[valuetype][0],
                                       tifffile.read(length * typelen))
            values = VALUETYPE[valuetype][2](raw_values)
            assert tag in __FIELD_BY_ID_MAP, "Tag 0x%x not found" % tag
            fielddata = __FIELD_BY_ID_MAP[tag]
            value = fielddata[2](values)
            if len(fielddata) == 4:
                assert value in fielddata[3], \
                    "Value not acceptable: %s %s" % (fielddata[0], repr(value))
            directory[fielddata[0]] = value
            log.debug("Found tag: %s = %s", fielddata[0], repr(value))
        assert len(directory["bitspersample"]) == directory["samplesperpixel"]
        assert len(directory["sampleformat"]) == directory["samplesperpixel"]
        nrstrips = int(math.ceil(float(directory["height"]) /
                                 directory["rowsperstrip"]))
        assert len(directory["stripoffsets"]) == nrstrips
        assert len(directory["stripbytecounts"]) == nrstrips
        assert len(FIELD) == len(directory), "Not all fields present"

        imageasstring = ""
        # read the strips
        for stripnr in range(nrstrips):
            nrrows = min(directory["height"] -
                         directory["rowsperstrip"] * stripnr,
                         directory["rowsperstrip"])
            nrpixels = directory["width"] * nrrows
            nrbytes = nrpixels * sum(directory["bitspersample"]) / 8

            tifffile.seek(directory["stripoffsets"][stripnr])
            assert directory["compression"] == 5  # lzw
            lzwstrip = tifffile.read(directory["stripbytecounts"][stripnr])
            predictedstrip = numpy.fromstring(lzw.decompress(lzwstrip),
                                              dtype=numpy.uint8)
            assert len(predictedstrip) == nrbytes
            assert directory["predictor"] == 3  # float predictor
            # undo prediction in two steps:
            # first add the value or the previous 4 columns to the next
            # over the whole strip (should probably optimise)
            width = directory["width"]
            nrchannels = directory["samplesperpixel"]
            bytespersample = directory["bitspersample"][0] / 8
            assert len(set(directory["bitspersample"])) == 1, \
                "Images with different number of bits per sample per channel" \
                " not supported"
            cumsummedstrip = (predictedstrip.reshape(
                (nrrows, width * bytespersample, nrchannels)).
                cumsum(1, dtype=numpy.uint8))
            # then re-arrange the value. if the width is 640 and 4 float32 per
            # pixel
            strip = (cumsummedstrip.reshape(
                # reverse the order of columns, to go from bit to little endian
                (nrrows, bytespersample, width * nrchannels))[:, ::-1, :].
                # transpose in the second dimension to descramble the parts
                # of the individual floats
                transpose(0, 2, 1).flatten().tostring())
            imageasstring += strip
        flatimage = numpy.fromstring(imageasstring, dtype=numpy.float32)
        return flatimage.reshape((directory["height"], directory["width"],
                                  directory["samplesperpixel"]))


if __name__ == "__main__":
    import shared
    logging.basicConfig()
    log.setLevel(logging.DEBUG)
    image = read_tiff(os.path.join(_MYDIR, "tifftest.tif"))
    shared.save_image("/tmp/test.tif", image.shape[1], image.shape[0], image)
