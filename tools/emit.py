"""Translate a traced H8S image into C.

Same construction as the Tamagotchi emitter, because it survived contact with a
real ROM: one label per instruction, sequential instructions falling through
with no branch at all, direct transfers compiled to `goto`, and a single dense
dispatch switch for everything computed.

That last part is what makes indirect calls a non-problem. `jsr @ERn` on a
register machine has no static target -- but if every traced instruction has a
label and the dispatch covers all of them, a computed transfer can never land
somewhere without code. The vtable analysis in vtables.py makes that dispatch
*small*; it is not what makes it correct.

Two things differ from the 4-bit case, both from H8S being a real CPU:

  Registers alias.  ER0 is also E0:R0 and R0 is also R0H:R0L, so an 8-bit
  write has to leave the other 24 bits alone. State is held as eight uint32
  and the accessors mask; the compiler folds them away.

  Calls use a real stack.  JSR pushes a 24-bit return address in advanced
  mode. As on the Tamagotchi that stack stays in guest memory rather than
  being mapped onto C's, because the program is free to read it.

    python tools/emit.py <image> <out.c> [--io cyio.bin]
"""
import sys

import analyze
import vtables
from h8s import K_CALL, K_JCC, K_JMP, K_RET, K_RTE, K_TRAP, K_UNK

SIZE_MASK = {"b": 0xFF, "w": 0xFFFF, "l": 0xFFFFFFFF}


# --- operand rendering ----------------------------------------------------

def rd(op):
    """C expression reading a structured operand."""
    kind, size = op[0], op[1]
    if kind == "r":
        return reg_read(size, op[2])
    if kind == "i":
        return "0x%XU" % (op[2] & SIZE_MASK[size])
    return "MR%s(%s)" % (size.upper(), ea(op))


def wr(op, value):
    """C statement writing `value` into a structured operand."""
    kind, size = op[0], op[1]
    if kind == "r":
        return reg_write(size, op[2], value)
    return "MW%s(%s, %s);" % (size.upper(), ea(op), value)


def reg_read(size, n):
    if size == "l":
        return "E[%d]" % (n & 7)
    if size == "w":
        return ("(E[%d] & 0xFFFF)" % n) if n < 8 else ("(E[%d] >> 16 & 0xFFFF)" % (n & 7))
    # 8-bit: 0-7 are the high byte of the low word, 8-15 the low byte
    return ("(E[%d] >> 8 & 0xFF)" % n) if n < 8 else ("(E[%d] & 0xFF)" % (n & 7))


def reg_write(size, n, v):
    if size == "l":
        return "E[%d] = (%s);" % (n & 7, v)
    if size == "w":
        if n < 8:
            return "E[%d] = (E[%d] & 0xFFFF0000U) | ((%s) & 0xFFFF);" % (n, n, v)
        return "E[%d] = (E[%d] & 0x0000FFFFU) | (((%s) & 0xFFFF) << 16);" % (
            n & 7, n & 7, v)
    if n < 8:
        return "E[%d] = (E[%d] & 0xFFFF00FFU) | (((%s) & 0xFF) << 8);" % (n, n, v)
    return "E[%d] = (E[%d] & 0xFFFFFF00U) | ((%s) & 0xFF);" % (n & 7, n & 7, v)


def ea(op):
    kind = op[0]
    if kind == "ind":
        return "E[%d]" % op[2]
    if kind == "abs":
        return "0x%06XU" % op[2]
    if kind == "dsp":
        return "(E[%d] + %d)" % (op[2], op[3])
    if kind in ("pi", "pd"):
        return "E[%d]" % op[2]
    raise AssertionError(kind)


def step_bytes(size):
    return {"b": 1, "w": 2, "l": 4}[size]


def indirect_target(i):
    """C expression for where an indirect JMP/JSR goes.

    Read out of the raw bytes, not parsed back from the display string --
    `jmp @@0x12` and `jsr @er2` do not have the register in the same place,
    and picking it out of text is how you get 'x' where a number should be.

      59 n0 / 5D n0   through ER n
      5B aa / 5F aa   through the longword at @aa:8, a vector slot
    """
    op = i.raw[0]
    if op in (0x59, 0x5D):
        return "E[%d]" % ((i.raw[1] >> 4) & 7)
    if op in (0x5B, 0x5F):
        return "MRL(0x%06XU)" % i.raw[1]
    raise AssertionError("not an indirect transfer: %02X" % op)


# --- instruction bodies ---------------------------------------------------

