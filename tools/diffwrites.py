"""Compare the byte-write streams of the recompiled core and MAME.

Writes are the signal a PC trace could not be: the H8S prefetches, so a fetch
tap records instructions that never execute, but a store happens only when an
instruction really runs. Two cores computing the same thing write the same
bytes to the same addresses in the same order.

    python tools/diffwrites.py <ours.bin> <mame.bin>

Both files are 8 bytes per byte-write, big-endian: addr, value.
"""
import struct
import sys

REC = 8


def load(path):
    raw = open(path, "rb").read()
    return [struct.unpack_from(">II", raw, i * REC)
            for i in range(len(raw) // REC)]


def align(ours, theirs, window=4096, run=24):
    """Offset into `theirs` where it starts matching ours.

    MAME runs from power-on and our harness starts at the reset vector with a
    stack already set, so the streams do not begin together. A run of matching
    writes is required rather than one, since a single store to a common
    address means nothing.
    """
    if len(ours) < run:
        return 0
    want = ours[:run]
    for off in range(min(window, max(0, len(theirs) - run))):
        if theirs[off:off + run] == want:
            return off
    return None


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    ours, theirs = load(argv[0]), load(argv[1])
    print("ours   %d byte-writes" % len(ours))
    print("mame   %d byte-writes" % len(theirs))

    off = align(ours, theirs)
    if off is None:
        print("\nthe streams never line up.")
        print("  ours  : %s" % " ".join("%06X=%02X" % w for w in ours[:8]))
        print("  mame  : %s" % " ".join("%06X=%02X" % w for w in theirs[:8]))
        return 1
    if off:
        print("aligned at mame write %d" % off)
    theirs = theirs[off:]

    n = min(len(ours), len(theirs))
    print("comparing %d byte-writes\n" % n)

    for i in range(n):
        if ours[i] == theirs[i]:
            continue
        print("DIVERGENCE at byte-write %d" % i)
        print("  ours  0x%06X = 0x%02X" % ours[i])
        print("  mame  0x%06X = 0x%02X" % theirs[i])
        print("\n  last 8 agreeing:")
        for k in range(max(0, i - 8), i):
            print("    %6d  0x%06X = 0x%02X" % (k, ours[k][0], ours[k][1]))
        return 1

    print("no divergence in %d byte-writes" % n)
    if len(ours) != len(theirs):
        print("(streams differ in length: ours %d, mame %d -- ours stopped "
              "first)" % (len(ours), len(theirs)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
