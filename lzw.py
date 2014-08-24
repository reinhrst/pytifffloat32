"""
Pure python lzw implementation
Algorithm from http://en.wikipedia.org/wiki/Lempel-Ziv-Welch


Could probably be made faster through the use of bitstrings... And through some
other magic as well.
"""
import logging
import os
import struct
import binascii
log = logging.getLogger()
_MYDIR = os.path.dirname(os.path.realpath(__file__))

CLEAR_CODE = 256
END_OF_INFO_CODE = 257

START_BIT_WIDTH = 9
MAX_BIT_WIDTH = 12


def decompress(bytelist):
    """
    gets a list of bytes (string) as input, returns a list of bytes (string)
    as output; assumes msb_first (used in tiff encoding)
    """
    lookup = map(chr, range(0x100)) + [CLEAR_CODE, END_OF_INFO_CODE]

    lastbytes = None
    outputbytes = ""
    bitoffset = 0
    bitwidth = START_BIT_WIDTH
    while bitoffset / 8 != len(bytelist) - 1:
        startbyte = bitoffset / 8
        word = bytelist[startbyte:startbyte + 4]
        if len(word) < 4:
            word += (4 - len(word)) * '\x00'
        shift = 32 - (bitoffset - bitoffset / 8 * 8) - bitwidth
        mask = (1 << bitwidth) - 1
        code = (struct.unpack(">I", word)[0] >> shift) & mask
        if code == CLEAR_CODE:
            logging.debug("Resetting bitwidth")
            bitoffset += bitwidth
            bitwidth = START_BIT_WIDTH
            lastbytes = None
            lookup = lookup[:0x102]
            continue
        if code == END_OF_INFO_CODE:
            assert (bitoffset + bitwidth - 1) / 8 == len(bytelist) - 1, \
                "End of info code, but not at the end of the string"
            break
        bitoffset += bitwidth
        log.debug("found code %d", code)
        if code < len(lookup):
            lookedup = lookup[code]
        else:
            assert code == len(lookup)
            # special case: repeat the first
            lookedup = lastbytes + lastbytes[0]
        if lastbytes is not None:
            lookup.append(lastbytes + lookedup[0])
        lastbytes = lookedup
        outputbytes += lookedup
        if len(lookup) == (1 << bitwidth) - 1 and bitwidth < MAX_BIT_WIDTH:
            bitwidth += 1
            log.debug("Switching to bitwidth %d" % bitwidth)
        log.debug("Adding bytes: %s (%d)", map(hex, map(ord, lookedup)),
                  len(outputbytes))
    log.debug("output: %s", map(hex, map(ord, outputbytes[:2000])))
    return outputbytes


def compress(bytelist):
    """
    decompress(compress(x)) == x
    (although not necessarily the other way around)
    """
    lookup = {chr(i): {'value': i} for i in range(0x100)}
    lookuplength = 0x102  # all chars + clearcode + endcode
    currentlookup = lookup

    bitwidth = START_BIT_WIDTH
    lookupmaxlength = 1 << bitwidth
    codes = [(CLEAR_CODE, bitwidth)]
    for c in bytelist:
        if c in currentlookup:
            currentlookup = currentlookup[c]
            continue
        # add new code to codes
        codes.append((currentlookup['value'], bitwidth))
        # add new entry in lookup table
        currentlookup[c] = {'value': lookuplength}
        lookuplength += 1

        if lookuplength == lookupmaxlength:
            if bitwidth < MAX_BIT_WIDTH:
                bitwidth += 1
                lookupmaxlength = 1 << bitwidth
                log.debug("Going to bitwidth %d", bitwidth)
            else:
                codes.append((CLEAR_CODE, bitwidth))
                bitwidth = START_BIT_WIDTH
                lookupmaxlength = 1 << bitwidth
                log.debug("Reset bitwidth to %d", bitwidth)
                lookup = {chr(i): {'value': i} for i in range(0x100)}
                lookuplength = 0x102  # all chars + clearcode + endcode
        # reset lookup (only do after potential lookup reset)
        currentlookup = lookup[c]

    codes.append((currentlookup['value'], bitwidth))
    codes.append((END_OF_INFO_CODE, bitwidth))

    # we all add it to a very long number, but don't make the number
    # too large, because it slows stuff down considerably
    values = [0L]
    width = 0
    for code, bitwidth in codes:
        values[-1] = values[-1] << bitwidth | code
        width += bitwidth
        if width % 8 == 0:
            values[-1] = ("%%0%dx" % (width / 4)) % values[-1]
            values.append(0L)
            width = 0
    if width == 0:
        # we were just done, so the last value should be empty
        values[-1] = ""
    else:
        # but the MSB nicely on a byte boundary
        if width % 8 != 0:
            shiftby = 8 - (width % 8)
            values[-1] <<= shiftby
            width += shiftby
        values[-1] = ("%%0%dx" % (width / 4)) % values[-1]
    compressed = binascii.a2b_hex("".join(values))
    return compressed


if __name__ == "__main__":
    logging.basicConfig()
    log.setLevel(logging.DEBUG)
    with open(__file__) as f:
        data = f.read()
    compresseddata = compress(data)
    decompresseddata = decompress(compresseddata)
    assert data == decompresseddata
    print "SUCCESS"