def body(i):
    """C statements for one instruction, or None if not yet supported."""
    m = i.mnem
    base = m.split(".")[0]
    size = m.split(".")[1] if "." in m else None
    out = []

    # STM/LDM carry their register range in the encoding rather than in sd.
    # `01 n0 6D Fm` stores ERm..ERm+n; `01 n0 6D 7m` loads them back and names
    # the *last* register, because it restores in reverse.
    if base in ("stm", "ldm"):
        count = (i.raw[1] >> 4) + 1
        reg = i.raw[3] & 7
        if i.raw[3] & 0x80:
            first = reg
            out = ["E[7] -= %d;" % (4 * count)]
            out += ["MWL(E[7] + %d, E[%d]);" % (4 * k, first + k)
                    for k in range(count)]
        else:
            first = reg - count + 1
            out = ["E[%d] = MRL(E[7] + %d);" % (first + k, 4 * k)
                   for k in range(count)]
            out.append("E[7] += %d;" % (4 * count))
        return out

    if base == "nop":
        return []

    # The condition-code register as a value. ORC sets bits, ANDC clears the
    # ones not named, XORC toggles, LDC replaces outright.
    if base in ("orc", "andc", "xorc", "ldc") and i.sd:
        dst, src = i.sd
        if dst[0] == "ccr" and src[0] == "i":
            v = src[2] & 0xFF
            expr = {"orc": "CY_CCR_GET(c) | 0x%02XU" % v,
                    "andc": "CY_CCR_GET(c) & 0x%02XU" % v,
                    "xorc": "CY_CCR_GET(c) ^ 0x%02XU" % v,
                    "ldc": "0x%02XU" % v}[base]
            return ["CY_CCR_SET(c, %s);" % expr]
        return None

    # Add/subtract with carry, and the rotates that go through it.
    if base in ("addx", "subx") and i.sd:
        dst, src = i.sd
        op = "+" if base == "addx" else "-"
        return ["t = %s %s %s %s c->cf;" % (rd(dst), op, rd(src), op),
                "SETFLAGS_%s(%s, (%s) %s c->cf, t, %s);"
                % ("ADD" if base == "addx" else "SUB",
                   rd(dst), rd(src), op, size or "b"),
                wr(dst, "t")]

    if base in ("rotxl", "rotxr", "rotl", "rotr") and i.sd:
        dst, _ = i.sd
        bits = {"b": 8, "w": 16, "l": 32}[size]
        v = rd(dst)
        if base == "rotxl":
            out = ["t = (%s << 1) | c->cf;" % v,
                   "c->cf = (%s >> %d) & 1;" % (v, bits - 1)]
        elif base == "rotxr":
            out = ["t = (%s >> 1) | ((uint32_t)c->cf << %d);" % (v, bits - 1),
                   "c->cf = %s & 1;" % v]
        elif base == "rotl":
            out = ["t = (%s << 1) | ((%s >> %d) & 1);" % (v, v, bits - 1),
                   "c->cf = (%s >> %d) & 1;" % (v, bits - 1)]
        else:
            out = ["t = (%s >> 1) | ((%s & 1) << %d);" % (v, v, bits - 1),
                   "c->cf = %s & 1;" % v]
        return out + [wr(dst, "t"), "SETNZ(t, %s);" % size]

    # Bit operations. BTST only sets Z; the others read-modify-write and leave
    # the flags alone. The bit number is either a 3-bit immediate or the low
    # three bits of a register.
    if base in ("bset", "bclr", "bnot", "btst"):
        if i.sd is None:
            return None
        dst, src = i.sd
        n = ("%s" % rd(src)) if src[0] == "i" else ("(%s & 7)" % rd(src))
        if base == "btst":
            return ["c->zf = ((%s >> %s) & 1) == 0;" % (rd(dst), n)]
        op = {"bset": "|  (1u << %s)", "bclr": "& ~(1u << %s)",
              "bnot": "^  (1u << %s)"}[base] % n
        return ["t = %s %s;" % (rd(dst), op), wr(dst, "t")]

    if i.sd is None:
        return None
    dst, src = i.sd

    # pre-decrement happens before the access, post-increment after
    pre = []
    post = []
    for op in (dst, src):
        if op and op[0] == "pd":
            pre.append("E[%d] -= %d;" % (op[2], step_bytes(op[1])))
        elif op and op[0] == "pi":
            post.append("E[%d] += %d;" % (op[2], step_bytes(op[1])))

    if base == "mov":
        out = ["t = %s;" % rd(src), wr(dst, "t"), "SETNZ(t, %s);" % size]
    elif base in ("add", "sub", "cmp", "and", "or", "xor"):
        op = {"add": "+", "sub": "-", "cmp": "-",
              "and": "&", "or": "|", "xor": "^"}[base]
        out = ["t = %s %s %s;" % (rd(dst), op, rd(src))]
        if base in ("add", "sub", "cmp"):
            out.append("SETFLAGS_%s(%s, %s, t, %s);"
                       % (base.upper(), rd(dst), rd(src), size))
        else:
            out.append("SETNZ(t, %s);" % size)
        if base != "cmp":
            out.append(wr(dst, "t"))
    elif base in ("adds", "subs"):
        out = ["E[%d] %s= %s;" % (dst[2], "+" if base == "adds" else "-",
                                  rd(src))]
    elif base in ("inc", "dec"):
        out = ["t = %s %s %s;" % (rd(dst), "+" if base == "inc" else "-",
                                  rd(src)),
               wr(dst, "t"), "SETNZ(t, %s);" % size]
    elif base == "not":
        out = ["t = ~%s;" % rd(dst), wr(dst, "t"), "SETNZ(t, %s);" % size]
    elif base == "neg":
        out = ["t = -(int32_t)%s;" % rd(dst), wr(dst, "t"),
               "SETNZ(t, %s);" % size]
    elif base in ("extu", "exts"):
        half = "b" if size == "w" else "w"
        conv = ("(uint32_t)" if base == "extu"
                else ("(int32_t)(int8_t)" if size == "w" else "(int32_t)(int16_t)"))
        out = ["t = %s%s;" % (conv, reg_read(half, dst[2])),
               wr(dst, "t"), "SETNZ(t, %s);" % size]
    elif base in ("shll", "shal"):
        out = ["t = %s << %s;" % (rd(dst), rd(src)), wr(dst, "t"),
               "SETNZ(t, %s);" % size]
    elif base == "shlr":
        out = ["t = %s >> %s;" % (rd(dst), rd(src)), wr(dst, "t"),
               "SETNZ(t, %s);" % size]
    elif base == "shar":
        out = ["t = (uint32_t)(SEXT_%s(%s) >> %s);"
               % (size.upper(), rd(dst), rd(src)), wr(dst, "t"),
               "SETNZ(t, %s);" % size]
    elif base == "push":
        out = ["E[7] -= 4;", "MWL(E[7], %s);" % rd(src)]
        pre = post = []
    elif base == "pop":
        out = ["t = MRL(E[7]);", wr(dst, "t"), "E[7] += 4;"]
        pre = post = []
    else:
        return None

    return pre + out + post

