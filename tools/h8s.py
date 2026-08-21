"""H8S/2000 instruction decoder — the core inside the Cybiko's H8S/2246.

Big-endian, variable length: 2, 4, 6, 8 or 10 bytes. That variability is the
whole difficulty. On a fixed-width machine a wrong opcode costs you one
instruction; here it costs you the rest of the stream, because the next decode
starts at the wrong byte. So `length` is the field to get right first, and the
one the tests pin hardest.

Registers. Eight 32-bit ER0-ER7 with ER7 as the stack pointer. Each is also
addressable as two 16-bit halves (E0/R0) and the low half as two 8-bit
(R0H/R0L), which is why the same 3 or 4 operand bits mean different things
depending on the operation size:

    rrr   in an 8-bit op   ->  R0H..R7L, encoded 0-7 = xxH, 8-15 = xxL
    rrr   in a 16-bit op   ->  R0..R7 (low half), 8-15 = E0..E7 (high half)
    errr  in a 32-bit op   ->  ER0..ER7, the top bit must be 0

The CPU runs in *advanced mode* on this part: 24-bit addresses, and a stack
frame that pushes 4 bytes for a return address rather than 2.
"""

SZ_B, SZ_W, SZ_L = "b", "w", "l"


def r8(n):
    return "r%d%s" % (n & 7, "h" if n < 8 else "l")


def r16(n):
    return ("r%d" if n < 8 else "e%d") % (n & 7)


def r32(n):
    return "er%d" % (n & 7)


CC = ("bra", "brn", "bhi", "bls", "bcc", "bcs", "bne", "beq",
      "bvc", "bvs", "bpl", "bmi", "bge", "blt", "bgt", "ble")

# Control-flow classes the analyzer cares about. Everything else is "seq".
K_SEQ, K_JMP, K_JCC, K_CALL, K_RET, K_RTE, K_TRAP, K_UNK = (
    "seq", "jmp", "jcc", "call", "ret", "rte", "trap", "unk")


# Structured operands, for the emitter. `ops` stays a tuple of strings for
# display; `sd` carries the same thing in a form codegen can use:
#
#   ("r",  size, n)          register n at that size ('b'/'w'/'l')
#   ("i",  size, value)      immediate
#   ("ind", size, n)         @ERn
#   ("dsp", size, n, d)      @(d, ERn)
#   ("abs", size, a)         @aa
#   ("pi",  size, n)         @ERn+      (post-increment)
#   ("pd",  size, n)         @-ERn      (pre-decrement)
#
# An instruction with sd == None is one the decoder can size and classify but
# not yet describe; the emitter counts those rather than guessing.
def R(size, n):
    return ("r", size, n)


def I(size, v):
    return ("i", size, v)


class Insn:
    __slots__ = ("addr", "length", "mnem", "ops", "kind", "target", "raw", "sd")

    def __init__(self, addr, length, mnem, ops=(), kind=K_SEQ, target=None,
                 raw=b"", sd=None):
        self.addr, self.length = addr, length
        self.mnem, self.ops, self.kind = mnem, ops, kind
        self.target = target          # resolved absolute target, when static
        self.raw = raw
        self.sd = sd                  # (dst, src) structured, or None

    def __str__(self):
        return ("%s %s" % (self.mnem, ", ".join(self.ops))).strip()

    def __repr__(self):
        return "<%06X %s %s>" % (self.addr, self.raw.hex(), self)


def _s8(v):
    return v - 256 if v & 0x80 else v


def _s16(v):
    return v - 0x10000 if v & 0x8000 else v


def u16(d, i):
    return (d[i] << 8) | d[i + 1]


def u24(d, i):
    return (d[i] << 16) | (d[i + 1] << 8) | d[i + 2]


def u32(d, i):
    return (d[i] << 24) | (d[i + 1] << 16) | (d[i + 2] << 8) | d[i + 3]


# --- the 0x01 prefix group ------------------------------------------------
# 0x01 introduces most of the 32-bit and control-register operations. The
# second byte selects which, and several of them then reuse an ordinary
# two-byte opcode as their body.

