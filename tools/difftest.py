"""Differential test: the recompiled H8S core against MAME.

The recompiled boot ROM runs 2819 dispatches from reset and then transfers to
address zero. Something before that computed a different answer from the
hardware, and 39,000 instructions is far too many to read. Running MAME beside
it and comparing every instruction says exactly which one.

Both sides record 40 big-endian bytes per instruction -- pc, ER0..ER7, CCR --
sampled *before* the instruction executes.

    python tools/difftest.py <ours.bin> <mame.bin>

The two traces are not expected to be the same length; the comparison stops at
the shorter. Nor do they have to start together: MAME is traced from power-on
and may run setup our harness does not, so the tool finds the first place the
PC streams agree and aligns there.

**The H8S prefetches, so a fetch trace is not an execution trace.**

This is the thing to know before trusting any result here. Tapping instruction
fetches looks like it gives the executed instruction stream, and it does not.
The CPU fetches the word following a branch while the branch is still
executing; when the branch is taken that word is discarded, but the tap has
already recorded it. In the boot ROM's first copy loop:

    address    MAME    ours
    000D92        1     798      branch target
    000D94      798     798      loop body -- identical
    000D96      798     798
    000D98      798     798
    000D9C      797       0      fall-through, prefetched and discarded

The loop ran exactly 798 times on both sides. The cores agree completely; the
*instrument* disagrees, and comparing the streams position-by-position reports
a divergence at instruction 15 that does not exist.

So a PC-stream comparison is only sound on straight-line code. Comparing
memory *writes* instead would not have this problem -- a write happens only
when an instruction really executes -- and that is the direction to take this
if a real divergence needs finding.
"""
import struct
import sys

REC = 40
FIELDS = ("pc", "ER0", "ER1", "ER2", "ER3", "ER4", "ER5", "ER6", "ER7", "CCR")


def load(path):
    raw = open(path, "rb").read()
    n = len(raw) // REC
    return [struct.unpack_from(">10I", raw, i * REC) for i in range(n)]


def align(ours, theirs, window=64, run=16):
    """Offset into `theirs` where its PC stream starts matching ours.

    Compares a run of consecutive PCs rather than a single one, because a
    single address recurs constantly in a loop and would align anywhere.
    """
    if not ours:
        return 0
    want = [r[0] for r in ours[:run]]
    for off in range(min(window, max(0, len(theirs) - run))):
        if [r[0] for r in theirs[off:off + run]] == want:
            return off
    return None


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    ours = load(argv[0])
    theirs = load(argv[1])
    print("ours   %d instructions" % len(ours))
    print("mame   %d instructions" % len(theirs))

    off = align(ours, theirs)
    if off is None:
        print("\nthe two PC streams never line up.")
        print("  ours starts : %s" % " ".join("%06X" % r[0] for r in ours[:8]))
        print("  mame starts : %s" % " ".join("%06X" % r[0] for r in theirs[:8]))
        return 1
    if off:
        print("aligned at mame instruction %d" % off)
    theirs = theirs[off:]

    n = min(len(ours), len(theirs))
    print("comparing %d instructions\n" % n)

    for i in range(n):
        a, b = ours[i], theirs[i]
        if a == b:
            continue
        print("DIVERGENCE at instruction %d, pc=0x%06X" % (i, b[0]))
        for j, name in enumerate(FIELDS):
            mark = "   <--" if a[j] != b[j] else ""
            print("  %-4s ours %08X   mame %08X%s" % (name, a[j], b[j], mark))
        print("\n  last 6 agreeing:")
        for k in range(max(0, i - 6), i):
            r = ours[k]
            print("    %5d  pc=%06X ER0=%08X ER1=%08X ER2=%08X SP=%08X CCR=%02X"
                  % (k, r[0], r[1], r[2], r[3], r[8], r[9]))
        return 1

    print("no divergence in %d instructions" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