# How many instructions to put in one C function.
#
# One function holding all 39,841 was correct and would not finish compiling --
# clang goes superlinear in the number of labels, and what took 13 seconds for
# the Tamagotchi's 6,144 had not returned after ten minutes here. Chunking is
# purely a concession to the compiler.
#
# The split is at *entry points*, never inside a function, so fall-through and
# intra-function `goto` -- where all the speed is -- are untouched. Only
# transfers that leave a chunk pay for it, and a call is already doing a stack
# push, so the extra dispatch is proportionally small.
CHUNK = 3000

HEADER = '''/* Generated by tools/emit.py -- do not edit.
 *
 * A traced Cybiko image as C: one label per instruction, sequential
 * instructions falling through, direct transfers as `goto`, and a dispatch for
 * everything computed.
 *
 * It is split into chunk functions only so that it compiles in finite time.
 * The split is at function boundaries, so no intra-function control flow
 * crosses one.
 */
#include "cybikorecomp/h8s.h"

#define MRB(a)     cy_read8(c, (a))
#define MRW(a)     cy_read16(c, (a))
#define MRL(a)     cy_read32(c, (a))
#define MWB(a, v)  cy_write8(c, (a), (uint8_t)(v))
#define MWW(a, v)  cy_write16(c, (a), (uint16_t)(v))
#define MWL(a, v)  cy_write32(c, (a), (uint32_t)(v))

#define SEXT_B(v)  ((int32_t)(int8_t)(v))
#define SEXT_W(v)  ((int32_t)(int16_t)(v))
#define SEXT_L(v)  ((int32_t)(v))

static int cy_chunk_of(uint32_t pc);

'''


def chunk_up(addrs, entries):
    """Split into runs of about CHUNK instructions, breaking only at entries."""
    out, cur = [], []
    for a in addrs:
        if cur and len(cur) >= CHUNK and a in entries:
            out.append(cur)
            cur = []
        cur.append(a)
    if cur:
        out.append(cur)
    return out


