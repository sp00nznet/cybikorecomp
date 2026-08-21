"""The Cybiko `.app` container.

A `.app` is not an executable. It is a little archive holding everything one
application needs -- its code, its icon, its help text, its sounds -- and the
H8S code is one member of it, conventionally named `main.e`.

    offset  size  field
    0       2     "Cy"
    2       2     entry count
    4       2     (end of the name table)
    6       10*n  entries: u16 name_offset, u32 data_offset, u32 length
    ...           NUL-terminated names, at the offsets above
    ...           member data

Every member begins with a one-byte compression method:

    0x00   stored, the rest is the data
    0x02   compressed, followed by a big-endian u32 of the unpacked size

The 0x02 codec is not yet identified -- see docs/FORMATS.md. Members that are
stored come out whole, which is enough to read `root.inf` and the sound and
text members on most applications.

    python tools/cyapp.py <file.app> [-x outdir]
"""
import os
import struct
import sys

MAGIC = b"Cy"
STORED, COMPRESSED = 0x00, 0x02


class Member:
    __slots__ = ("name", "offset", "length", "method", "unpacked", "payload")

    def __init__(self, name, offset, length, blob):
        self.name, self.offset, self.length = name, offset, length
        raw = blob[offset:offset + length]
        self.method = raw[0] if raw else None
        if self.method == COMPRESSED and len(raw) >= 5:
            self.unpacked = struct.unpack_from(">I", raw, 1)[0]
            self.payload = raw[5:]
        else:
            self.unpacked = max(0, len(raw) - 1)
            self.payload = raw[1:]

    @property
    def stored(self):
        return self.method == STORED

    def __repr__(self):
        return "<%s %s %d->%d>" % (self.name,
                                   "stored" if self.stored else "packed",
                                   len(self.payload), self.unpacked)


def parse(path):
    """-> list of Member. Raises ValueError if the container is malformed."""
    blob = open(path, "rb").read()
    if blob[:2] != MAGIC:
        raise ValueError("%s: not a Cybiko .app (magic %r)" % (path, blob[:2]))
    count = struct.unpack_from(">H", blob, 2)[0]

    members = []
    for i in range(count):
        name_off, data_off, length = struct.unpack_from(">HII", blob, 6 + 10 * i)
        end = blob.index(b"\0", name_off)
        members.append(Member(blob[name_off:end].decode("latin1"),
                              data_off, length, blob))

    # The container is dense: every byte after the header belongs to exactly
    # one member, and the last one ends at EOF. Checking that is the cheapest
    # way to know the layout has been read correctly.
    covered = max((m.offset + m.length for m in members), default=0)
    if covered != len(blob):
        raise ValueError("%s: members cover 0x%X of 0x%X bytes"
                         % (path, covered, len(blob)))
    return members


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    path = argv[0]
    outdir = argv[argv.index("-x") + 1] if "-x" in argv else None

    members = parse(path)
    print("%s: %d members" % (os.path.basename(path), len(members)))
    print("  %-14s %8s %10s %10s" % ("name", "method", "packed", "unpacked"))
    for m in members:
        print("  %-14s %8s %10d %10d"
              % (m.name, "stored" if m.stored else "packed(%d)" % m.method,
                 len(m.payload), m.unpacked))

    if outdir:
        os.makedirs(outdir, exist_ok=True)
        wrote = skipped = 0
        for m in members:
            if not m.stored:
                skipped += 1
                continue
            with open(os.path.join(outdir, m.name.replace("/", "_")), "wb") as f:
                f.write(m.payload)
            wrote += 1
        print("\nextracted %d stored members to %s (%d still packed)"
              % (wrote, outdir, skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