def _decode_01(d, a, n):
    b1 = d[a + 1]
    # STM.L / LDM.L -- push or pop a run of 2 to 4 consecutive ER registers.
    # `01 n0 6D Fm` stores ERm..ERm+n; `01 n0 6D 7m` loads them back, and
    # encodes the *last* register because it restores in reverse. These are
    # function prologues and epilogues, which is why they turn up in exactly
    # matched pairs.
    if n >= 4 and (b1 & 0x8F) == 0 and d[a + 2] == 0x6D:
        cnt = (b1 >> 4) + 1
        if 2 <= cnt <= 4:
            b3 = d[a + 3]
            reg = b3 & 7
            if b3 & 0x80:
                lst = "er%d-er%d" % (reg, reg + cnt - 1)
                return Insn(a, 4, "stm.l", ("(%s)" % lst, "@-sp"),
                            raw=d[a:a + 4])
            lst = "er%d-er%d" % (reg - cnt + 1, reg)
            return Insn(a, 4, "ldm.l", ("@sp+", "(%s)" % lst), raw=d[a:a + 4])
    if b1 == 0x00 and n >= 4:
        b2 = d[a + 2]
        if 0x68 <= b2 <= 0x6F:
            r = _mov_ea(d, a, b2 & 0xF, "l", 2)
            if r:
                # @ERm+/@-ERm on ER7 is what push and pop actually are
                if (b2 & 0x0E) == 0x0C:
                    ea = r.sd[0] if r.sd[0][0] in ("pd", "pi") else r.sd[1]
                    if ea[2] == 7:
                        push = ea[0] == "pd"
                        reg = (r.sd[1] if push else r.sd[0])[2]
                        return Insn(a, r.length, "push.l" if push else "pop.l",
                                    (r32(reg),), raw=r.raw,
                                    sd=(r.sd[0], r.sd[1]))
                return r
        if b2 == 0x78 and n >= 10:
            return Insn(a, 10, "mov.l", ("@(d:24,ERs)",), raw=d[a:a + 10])
        return Insn(a, 4, "mov.l", (), raw=d[a:a + 4])
    if b1 == 0x40 and n >= 4:
        return Insn(a, 4, "ldc/stc", (), raw=d[a:a + 4])
    if b1 == 0x41 and n >= 4:
        return Insn(a, 4, "ldc/stc", (), raw=d[a:a + 4])
    if b1 == 0x80:
        return Insn(a, 2, "sleep", raw=d[a:a + 2])
    if b1 == 0xC0 and n >= 4:
        return Insn(a, 4, "mulxs", (), raw=d[a:a + 4])
    if b1 == 0xD0 and n >= 4:
        return Insn(a, 4, "divxs", (), raw=d[a:a + 4])
    if b1 == 0xF0 and n >= 4:
        return Insn(a, 4, "tas", (), raw=d[a:a + 4])
    return None



# --- the size-and-count groups -------------------------------------------
# 0x0B/0x1B (ADDS/INC, SUBS/DEC) and 0x10-0x13/0x17 all share a shape: the
# second byte's high nibble picks both the operation variant and the operand
# size, and the low nibble is the register. The tables below are read straight
# off the H8S/2000 instruction list; the awkward part is that the same nibble
# means a different size in each group, so they cannot be merged.

# high nibble -> (mnemonic, size, immediate) for 0x0B / 0x1B
_STEP = {
    0x0: ("s", "l", 1), 0x8: ("s", "l", 2), 0x9: ("s", "l", 4),
    0x5: ("x", "w", 1), 0xD: ("x", "w", 2),
    0x7: ("x", "l", 1), 0xF: ("x", "l", 2),
}

# high nibble -> (mnemonic, size) for 0x17
_UNARY17 = {
    0x0: ("not", "b"), 0x1: ("not", "w"), 0x3: ("not", "l"),
    0x5: ("extu", "w"), 0x7: ("extu", "l"),
    0x8: ("neg", "b"), 0x9: ("neg", "w"), 0xB: ("neg", "l"),
    0xD: ("exts", "w"), 0xF: ("exts", "l"),
}

