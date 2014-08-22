"""
Pure python lzw implementation
Algorithm from http://en.wikipedia.org/wiki/Lempel-Ziv-Welch
"""
import logging
import os
import struct
log = logging.getLogger()
_MYDIR = os.path.dirname(os.path.realpath(__file__))

CLEAR_CODE = 256
END_OF_INFO_CODE = 257

START_BIT_WIDTH = 9
MAX_BIT_WIDTH = 12


def decompress(bytelist):
    """
    gets a list of bytes as input, returns a list of bytes as output
    assumes lsb_first
    """
    log.setLevel(logging.INFO)
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
            assert (bitoffset + bitwidth) / 8 == len(bytelist) - 1, \
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
            log.debug("Switching to bitwidth %d" % bitwidth)
            bitwidth += 1
        log.debug("Adding bytes: %s (%d)", map(hex, map(ord, lookedup)),
                  len(outputbytes))
    log.debug("output: %s", map(hex, map(ord, outputbytes[:2000])))
    return outputbytes


if __name__ == "__main__":
    logging.basicConfig()
    log.setLevel(logging.DEBUG)
    with open(os.path.join(_MYDIR, "compresseddata.lzw")) as f:
        compresseddata = f.read()
    decompress(compresseddata)
