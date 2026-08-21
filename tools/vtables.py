"""Find the tables the Cybiko's indirect calls dispatch through.

178 of the ~227 indirect calls in a combined Cybiko image load their target
with `mov.l @(d:16,ERm), ERn` -- a field of a struct the callee was handed.
That is C++ virtual dispatch, and it means the targets live in vtables.

A vtable is easy to recognise once some code is known: a run of consecutive
big-endian u32 that are *all* addresses of already-traced instructions. Three
in a row is enough to be well past coincidence, and in this image they cluster
in one contiguous region, which is what a linker does with them.

Finding them feeds a fixpoint. New vtable targets reveal code, that code makes
more pointers recognisable, and so on -- it settles in two rounds.

**The trace must be bounded to mapped regions.** An unbounded version of this
reported 1,073,877 instructions, more than the image holds, because a bogus
pointer sent it into the 0xFF fill -- and 0xFF decodes as a perfectly good
`mov.b #imm, r7l`, so it never stops. See analyze.CYBIKO_REGIONS.

    python tools/vtables.py cybiko.img [cyio.bin]
"""
import struct
import sys

import analyze

RAM_LO, RAM_HI = 0x200000, 0x240000
MIN_ENTRIES = 3

# The boot ROM's interrupt handler table, in on-chip RAM. Eleven slots, each
# reached by its own 26-byte trampoline in the boot ROM (save, load handler,
# jsr, restore, rte). Those trampolines are 43 of the indirect call sites, so
# reading this table turns all of them into one understood mechanism.
IO_BASE, IRQ_TABLE, IRQ_COUNT = 0xFFE000, 0xFFEC90, 11


def find(d, code):
    """Runs of >= MIN_ENTRIES consecutive pointers into `code`."""
    out = []
    a = RAM_LO
    while a < RAM_HI - 4:
        n = 0
        while a + 4 * n + 4 <= RAM_HI:
            if struct.unpack_from(">I", d, a + 4 * n)[0] in code:
                n += 1
            else:
                break
        if n >= MIN_ENTRIES:
            out.append((a, n))
            a += 4 * n
        else:
            a += 2
    return out


def targets(d, runs):
    return {struct.unpack_from(">I", d, a + 4 * i)[0]
            for a, n in runs for i in range(n)}


def irq_handlers(io):
    return {struct.unpack_from(">I", io, IRQ_TABLE - IO_BASE + 4 * i)[0]
            for i in range(IRQ_COUNT)}


def resolve(d, io=None, rounds=8):
    """Trace to a fixpoint, discovering vtables as more code becomes known."""
    seeds = set(v for _, v in analyze.vectors(d))
    seeds |= analyze.prologue_seeds(d, 0, 0x0000, 0x8000)
    seeds |= analyze.prologue_seeds(d, 0, RAM_LO, RAM_HI)
    if io:
        seeds |= irq_handlers(io)

    prev, runs, result = -1, [], None
    for _ in range(rounds):
        result = analyze.analyze(d, 0, seeds, analyze.CYBIKO_REGIONS)
        runs = find(d, set(result[1]))
        tg = targets(d, runs)
        if len(seeds | tg) == prev:
            break
        prev = len(seeds | tg)
        seeds |= tg
    return result, runs


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    d = analyze.load(argv[0])
    io = open(argv[1], "rb").read() if len(argv) > 1 else None

    (ops, reached, entries, calls, unresolved), runs = resolve(d, io)
    ptrs = sum(n for _, n in runs)

    print("vtables        %d, holding %d pointers (%d distinct targets)"
          % (len(runs), ptrs, len(targets(d, runs))))
    print("instructions   %d" % len(reached))
    print("bytes reached  %d" % sum(ops[a].length for a in reached))
    print("entry points   %d (%d of them call targets)" % (len(entries), len(calls)))
    print("unresolved     %d" % sum(len(v) for v in unresolved.values()))
    for k in sorted(unresolved, key=lambda k: -len(unresolved[k])):
        print("  %-26s %d" % (k, len(unresolved[k])))

    print("\nlargest tables:")
    for a, n in sorted(runs, key=lambda r: -r[1])[:8]:
        head = [struct.unpack_from(">I", d, a + 4 * i)[0] for i in range(min(n, 4))]
        print("  %06X  %3d entries   %s%s"
              % (a, n, " ".join("%06X" % t for t in head), " ..." if n > 4 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