# high nibble -> (which of the pair, size, shift-by) for 0x10-0x13
_SHIFT = {
    0x0: (0, "b", 1), 0x1: (0, "w", 1), 0x3: (0, "l", 1),
    0x4: (0, "b", 2), 0x5: (0, "w", 2), 0x7: (0, "l", 2),
    0x8: (1, "b", 1), 0x9: (1, "w", 1), 0xB: (1, "l", 1),
    0xC: (1, "b", 2), 0xD: (1, "w", 2), 0xF: (1, "l", 2),
}

_SHIFT_NAMES = {0x10: ("shll", "shal"), 0x11: ("shlr", "shar"),
                0x12: ("rotxl", "rotl"), 0x13: ("rotxr", "rotr")}


def _reg_name(size, n):
    return {"b": r8, "w": r16, "l": r32}[size](n)


def _decode_step(d, a, b0, b1):
    """0x0B ADDS/INC and 0x1B SUBS/DEC."""
    ent = _STEP.get(b1 >> 4)
    if ent is None:
        return None
    kind, size, imm = ent
    add = b0 == 0x0B
    if kind == "s":
        mnem = "adds" if add else "subs"
    else:
        mnem = ("inc" if add else "dec") + "." + size
    n = b1 & 0xF
    reg = _reg_name(size, n)
    ops = ("#%d" % imm, reg)
    return Insn(a, 2, mnem, ops, raw=d[a:a + 2],
                sd=(R(size, n), I(size, imm)))


def _decode_unary17(d, a, b1):
    ent = _UNARY17.get(b1 >> 4)
    if ent is None:
        return None
    mnem, size = ent
    n = b1 & 0xF
    return Insn(a, 2, "%s.%s" % (mnem, size), (_reg_name(size, n),),
                raw=d[a:a + 2], sd=(R(size, n), None))


def _decode_shift(d, a, b0, b1):
    ent = _SHIFT.get(b1 >> 4)
    if ent is None:
        return None
    which, size, by = ent
    mnem = _SHIFT_NAMES[b0][which]
    n = b1 & 0xF
    ops = ((("#%d" % by,) if by != 1 else ()) + (_reg_name(size, n),))
    return Insn(a, 2, "%s.%s" % (mnem, size), ops, raw=d[a:a + 2],
                sd=(R(size, n), I(size, by)))



# --- the MOV effective-address family ------------------------------------
# 0x68-0x6F is one family in four addressing modes, and the same four repeat
# for every operand size:
#
#   68/69   @ERm            2 bytes
#   6A/6B   @aa:16 or :24   4 or 6 bytes
#   6C/6D   @ERm+ / @-ERm   2 bytes
#   6E/6F   @(d:16,ERm)     4 bytes
#
# Even opcodes are byte-sized and odd ones word-sized; prefixing the whole
# thing with `01 00` makes it long. Bit 7 of the second byte is the direction:
# set means register -> memory.
#
# The 6A/6B form is the exception -- it has no register field to hang the
# direction bit on, so the second byte's high nibble encodes both:
#   0 = load @aa:16   2 = load @aa:24   8 = store @aa:16   A = store @aa:24

