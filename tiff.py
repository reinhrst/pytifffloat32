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

VT_BYTE = 1
VT_ASCII = 2
VT_SHORT = 3
VT_LONG = 4      # TIFF LONGS ar 32 bits
VT_RATIONAL = 5  # RATIONAL is fraction: first int32 / second int32
VALUETYPE = {
    VT_BYTE:     ["c",  1, lambda x: "".join(x)],
    VT_ASCII:    ["c",  1, lambda x: "".join(x[:-1]).split("\x00")],
    VT_SHORT:    ["H",  2, lambda x: list(x)],
    VT_LONG:     ["I",  4, lambda x: list(x)],
    VT_RATIONAL: ["ii", 8, lambda x: zip(x[::2], x[1::2])],
}


def _single_param(v):
    assert len(v) == 1
    return v[0]


def _id(v):
    return v

DIRECTORY_ENTRY_LENGTH = 12
TIFF_HEADER = '\x49\x49\x2a\x00'
END_OF_DIRECTORY_PADDING = '\x00\x00\x00\x00'

COMPRESSION_NONE = 1
COMPRESSION_LZW = 5
PREDICTOR_NONE = 1
PREDICTOR_FLOAT = 3
EXTRASAMPLES_ALPHA = 1
PHOTOMETRIC_RGB = 2
SAMPLEFORMAT_FLOAT = 3
FIELD = [
    #  name              id       transform    acceptable values
    ("width",           0x100, _single_param),
    ("height",          0x101, _single_param),
    ("bitspersample",   0x102, _id,           [[32, 32, 32, 32]]),
    ("compression",     0x103, _single_param, [COMPRESSION_LZW]),
    ("photometric",     0x106, _single_param, [PHOTOMETRIC_RGB]),
    ("stripoffsets",    0x111, _id),
    ("orientation",     0x112, _single_param, [1]),
    ("samplesperpixel", 0x115, _single_param, [4]),
    ("rowsperstrip",    0x116, _single_param),
    ("stripbytecounts", 0x117, _id),
    ("planarconfig",    0x11C, _single_param, [1]),
    ("xposition",       0x11E, _single_param, [(0, 1)]),
    ("yposition",       0x11F, _single_param, [(0, 1)]),
    ("datetime",        0x132, _single_param),
    # predictor: http://chriscox.org/TIFFTN3d1.pdf
    ("predictor",       0x13D, _single_param, [PREDICTOR_FLOAT]),
    ("extrasamples",    0x152, _single_param, [EXTRASAMPLES_ALPHA]),
    ("sampleformat",    0x153, _id, [4 * [SAMPLEFORMAT_FLOAT]]),
    ("xml",             0x2bc, _id),
]

__FIELD_BY_ID_MAP = {values[1]: values for values in FIELD}


def read_uint32(f):
    """
    reads a singe uint32 (little endian) from a file. Filepointer progresses
    4 bytes.
    """
    return struct.unpack("<I", f.read(4))[0]


def write_uint32(f, i):
    f.write(struct.pack("<I", i))


def read_uint16(f):
    return struct.unpack("<H", f.read(2))[0]


def write_uint16(f, i):
    f.write(struct.pack("<H", i))


def read_tiff(filename):
    with open(filename) as tifffile:
        header = tifffile.read(4)
        assert header == TIFF_HEADER, "TIFF header not found"
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


