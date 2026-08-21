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

    python tools/analyze.py <image.bin> [load_address]
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


def analyze(d, base=0):
    ops = {}
    reached = set()
    entries = set()
    unresolved = defaultdict(list)   # reason -> [addr]
    calls = set()

    work = []
    for idx, v in vectors(d):
        entries.add(v)
        work.append(v)

    while work:
        a = work.pop()
        if a in reached:
            continue
        if a >= len(d):
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

    ops, reached, entries, calls, unresolved = analyze(d)

    # bytes covered, not instructions -- variable length makes the byte count
    # the meaningful one
    covered = sum(ops[a].length for a in reached)
    tail = len(d)
    while tail > 0 and d[tail - 1] == 0xFF:
        tail -= 1

    print("image           %s" % path)
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
