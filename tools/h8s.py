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


class Insn:
    __slots__ = ("addr", "length", "mnem", "ops", "kind", "target", "raw")

    def __init__(self, addr, length, mnem, ops=(), kind=K_SEQ, target=None,
                 raw=b""):
        self.addr, self.length = addr, length
        self.mnem, self.ops, self.kind = mnem, ops, kind
        self.target = target          # resolved absolute target, when static
        self.raw = raw

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
        # 01 00 then a MOV.L-shaped body
        b2, b3 = d[a + 2], d[a + 3]
        if b2 == 0x69:
            return Insn(a, 4, "mov.l",
                        ((r32(b3 & 7 | 0), "@%s" % r32(b3 >> 4)) if b3 & 0x80
                         else ("@%s" % r32(b3 >> 4), r32(b3 & 7))), raw=d[a:a + 4])
        if b2 == 0x6B:
            sub = b3 & 0xF0
            if sub in (0x00, 0x80):        # @aa:16
                return Insn(a, 6, "mov.l", (), raw=d[a:a + 6])
            return Insn(a, 8, "mov.l", (), raw=d[a:a + 8])
        if b2 == 0x6D:
            reg = b3 >> 4
            if b3 & 0x80:
                return Insn(a, 4, "push.l", (r32(b3 & 7),), raw=d[a:a + 4])
            return Insn(a, 4, "pop.l", (r32(b3 & 7),), raw=d[a:a + 4])
        if b2 == 0x6F:
            return Insn(a, 6, "mov.l", (), raw=d[a:a + 6])
        if b2 == 0x78:
            return Insn(a, 10, "mov.l", (), raw=d[a:a + 10])
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
                raw=d[a:a + 4])


def _decode_7a(d, a, n):
    if n < 6:
        return None
    sel = d[a + 1] >> 4
    reg = d[a + 1] & 0xF
    op = _IMM_OPS.get(sel)
    if op is None:
        return None
    return Insn(a, 6, op + ".l", ("#0x%08X" % u32(d, a + 2), r32(reg)),
                raw=d[a:a + 6])


# --- 0x6x memory group ----------------------------------------------------

