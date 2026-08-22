"""Static control-flow analysis of an H8S image.

Traces from the interrupt vector table, following every transfer whose target
is a build-time constant, and reports what it could not resolve.

This is where the H8S differs sharply from a small fixed-width machine. On the
Tamagotchi's 4-bit core every jump target was a constant because the only
page-changing instruction took an immediate. Here the CPU is a register machine
with `jsr @ERn`, `jmp @ERn` and `jmp @@aa:8` -- targets that live in a register
or behind a pointer, and no amount of staring at one instruction will tell you
where they go. The number this tool prints is therefore the honest one: how
much of the image can be reached *without guessing*.

    python tools/analyze.py <image.bin>
    python tools/analyze.py cyram.bin --base 0x200000 --prologues

The second form is for an image dumped out of RAM, which has no vector table
to start from -- see docs/CYOS.md.
"""
import sys
from collections import defaultdict

from h8s import (K_CALL, K_JCC, K_JMP, K_RET, K_RTE, K_TRAP, K_UNK,
                 decode, load, u32)

# H8S advanced mode: 256 vectors, four bytes each, starting at zero.
VECTOR_COUNT = 256
VECTOR_NAMES = {0: "reset", 7: "nmi"}


def vectors(d):
    """Plausible entry points from the vector table.

    Zero and 0xFFFFFFFF are unfilled slots. Anything landing outside the image
    is a vector into RAM or flash and is not ours to trace.
    """
    out = []
    for i in range(VECTOR_COUNT):
        off = 4 * i
        if off + 4 > len(d):
            break
        v = u32(d, off)
        if v in (0, 0xFFFFFFFF) or v >= len(d):
            continue
        out.append((i, v))
    return out


def pc_seeds(path):
    """Addresses actually executed, captured from a run under MAME.

    Static tracing only finds code whose entry is a constant somewhere. On a
    register machine that misses real code entirely -- the boot ROM reaches
    0x00204C through a computed path, and nothing in the image points at it.
    A recorded run has no such blind spot for the paths it took, and no
    guesswork at all: every address in the file was fetched as an instruction.

    It is the complement of prologue_seeds rather than a replacement. A trace
    covers what ran; prologues find functions that have not run yet.
    """
    out = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            a = int(line, 16)
            # MAME reports PC = 0 for the fetch that loads the reset vector,
            # so a raw capture always contains address 0 -- which is the
            # vector table, not code. Seeding on it makes the trace decode 256
            # longwords of addresses as instructions and walk off into them.
            if a < VECTOR_COUNT * 4:
                continue
            out.add(a)
    return out


def prologue_seeds(d, base=0, lo=0, hi=None):
    """Addresses that look like the start of a function.

    An image dumped out of RAM has no vector table and no symbols, so entry
    points have to be guessed -- and the compiler makes that easy, because it
    opens almost every non-leaf function by saving registers:

        01 n0 6D Fm      stm.l (ERm-ERm+n), @-sp

    Seeding a trace with all of them, then letting the trace discover the rest
    through direct calls, gets most of an image without any value analysis.
    Leaf functions that save nothing are missed, and are picked up later only
    if something calls them directly.
    """
    hi = hi if hi is not None else len(d)
    out = set()
    for a in range(lo, min(hi, len(d) - 4), 2):
        if (d[a] == 0x01 and d[a + 2] == 0x6D
                and (d[a + 1] & 0x8F) == 0 and (d[a + 3] & 0x80)):
            out.add(base + a)
    return out


# What is actually mapped in a combined Cybiko image. Everything else is the
# 0xFF fill cyimage.py pads with -- and 0xFF decodes as a perfectly valid
# `mov.b #imm, r7l`, so a trace that wanders into padding never stops and
# reports more "code" than the image contains. Ask before following.
CYBIKO_REGIONS = ((0x000000, 0x008000), (0x200000, 0x240000))


def in_region(a, regions):
    if not regions:
        return True
    return any(lo <= a < hi for lo, hi in regions)


def analyze(d, base=0, seeds=None, regions=None):
    """Trace an image loaded at `base`.

    `seeds` supplies entry points for images that carry no vector table --
    a CyOS image dumped out of RAM, for instance, whose entry points come
    from the pointer table at the head of the flash.
    """
    ops = {}
    reached = set()
    entries = set()
    unresolved = defaultdict(list)   # reason -> [addr]
    calls = set()

    work = []
    if seeds:
        for v in seeds:
            if 0 <= v - base < len(d):
                entries.add(v - base)
                work.append(v - base)
    else:
        for idx, v in vectors(d):
            entries.add(v)
            work.append(v)

    while work:
        a = work.pop()
        if a in reached:
            continue
        if a >= len(d) or not in_region(a, regions):
            unresolved["target outside the image"].append(a)
            continue
        i = decode(d, a)
        ops[a] = i
        reached.add(a)

        if i.kind == K_UNK:
            unresolved["undecodable opcode"].append(a)
            continue
        if i.kind in (K_RET, K_RTE):
            continue

        nxt = a + i.length
        if i.kind in (K_JMP, K_JCC, K_CALL):
            if i.target is None:
                # jsr @ERn / jmp @ERn / jmp @@aa:8 -- a computed target
                unresolved["indirect %s" % i.mnem].append(a)
            else:
                if i.kind == K_CALL:
                    entries.add(i.target)
                    calls.add(i.target)
                work.append(i.target)
        if i.kind != K_JMP:              # everything else falls through
            work.append(nxt)

    return ops, reached, entries, calls, unresolved


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    path = argv[0]
    d = load(path)

    base = 0
    if "--base" in argv:
        base = int(argv[argv.index("--base") + 1], 0)
    seeds = None
    if "--prologues" in argv:
        seeds = prologue_seeds(d, base)
    if "--pc" in argv:
        seeds = (seeds or set()) | pc_seeds(argv[argv.index("--pc") + 1])

    ops, reached, entries, calls, unresolved = analyze(d, base, seeds)

    # bytes covered, not instructions -- variable length makes the byte count
    # the meaningful one
    covered = sum(ops[a].length for a in reached)
    tail = len(d)
    while tail > 0 and d[tail - 1] == 0xFF:
        tail -= 1

    print("image           %s%s" % (path, "  base 0x%06X" % base if base else ""))
    if seeds is not None:
        print("seeded with     %d function prologues" % len(seeds))
    print("size            %d bytes (0x%X); %d before the 0xFF padding"
          % (len(d), len(d), tail))
    print("vectors filled  %d" % len(vectors(d)))
    print("entry points    %d (%d of them call targets)" % (len(entries), len(calls)))
    print("instructions    %d" % len(reached))
    print("bytes reached   %d  (%.1f%% of the non-padding image)"
          % (covered, 100.0 * covered / max(1, tail)))
    print()

    total_unres = sum(len(v) for v in unresolved.values())
    print("unresolved      %d" % total_unres)
    for reason in sorted(unresolved, key=lambda k: -len(unresolved[k])):
        sites = unresolved[reason]
        show = " ".join("0x%06X" % s for s in sites[:4])
        print("  %-28s %4d   %s%s"
              % (reason, len(sites), show, " ..." if len(sites) > 4 else ""))

    from collections import Counter
    hist = Counter(ops[a].mnem for a in reached)
    print("\ntop opcodes:")
    for m, c in hist.most_common(12):
        print("  %-20s %5d" % (m, c))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