def write_tiff(filename, data):
    """
    expects data to be a 3-dimensional numpy array (height, width, channels)
    of type numpy.float32
    """
    assert len(data.shape) == 3
    height, width, nrchannels = data.shape
    assert nrchannels == 4
    ROWSPERSTRIP = 32
    FIRSTSTRIP = 8
    BITSPERSAMPLE = 32
    stripoffsets = []
    stripbytecounts = []
    directory = {
        "width": (width, VT_SHORT),
        "height": (height, VT_SHORT),
        "bitspersample": (nrchannels * [BITSPERSAMPLE], VT_SHORT),
        "compression": (COMPRESSION_LZW, VT_SHORT),
        "photometric": (PHOTOMETRIC_RGB, VT_SHORT),
        "stripoffsets": (stripoffsets, VT_LONG),
        "orientation": (1, VT_SHORT),
        "samplesperpixel": (nrchannels, VT_SHORT),
        "rowsperstrip": (ROWSPERSTRIP, VT_SHORT),
        "stripbytecounts": (stripbytecounts, VT_LONG),
        "planarconfig": (1, VT_SHORT),
        "xposition": ((0, 1), VT_RATIONAL),
        "yposition": ((0, 1), VT_RATIONAL),
        "datetime": ("some time long ago", VT_ASCII),
        "predictor": (PREDICTOR_FLOAT, VT_SHORT),
        "extrasamples": (EXTRASAMPLES_ALPHA, VT_SHORT),
        "sampleformat": (SAMPLEFORMAT_FLOAT, VT_SHORT),
        "xml": ("dontcare", VT_BYTE)
    }
    nrstrips = int(math.ceil(float(height) / ROWSPERSTRIP))
    stripstart = FIRSTSTRIP
    stripdata = []
    for stripnr in range(nrstrips):
        nrrows = min(height - ROWSPERSTRIP * stripnr, ROWSPERSTRIP)
        bytespersample = BITSPERSAMPLE / 8

        stripstring = data[stripnr * ROWSPERSTRIP:][:ROWSPERSTRIP].tostring()
        stripbytes = numpy.fromstring(stripstring, dtype=numpy.uint8)
        # reverse the thing we do in reading
        cumsummedstrip = (stripbytes.reshape(
            (nrrows, width * nrchannels, bytespersample))[:, :, ::-1].
            transpose(0, 2, 1))
        reshapedcumsummedstrip = cumsummedstrip.reshape(
            (nrrows, width * bytespersample, nrchannels))
        # now the second step is slightly more complex than in the read-case
        diffstrip = numpy.diff(reshapedcumsummedstrip, axis=1)
        # because the diffstrip only contains diffs, not the starting value
        # so we have to re-attach the staring column
        predictedstrip = numpy.concatenate((reshapedcumsummedstrip[:, 0:1, :],
                                            diffstrip), axis=1).tostring()

        compressedstrip = lzw.compress(predictedstrip)
        stripoffsets.append(stripstart)
        stripbytecounts.append(len(compressedstrip))
        stripstart += len(compressedstrip)
        stripdata.append(compressedstrip)

    log.debug("Found strips of sizes: %s", repr(stripbytecounts))

    with open(filename, "w+b") as f:
        f.write(TIFF_HEADER)
        directorystart = stripstart
        write_uint32(f, directorystart)
        # pad.... Not sure if we need the padding at all or can just have the
        # first strip start at position 8....
        while f.tell() < FIRSTSTRIP:
            f.write('\x00')
        for stripstring in stripdata:
            f.write(stripstring)
        assert f.tell() == directorystart
        write_uint16(f, len(directory))
        extradatastart = (directorystart + 2 +
                          DIRECTORY_ENTRY_LENGTH * len(directory) +
                          len(END_OF_DIRECTORY_PADDING))
        extradata = ""

        assert len(directory) == len(FIELD)
        for info in FIELD:
            tagname, tag = info[:2]
            assert tagname in directory

            value = directory[tagname][0]
            vt_type = directory[tagname][1]
            write_uint16(f, tag)
            write_uint16(f, vt_type)

            if isinstance(value, list):
                values = value
            else:
                values = [value]

            if vt_type == VT_BYTE:
                towrite = value
            elif vt_type == VT_ASCII:
                towrite = "\x00".join(values) + "\x00"
            elif vt_type in [VT_SHORT, VT_LONG]:
                packformat = "<" + len(values) * VALUETYPE[vt_type][0]
                towrite = struct.pack(packformat, *values)
            else:
                assert vt_type == VT_RATIONAL
                packformat = "<" + len(values) * VALUETYPE[vt_type][0]
                topack = sum(values, ())
                towrite = struct.pack(packformat, *topack)

            length = len(towrite) / VALUETYPE[vt_type][1]
            write_uint32(f, length)

            if len(towrite) > 4:
                pointer = extradatastart + len(extradata)
                write_uint32(f, pointer)
                extradata += towrite
            else:
                f.write((towrite + 4 * '\x00')[:4])
        f.write(END_OF_DIRECTORY_PADDING)
        assert f.tell() == extradatastart
        if extradata:
            f.write(extradata)


if __name__ == "__main__":
    import shared
    logging.basicConfig()
    log.setLevel(logging.INFO)
    (width, height, image) = shared.read_image(os.path.join(_MYDIR,
                                                            "tifftest.tif"))
    write_tiff("/tmp/test.tif", image.reshape(height, width, 4))
    # image = read_tiff(os.path.join(_MYDIR, "tifftest.tif"))
    # shared.save_image("/tmp/test.tif", image.shape[1], image.shape[0], image)