def _decode_6(d, a, n):
    b0, b1 = d[a], d[a + 1]
    lo = b0 & 0xF

    if lo in (0x0, 0x1, 0x2, 0x3):        # BSET/BNOT/BCLR/BTST Rn,<ea>
        return Insn(a, 2, ("bset", "bnot", "bclr", "btst")[lo], (), raw=d[a:a + 2])
    if lo in (0x4, 0x5, 0x6):             # OR/XOR/AND .w Rs,Rd
        return Insn(a, 2, ("or", "xor", "and")[lo - 4] + ".w",
                    (r16(b1 >> 4), r16(b1 & 0xF)), raw=d[a:a + 2])
    if lo == 0x7:
        return Insn(a, 2, "bst/bist", (), raw=d[a:a + 2])
    if lo == 0x8:                         # MOV.B @ERs,Rd / Rs,@ERd
        if b1 & 0x80:
            return Insn(a, 2, "mov.b", (r8(b1 & 0xF), "@%s" % r32(b1 >> 4 & 7)),
                        raw=d[a:a + 2])
        return Insn(a, 2, "mov.b", ("@%s" % r32(b1 >> 4 & 7), r8(b1 & 0xF)),
                    raw=d[a:a + 2])
    if lo == 0x9:                         # MOV.W @ERs,Rd / Rs,@ERd
        if b1 & 0x80:
            return Insn(a, 2, "mov.w", (r16(b1 & 0xF), "@%s" % r32(b1 >> 4 & 7)),
                        raw=d[a:a + 2])
        return Insn(a, 2, "mov.w", ("@%s" % r32(b1 >> 4 & 7), r16(b1 & 0xF)),
                    raw=d[a:a + 2])
    if lo in (0xA, 0xB):                  # MOV @aa:16 / @aa:24
        sz = ".b" if lo == 0xA else ".w"
        sub = b1 & 0xF0
        if sub in (0x00, 0x80):
            if n < 4:
                return None
            return Insn(a, 4, "mov" + sz, ("@0x%04X" % u16(d, a + 2),),
                        raw=d[a:a + 4])
        if n < 6:
            return None
        return Insn(a, 6, "mov" + sz, ("@0x%06X" % u24(d, a + 3),),
                    raw=d[a:a + 6])
    if lo == 0xC:                         # MOV.B @ERs+,Rd / Rs,@-ERd
        return Insn(a, 2, "mov.b", (), raw=d[a:a + 2])
    if lo == 0xD:                         # MOV.W @ERs+,Rd  (push/pop when ER7)
        reg = b1 >> 4 & 7
        if b1 & 0x80:
            m = "push.w" if reg == 7 else "mov.w"
            return Insn(a, 2, m, (r16(b1 & 0xF),), raw=d[a:a + 2])
        m = "pop.w" if reg == 7 else "mov.w"
        return Insn(a, 2, m, (r16(b1 & 0xF),), raw=d[a:a + 2])
    if lo in (0xE, 0xF):                  # MOV @(d:16,ERs)
        if n < 4:
            return None
        sz = ".b" if lo == 0xE else ".w"
        return Insn(a, 4, "mov" + sz, (), raw=d[a:a + 4])
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
        return Insn(a, 2, "add.b", (r8(b1 >> 4), r8(b1 & 0xF)), raw=d[a:a + 2])
    if b0 == 0x09:
        return Insn(a, 2, "add.w", (r16(b1 >> 4), r16(b1 & 0xF)), raw=d[a:a + 2])
    if b0 == 0x0A:
        if b1 & 0x80:
            return Insn(a, 2, "add.l", (r32(b1 >> 4 & 7), r32(b1 & 7)),
                        raw=d[a:a + 2])
        return Insn(a, 2, "inc.b", (r8(b1 & 0xF),), raw=d[a:a + 2])
    if b0 == 0x0B:
        return Insn(a, 2, "adds/inc", (), raw=d[a:a + 2])
    if b0 == 0x0C:
        return Insn(a, 2, "mov.b", (r8(b1 >> 4), r8(b1 & 0xF)), raw=d[a:a + 2])
    if b0 == 0x0D:
        return Insn(a, 2, "mov.w", (r16(b1 >> 4), r16(b1 & 0xF)), raw=d[a:a + 2])
    if b0 == 0x0E:
        return Insn(a, 2, "addx", (), raw=d[a:a + 2])
    if b0 == 0x0F:
        if b1 & 0x80:
            return Insn(a, 2, "mov.l", (r32(b1 >> 4 & 7), r32(b1 & 7)),
                        raw=d[a:a + 2])
        return Insn(a, 2, "daa", (r8(b1 & 0xF),), raw=d[a:a + 2])

    # --- 0x1x ---
    if b0 in (0x10, 0x11, 0x12, 0x13):
        m = ("shll/shal", "shlr/shar", "rotxl/rotl", "rotxr/rotr")[b0 - 0x10]
        return Insn(a, 2, m, (), raw=d[a:a + 2])
    if b0 in (0x14, 0x15, 0x16):
        return Insn(a, 2, ("or", "xor", "and")[b0 - 0x14] + ".b",
                    (r8(b1 >> 4), r8(b1 & 0xF)), raw=d[a:a + 2])
    if b0 == 0x17:
        return Insn(a, 2, "not/extu/exts/neg", (), raw=d[a:a + 2])
    if b0 == 0x18:
        return Insn(a, 2, "sub.b", (r8(b1 >> 4), r8(b1 & 0xF)), raw=d[a:a + 2])
    if b0 == 0x19:
        return Insn(a, 2, "sub.w", (r16(b1 >> 4), r16(b1 & 0xF)), raw=d[a:a + 2])
    if b0 == 0x1A:
        if b1 & 0x80:
            return Insn(a, 2, "sub.l", (r32(b1 >> 4 & 7), r32(b1 & 7)),
                        raw=d[a:a + 2])
        return Insn(a, 2, "dec.b", (r8(b1 & 0xF),), raw=d[a:a + 2])
    if b0 == 0x1B:
        return Insn(a, 2, "subs/dec", (), raw=d[a:a + 2])
    if b0 == 0x1C:
        return Insn(a, 2, "cmp.b", (r8(b1 >> 4), r8(b1 & 0xF)), raw=d[a:a + 2])
    if b0 == 0x1D:
        return Insn(a, 2, "cmp.w", (r16(b1 >> 4), r16(b1 & 0xF)), raw=d[a:a + 2])
    if b0 == 0x1E:
        return Insn(a, 2, "subx", (), raw=d[a:a + 2])
    if b0 == 0x1F:
        if b1 & 0x80:
            return Insn(a, 2, "cmp.l", (r32(b1 >> 4 & 7), r32(b1 & 7)),
                        raw=d[a:a + 2])
        return Insn(a, 2, "das", (r8(b1 & 0xF),), raw=d[a:a + 2])

    # --- 0x2x / 0x3x : MOV.B @aa:8 ---
    if hi == 0x2:
        return Insn(a, 2, "mov.b", ("@0x%02X" % b1, r8(lo)), raw=d[a:a + 2])
    if hi == 0x3:
        return Insn(a, 2, "mov.b", (r8(lo), "@0x%02X" % b1), raw=d[a:a + 2])

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
        return Insn(a, 2, ("bset", "bnot", "bclr", "btst")[b0 - 0x70],
                    (), raw=d[a:a + 2])
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
        return Insn(a, 2, m, ("#0x%02X" % b1, r8(lo)), raw=d[a:a + 2])

    return Insn(a, 2, "?%02X%02X" % (b0, b1), kind=K_UNK, raw=d[a:a + 2])


def load(path):
    return open(path, "rb").read()
