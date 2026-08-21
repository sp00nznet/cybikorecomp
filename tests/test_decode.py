"""Self-checks for the H8S decoder and the .app container.

Run:  python tests/test_decode.py [cyrom112.bin] [dir-of-apps]

Both arguments are optional; the encoding checks need neither.
"""
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import analyze                                    # noqa: E402
import cyapp                                      # noqa: E402
from h8s import K_CALL, K_JCC, K_JMP, K_RET, decode, load   # noqa: E402


def d(*b):
    return bytes(b)


def test_lengths():
    """Length is the field that matters most.

    On a variable-length machine a wrong length does not cost you one
    instruction, it costs you the rest of the stream -- every following decode
    starts at the wrong byte. These pin one encoding of each length the H8S
    has.
    """
    cases = [
        (d(0x00, 0x00), 2, "nop"),
        (d(0x54, 0x70), 2, "rts"),
        (d(0x0C, 0x23), 2, "mov.b"),
        (d(0x79, 0x01, 0x12, 0x34), 4, "mov.w"),
        (d(0x7A, 0x11, 0x00, 0x11, 0x22, 0x33), 6, "add.l"),
        (d(0x7A, 0x01, 0x00, 0x11, 0x22, 0x33), 6, "mov.l"),
        (d(0x5E, 0x00, 0x12, 0x34), 4, "jsr"),
        (d(0x5A, 0x00, 0x0D, 0x6A), 4, "jmp"),
        (d(0x5C, 0x00, 0x01, 0x00), 4, "bsr"),
        (d(0x01, 0x20, 0x6D, 0xF4), 4, "stm.l"),
        (d(0x01, 0x20, 0x6D, 0x76), 4, "ldm.l"),
    ]
    for raw, length, mnem in cases:
        i = decode(raw, 0)
        assert i.length == length, \
            "%s: length %d, expected %d" % (raw.hex(), i.length, length)
        assert i.mnem.startswith(mnem.split(".")[0]), \
            "%s: decoded %s, expected %s" % (raw.hex(), i.mnem, mnem)
    print("lengths  ok  (%d encodings, one of every instruction size)" % len(cases))


def test_stm_ldm():
    """STM stores ERm..ERm+n; LDM encodes the *last* register, restoring in
    reverse. Getting that backwards names the wrong registers and still
    decodes, so it is worth pinning."""
    assert decode(d(0x01, 0x30, 0x6D, 0xF0), 0).ops[0] == "(er0-er3)"
    assert decode(d(0x01, 0x30, 0x6D, 0x73), 0).ops[1] == "(er0-er3)"
    assert decode(d(0x01, 0x20, 0x6D, 0xF4), 0).ops[0] == "(er4-er6)"
    assert decode(d(0x01, 0x20, 0x6D, 0x76), 0).ops[1] == "(er4-er6)"
    print("stm/ldm  ok  (register ranges, both directions)")


def at(addr, *b):
    """A buffer with `b` placed at `addr`.

    decode() indexes the image directly, so an address *is* a buffer offset --
    the analyzer assumes the image is loaded at zero, which is true of the H8S
    internal ROM. Testing a PC-relative branch away from zero therefore needs
    real padding in front of it.
    """
    return bytes(addr) + bytes(b)


def test_branches():
    """Branch targets are PC-relative to the *end* of the instruction."""
    i = decode(d(0x40, 0x10), 0)          # bra +0x10
    assert i.kind == K_JMP and i.target == 0x12, hex(i.target or -1)
    i = decode(at(0x100, 0x46, 0xFE), 0x100)       # bne -2, from 0x100
    assert i.kind == K_JCC and i.target == 0x100, hex(i.target or -1)
    i = decode(at(0x200, 0x58, 0x60, 0x01, 0x00), 0x200)   # bne.w +0x100
    assert i.kind == K_JCC and i.target == 0x304, hex(i.target or -1)
    i = decode(d(0x55, 0x20), 0)          # bsr +0x20
    assert i.kind == K_CALL and i.target == 0x22
    assert decode(d(0x54, 0x70), 0).kind == K_RET
    # register-indirect transfers have no static target, and must say so
    assert decode(d(0x5D, 0x20), 0).target is None
    assert decode(d(0x59, 0x20), 0).target is None
    print("branches ok  (relative targets, and indirects report no target)")


def test_rom(path):
    data = load(path)
    ops, reached, entries, calls, unresolved = analyze.analyze(data)

    assert analyze.vectors(data), "no interrupt vectors found"
    assert analyze.vectors(data)[0][0] == 0, "vector 0 is not the reset vector"
    assert len(reached) > 2000, "only %d instructions reached" % len(reached)
    assert not unresolved.get("undecodable opcode"), \
        "undecodable opcodes at %s" % unresolved["undecodable opcode"][:4]

    # Prologue and epilogue must balance. They are emitted as a pair by the
    # compiler, so a mismatch means the decoder is mis-reading one of them.
    stm = sum(1 for a in reached if ops[a].mnem == "stm.l")
    ldm = sum(1 for a in reached if ops[a].mnem == "ldm.l")
    assert stm == ldm, "stm.l %d != ldm.l %d" % (stm, ldm)

    print("rom      ok  (%d instructions, %d entries, %d stm/ldm pairs, "
          "0 undecodable)" % (len(reached), len(entries), stm))


def test_apps(dirname):
    files = sorted(glob.glob(os.path.join(dirname, "*.app")))
    assert files, "no .app files in " + dirname
    packed = stored = 0
    for f in files:
        members = cyapp.parse(f)          # raises if the layout is not dense
        assert any(m.name == "main.e" for m in members), \
            "%s has no main.e" % os.path.basename(f)
        for m in members:
            assert m.method in (cyapp.STORED, cyapp.COMPRESSED), \
                "%s/%s: unknown method 0x%02X" % (f, m.name, m.method)
            if m.stored:
                stored += 1
            else:
                packed += 1
                assert m.unpacked >= len(m.payload) // 4, \
                    "%s/%s: implausible unpacked size" % (f, m.name)
    print("apps     ok  (%d containers, %d members: %d stored, %d packed)"
          % (len(files), stored + packed, stored, packed))


if __name__ == "__main__":
    test_lengths()
    test_stm_ldm()
    test_branches()
    rom = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CYROM")
    if rom and os.path.exists(rom):
        test_rom(rom)
    else:
        print("rom      skipped (pass a path to cyrom112.bin)")
    apps = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("CYAPPS")
    if apps and os.path.isdir(apps):
        test_apps(apps)
    else:
        print("apps     skipped (pass a directory of .app files)")
    print("all checks passed")