def emit_chunk(k, ch, ops, where, w):
    """One chunk function: an entry switch, then labels and bodies."""
    covered = skipped = stranded = 0
    mine = set(ch)

    def go(target):
        """Jump inside this chunk, or hand control back to the run loop."""
        if target in mine:
            return "goto L_%06X;" % target
        return "c->pc = 0x%06XU; return;" % target

    w("static void cy_chunk%d(cy_t *c)\n{\n" % k)
    w("    uint32_t *E = c->e;\n    uint32_t t;\n    (void)t; (void)E;\n")
    w("    switch (c->pc) {\n")
    for a in ch:
        w("    case 0x%06XU: goto L_%06X;\n" % (a, a))
    w("    default: return;\n    }\n\n")

    for idx, a in enumerate(ch):
        i = ops[a]
        nxt = a + i.length
        w("L_%06X: /* %-12s %s */\n" % (a, i.raw.hex(), i))

        if i.kind in (K_JMP, K_JCC) and i.target is not None:
            if i.target not in where:
                stranded += 1
            cond = {"beq": "c->zf", "bne": "!c->zf", "bcs": "c->cf",
                    "bcc": "!c->cf", "bmi": "c->nf", "bpl": "!c->nf",
                    "bvs": "c->vf", "bvc": "!c->vf"}.get(i.mnem.split(".")[0])
            if i.kind == K_JMP:
                w("    %s\n" % go(i.target))
            elif cond:
                w("    if (%s) { %s }\n" % (cond, go(i.target)))
            else:
                w("    if (cy_cond(c, %d)) { %s }\n"
                  % (i.raw[0] & 0xF if i.raw[0] >> 4 == 4 else i.raw[1] >> 4,
                     go(i.target)))
            covered += 1
            continue

        if i.kind == K_CALL:
            w("    E[7] -= 4; MWL(E[7], 0x%06XU);\n" % nxt)
            if i.target is not None:
                if i.target not in where:
                    stranded += 1
                w("    %s\n" % go(i.target))
            else:
                w("    c->pc = %s & 0xFFFFFF; return;\n" % indirect_target(i))
            covered += 1
            continue

        if i.kind in (K_RET, K_RTE):
            w("    c->pc = MRL(E[7]) & 0xFFFFFF; E[7] += 4;\n    return;\n")
            covered += 1
            continue

        if i.kind == K_JMP:                       # indirect
            w("    c->pc = %s & 0xFFFFFF; return;\n" % indirect_target(i))
            covered += 1
            continue

        if i.kind in (K_TRAP, K_UNK):
            w("    c->trapped = 1; c->trap_pc = 0x%06XU; return;\n" % a)
            skipped += 1
            continue

        stmts = body(i)
        if stmts is None:
            w("    UNIMPLEMENTED(0x%06XU);   /* %s */\n" % (a, i.mnem))
            skipped += 1
        else:
            for st in stmts:
                w("    " + st + "\n")
            covered += 1

        # Fall through only if the next instruction really is the next label.
        last = idx + 1 == len(ch)
        if last or ch[idx + 1] != nxt:
            w("    c->pc = 0x%06XU; return;\n" % nxt)

    w("}\n\n")
    return covered, skipped, stranded


def emit(d, ops, reached, entries, out):
    w = out.write
    w(HEADER)
    addrs = sorted(reached)
    chunks = chunk_up(addrs, entries)
    where = {a: k for k, ch in enumerate(chunks) for a in ch}
    covered = skipped = stranded = 0

    for k in range(len(chunks)):
        w("static void cy_chunk%d(cy_t *c);\n" % k)

    w("\nvoid cy_run(cy_t *c, uint64_t budget)\n{\n")
    w("    while (!c->trapped) {\n")
    w("        if (c->cycles++ >= budget)\n            return;\n")
    w("        switch (cy_chunk_of(c->pc)) {\n")
    for k in range(len(chunks)):
        w("        case %d: cy_chunk%d(c); break;\n" % (k, k))
    w("        default: c->trapped = 1; c->trap_pc = c->pc; return;\n")
    w("        }\n    }\n}\n\n")

    for k, ch in enumerate(chunks):
        c2, s2, st2 = emit_chunk(k, ch, ops, where, w)
        covered += c2
        skipped += s2
        stranded += st2

    w("/* Which chunk owns an address. */\n")
    w("static int cy_chunk_of(uint32_t pc)\n{\n    switch (pc) {\n")
    for a in addrs:
        w("    case 0x%06XU: return %d;\n" % (a, where[a]))
    w("    default: return -1;\n    }\n}\n")
    return covered, skipped, stranded, len(chunks)


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    d = analyze.load(argv[0])
    io = None
    if "--io" in argv:
        io = open(argv[argv.index("--io") + 1], "rb").read()

    (ops, reached, entries, calls, unresolved), runs = vtables.resolve(d, io)
    with open(argv[1], "w", encoding="utf-8") as f:
        covered, skipped, stranded, nchunks = emit(d, ops, reached, entries, f)

    total = covered + skipped
    print("%s" % argv[1])
    print("  instructions   %d" % total)
    print("  emitted        %d  (%.1f%%)" % (covered, 100.0 * covered / total))
    print("  unimplemented  %d  (%.1f%%)" % (skipped, 100.0 * skipped / total))
    print("  stranded jumps %d  (target never traced; traps instead)" % stranded)
    print("  chunks         %d  (split at entry points, for the compiler)"
          % nchunks)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
