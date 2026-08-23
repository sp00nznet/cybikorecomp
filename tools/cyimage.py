"""Build one address space out of the pieces a running Cybiko has in it.

The boot ROM and CyOS are separate files but not separate worlds -- CyOS calls
down into the boot ROM constantly, for memcpy and memset among other things.
Analysed apart, every one of those calls looks like a target outside the image;
analysed together they are ordinary edges.

    0x000000-0x007FFF   cyrom112.bin, the H8S internal ROM
    0x200000-0x27FFFF   cyram.bin, SRAM dumped out of MAME after boot

The SRAM is 512K, not 256K. The boot ROM says so itself -- "Testing 512k
of memory @200000" -- and a stack pointer at 0x27FF6C proves it uses the
upper half.

Everything between is unmapped and filled with 0xFF, which the analyzer treats
as padding rather than code.

    python tools/cyimage.py cyrom112.bin cyram.bin -o cybiko.img
"""
import sys

ROM_BASE, ROM_SIZE = 0x000000, 0x008000
RAM_BASE, RAM_SIZE = 0x200000, 0x080000
IMAGE_SIZE = RAM_BASE + RAM_SIZE


def build(rom_path, ram_path):
    img = bytearray(b"\xFF" * IMAGE_SIZE)
    if rom_path:
        rom = open(rom_path, "rb").read()
        if len(rom) != ROM_SIZE:
            raise ValueError("%s: expected %d bytes, got %d"
                             % (rom_path, ROM_SIZE, len(rom)))
        img[ROM_BASE:ROM_BASE + len(rom)] = rom
    if ram_path:
        ram = open(ram_path, "rb").read()
        if len(ram) != RAM_SIZE:
            raise ValueError("%s: expected %d bytes, got %d"
                             % (ram_path, RAM_SIZE, len(ram)))
        img[RAM_BASE:RAM_BASE + len(ram)] = ram
    return bytes(img)


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    out = "cybiko.img"
    if "-o" in argv:
        i = argv.index("-o")
        out = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]

    img = build(argv[0], argv[1])
    with open(out, "wb") as f:
        f.write(img)
    print("%s: %d bytes  (rom @0x%06X, ram @0x%06X)"
          % (out, len(img), ROM_BASE, RAM_BASE))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