def _mov_ea(d, a, op, size, off):
    """Decode a 0x68-0x6F MOV. `off` is where the opcode byte sits (0, or 2
    when it follows an `01 00` prefix). Returns an Insn or None."""
    n = len(d) - a
    b1 = d[a + off + 1]
    form = op & 0x0E
    need = {0x08: 2, 0x0C: 2, 0x0E: 4}.get(form, 4)

    if form == 0x0A:                                   # @aa
        hi = b1 >> 4
        wide = hi in (0x2, 0xA)
        store = hi in (0x8, 0xA)
        need = 6 if wide else 4
        if n < off + need:
            return None
        reg = b1 & 0xF
        # @aa:16 is *sign-extended* to 24 bits, which is how a 16-bit
        # displacement reaches on-chip RAM and I/O at the top of the map:
        # 0xECB4 means 0xFFECB4, not 0x00ECB4. @aa:24 is already full width.
        if wide:
            addr = u24(d, a + off + 3)
        else:
            addr = u16(d, a + off + 2)
            if addr & 0x8000:
                addr |= 0xFF0000
        ea = ("abs", size, addr & 0xFFFFFF)
        text = "@0x%06X" % (addr & 0xFFFFFF)
    else:
        if n < off + need:
            return None
        store = bool(b1 & 0x80)
        m = (b1 >> 4) & 7
        reg = b1 & 0xF
        if form == 0x08:
            ea, text = ("ind", size, m), "@%s" % r32(m)
        elif form == 0x0C:
            if store:
                ea, text = ("pd", size, m), "@-%s" % r32(m)
            else:
                ea, text = ("pi", size, m), "@%s+" % r32(m)
        else:                                          # @(d:16,ERm)
            disp = _s16(u16(d, a + off + 2))
            ea, text = ("dsp", size, m, disp), "@(0x%X,%s)" % (disp & 0xFFFF, r32(m))

    rn = {"b": r8, "w": r16, "l": r32}[size](reg)
    rop = ("r", size, reg & 7 if size == "l" else reg)
    mnem = "mov." + size
    total = off + need
    if store:
        return Insn(a, total, mnem, (rn, text), raw=d[a:a + total], sd=(ea, rop))
    return Insn(a, total, mnem, (text, rn), raw=d[a:a + total], sd=(rop, ea))


# --- the 0x79/0x7A immediate groups ---------------------------------------
_IMM_OPS = {0x0: "mov", 0x1: "add", 0x2: "cmp", 0x3: "sub",
            0x4: "or", 0x5: "xor", 0x6: "and"}


def _decode_79(d, a, n):
    if n < 4:
        return None
    sel = d[a + 1] >> 4
    reg = d[a + 1] & 0xF
    op = _IMM_OPS.get(sel)
    if op is None:
        return None
    return Insn(a, 4, op + ".w", ("#0x%04X" % u16(d, a + 2), r16(reg)),
                raw=d[a:a + 4], sd=(R("w", reg), I("w", u16(d, a + 2))))


def _decode_7a(d, a, n):
    if n < 6:
        return None
    sel = d[a + 1] >> 4
    reg = d[a + 1] & 0xF
    op = _IMM_OPS.get(sel)
    if op is None:
        return None
    return Insn(a, 6, op + ".l", ("#0x%08X" % u32(d, a + 2), r32(reg)),
                raw=d[a:a + 6], sd=(R("l", reg & 7), I("l", u32(d, a + 2))))


# --- 0x6x memory group ----------------------------------------------------

def _decode_6(d, a, n):
    b0, b1 = d[a], d[a + 1]
    lo = b0 & 0xF

    if lo in (0x0, 0x1, 0x2, 0x3):        # BSET/BNOT/BCLR/BTST Rm, Rd
        m = ("bset", "bnot", "bclr", "btst")[lo]
        return Insn(a, 2, m, (r8(b1 >> 4), r8(b1 & 0xF)), raw=d[a:a + 2],
                    sd=(R("b", b1 & 0xF), R("b", b1 >> 4)))
    if lo in (0x4, 0x5, 0x6):             # OR/XOR/AND .w Rs,Rd
        m = ("or", "xor", "and")[lo - 4]
        return Insn(a, 2, m + ".w", (r16(b1 >> 4), r16(b1 & 0xF)),
                    raw=d[a:a + 2],
                    sd=(R("w", b1 & 0xF), R("w", b1 >> 4)))
    if lo == 0x7:
        return Insn(a, 2, "bst/bist", (), raw=d[a:a + 2])
    if lo >= 0x8:
        return _mov_ea(d, a, lo, "b" if (lo & 1) == 0 else "w", 0)
    return None


# --- 0x7Cx-0x7Fx bit-operation-on-memory group ----------------------------

def _decode_7c(d, a, n):
    """7C/7D/7E/7F: a bit op whose operand is @ERd or @aa, always 4 bytes."""
    if n < 4:
        return None
    return Insn(a, 4, "bit-op", (), raw=d[a:a + 4])


def decode(d, a):
    """Decode one instruction at offset `a` of bytes `d`.

    Returns an Insn, or an Insn of kind "unk" with length 2 so a caller
    sweeping linearly can keep going and report coverage rather than stop.
    """
    n = len(d) - a
    if n < 2:
        return Insn(a, max(1, n), "(truncated)", kind=K_UNK, raw=d[a:])
    b0, b1 = d[a], d[a + 1]
    hi, lo = b0 >> 4, b0 & 0xF

    # --- 0x0x ---
    if b0 == 0x00:
        return Insn(a, 2, "nop", raw=d[a:a + 2])
    if b0 == 0x01:
        r = _decode_01(d, a, n)
        if r:
            return r
    if b0 in (0x02, 0x03):
        return Insn(a, 2, "stc" if b0 == 0x02 else "ldc", (), raw=d[a:a + 2])
    if b0 in (0x04, 0x05, 0x06, 0x07):
        m = {0x04: "orc", 0x05: "xorc", 0x06: "andc", 0x07: "ldc"}[b0]
        return Insn(a, 2, m, ("#0x%02X" % b1, "ccr"), raw=d[a:a + 2])
    if b0 == 0x08:
        return Insn(a, 2, "add.b", (r8(b1 >> 4), r8(b1 & 0xF)), raw=d[a:a + 2],
                    sd=(R("b", b1 & 0xF), R("b", b1 >> 4)))
    if b0 == 0x09:
        return Insn(a, 2, "add.w", (r16(b1 >> 4), r16(b1 & 0xF)), raw=d[a:a + 2],
                    sd=(R("w", b1 & 0xF), R("w", b1 >> 4)))
    if b0 == 0x0A:
        if b1 & 0x80:
            return Insn(a, 2, "add.l", (r32(b1 >> 4 & 7), r32(b1 & 7)),
                        raw=d[a:a + 2],
                        sd=(R("l", b1 & 7), R("l", b1 >> 4 & 7)))
        return Insn(a, 2, "inc.b", (r8(b1 & 0xF),), raw=d[a:a + 2],
                    sd=(R("b", b1 & 0xF), I("b", 1)))
    if b0 == 0x0B:
        r = _decode_step(d, a, b0, b1)
        if r:
            return r
    if b0 == 0x0C:
        return Insn(a, 2, "mov.b", (r8(b1 >> 4), r8(b1 & 0xF)), raw=d[a:a + 2],
                    sd=(R("b", b1 & 0xF), R("b", b1 >> 4)))
    if b0 == 0x0D:
        return Insn(a, 2, "mov.w", (r16(b1 >> 4), r16(b1 & 0xF)), raw=d[a:a + 2],
                    sd=(R("w", b1 & 0xF), R("w", b1 >> 4)))
    if b0 == 0x0E:
        return Insn(a, 2, "addx", (), raw=d[a:a + 2])
    if b0 == 0x0F:
        if b1 & 0x80:
            return Insn(a, 2, "mov.l", (r32(b1 >> 4 & 7), r32(b1 & 7)),
                        raw=d[a:a + 2],
                        sd=(R("l", b1 & 7), R("l", b1 >> 4 & 7)))
        return Insn(a, 2, "daa", (r8(b1 & 0xF),), raw=d[a:a + 2])

    # --- 0x1x ---
    if b0 in (0x10, 0x11, 0x12, 0x13):
        r = _decode_shift(d, a, b0, b1)
        if r:
            return r
    if b0 in (0x14, 0x15, 0x16):
        return Insn(a, 2, ("or", "xor", "and")[b0 - 0x14] + ".b",
                    (r8(b1 >> 4), r8(b1 & 0xF)), raw=d[a:a + 2],
                    sd=(R("b", b1 & 0xF), R("b", b1 >> 4)))
    if b0 == 0x17:
        r = _decode_unary17(d, a, b1)
        if r:
            return r
    if b0 == 0x18:
        return Insn(a, 2, "sub.b", (r8(b1 >> 4), r8(b1 & 0xF)), raw=d[a:a + 2],
                    sd=(R("b", b1 & 0xF), R("b", b1 >> 4)))
    if b0 == 0x19:
        return Insn(a, 2, "sub.w", (r16(b1 >> 4), r16(b1 & 0xF)), raw=d[a:a + 2],
                    sd=(R("w", b1 & 0xF), R("w", b1 >> 4)))
    if b0 == 0x1A:
        if b1 & 0x80:
            return Insn(a, 2, "sub.l", (r32(b1 >> 4 & 7), r32(b1 & 7)),
                        raw=d[a:a + 2],
                        sd=(R("l", b1 & 7), R("l", b1 >> 4 & 7)))
        return Insn(a, 2, "dec.b", (r8(b1 & 0xF),), raw=d[a:a + 2],
                    sd=(R("b", b1 & 0xF), I("b", 1)))
    if b0 == 0x1B:
        r = _decode_step(d, a, b0, b1)
        if r:
            return r
    if b0 == 0x1C:
        return Insn(a, 2, "cmp.b", (r8(b1 >> 4), r8(b1 & 0xF)), raw=d[a:a + 2],
                    sd=(R("b", b1 & 0xF), R("b", b1 >> 4)))
    if b0 == 0x1D:
        return Insn(a, 2, "cmp.w", (r16(b1 >> 4), r16(b1 & 0xF)), raw=d[a:a + 2],
                    sd=(R("w", b1 & 0xF), R("w", b1 >> 4)))
    if b0 == 0x1E:
        return Insn(a, 2, "subx", (), raw=d[a:a + 2])
    if b0 == 0x1F:
        if b1 & 0x80:
            return Insn(a, 2, "cmp.l", (r32(b1 >> 4 & 7), r32(b1 & 7)),
                        raw=d[a:a + 2],
                        sd=(R("l", b1 & 7), R("l", b1 >> 4 & 7)))
        return Insn(a, 2, "das", (r8(b1 & 0xF),), raw=d[a:a + 2])

    # --- 0x2x / 0x3x : MOV.B @aa:8 ---
    # @aa:8 is the top page: 0x4C means 0xFFFF4C. It is how the compiler
    # reaches the I/O block in two bytes.
    if hi in (0x2, 0x3):
        addr = 0xFFFF00 | b1
        mem = ("abs", "b", addr)
        reg = ("r", "b", lo)
        if hi == 0x2:
            return Insn(a, 2, "mov.b", ("@0x%06X" % addr, r8(lo)),
                        raw=d[a:a + 2], sd=(reg, mem))
        return Insn(a, 2, "mov.b", (r8(lo), "@0x%06X" % addr),
                    raw=d[a:a + 2], sd=(mem, reg))

    # --- 0x4x : Bcc d:8 ---
    if hi == 0x4:
        disp = _s8(b1)
        tgt = a + 2 + disp
        return Insn(a, 2, CC[lo], ("0x%06X" % tgt,),
                    K_JMP if lo == 0 else K_JCC, tgt, d[a:a + 2])

    # --- 0x5x : the control-transfer block ---
    if b0 in (0x50, 0x51, 0x52, 0x53):
        m = ("mulxu.b", "divxu.b", "mulxu.w", "divxu.w")[b0 - 0x50]
        return Insn(a, 2, m, (), raw=d[a:a + 2])
    if b0 == 0x54:
        return Insn(a, 2, "rts", kind=K_RET, raw=d[a:a + 2])
    if b0 == 0x55:
        disp = _s8(b1)
        tgt = a + 2 + disp
        return Insn(a, 2, "bsr", ("0x%06X" % tgt,), K_CALL, tgt, d[a:a + 2])
    if b0 == 0x56:
        return Insn(a, 2, "rte", kind=K_RTE, raw=d[a:a + 2])
    if b0 == 0x57:
        return Insn(a, 2, "trapa", ("#%d" % ((b1 >> 4) & 3),), K_TRAP,
                    raw=d[a:a + 2])
    if b0 == 0x58 and n >= 4:
        cc = b1 >> 4
        disp = _s16(u16(d, a + 2))
        tgt = a + 4 + disp
        return Insn(a, 4, CC[cc] + ".w", ("0x%06X" % tgt,),
                    K_JMP if cc == 0 else K_JCC, tgt, d[a:a + 4])
    if b0 == 0x59:
        return Insn(a, 2, "jmp", ("@%s" % r32(b1 >> 4 & 7),), K_JMP,
                    raw=d[a:a + 2])
    if b0 == 0x5A and n >= 4:
        tgt = u24(d, a + 1)
        return Insn(a, 4, "jmp", ("@0x%06X" % tgt,), K_JMP, tgt, d[a:a + 4])
    if b0 == 0x5B:
        return Insn(a, 2, "jmp", ("@@0x%02X" % b1,), K_JMP, raw=d[a:a + 2])
    if b0 == 0x5C and n >= 4:
        disp = _s16(u16(d, a + 2))
        tgt = a + 4 + disp
        return Insn(a, 4, "bsr", ("0x%06X" % tgt,), K_CALL, tgt, d[a:a + 4])
    if b0 == 0x5D:
        return Insn(a, 2, "jsr", ("@%s" % r32(b1 >> 4 & 7),), K_CALL,
                    raw=d[a:a + 2])
    if b0 == 0x5E and n >= 4:
        tgt = u24(d, a + 1)
        return Insn(a, 4, "jsr", ("@0x%06X" % tgt,), K_CALL, tgt, d[a:a + 4])
    if b0 == 0x5F:
        return Insn(a, 2, "jsr", ("@@0x%02X" % b1,), K_CALL, raw=d[a:a + 2])

    # --- 0x6x ---
    if hi == 0x6:
        r = _decode_6(d, a, n)
        if r:
            return r

    # --- 0x7x ---
    if b0 in (0x70, 0x71, 0x72, 0x73):
        m = ("bset", "bnot", "bclr", "btst")[b0 - 0x70]
        bit = (b1 >> 4) & 7
        return Insn(a, 2, m, ("#%d" % bit, r8(b1 & 0xF)), raw=d[a:a + 2],
                    sd=(R("b", b1 & 0xF), I("b", bit)))
    if b0 in (0x74, 0x75, 0x76, 0x77):
        return Insn(a, 2, ("bor", "bxor", "band", "bld")[b0 - 0x74],
                    (), raw=d[a:a + 2])
    if b0 == 0x78 and n >= 8:
        return Insn(a, 8, "mov", ("@(d:24,ERs)",), raw=d[a:a + 8])
    if b0 == 0x79:
        r = _decode_79(d, a, n)
        if r:
            return r
    if b0 == 0x7A:
        r = _decode_7a(d, a, n)
        if r:
            return r
    if b0 == 0x7B and n >= 4:
        return Insn(a, 4, "eepmov", (), raw=d[a:a + 4])
    if b0 in (0x7C, 0x7D, 0x7E, 0x7F):
        r = _decode_7c(d, a, n)
        if r:
            return r

    # --- 0x8x-0xFx : one-byte-immediate ALU on Rd ---
    if hi >= 0x8:
        m = {0x8: "add.b", 0x9: "addx.b", 0xA: "cmp.b", 0xB: "subx.b",
             0xC: "or.b", 0xD: "xor.b", 0xE: "and.b", 0xF: "mov.b"}[hi]
        return Insn(a, 2, m, ("#0x%02X" % b1, r8(lo)), raw=d[a:a + 2],
                    sd=(R("b", lo), I("b", b1)))

    return Insn(a, 2, "?%02X%02X" % (b0, b1), kind=K_UNK, raw=d[a:a + 2])


def load(path):
    return open(path, "rb").read()
