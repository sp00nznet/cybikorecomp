# The machine loads its own OS

Everything here used to be recompiled from a RAM image dumped out of MAME.
That made MAME a build dependency, and worse, it capped what could be
recompiled at whatever happened to be resident the moment the dump was taken
— which is why the keyboard is stuck ([KEYBOARD.md](KEYBOARD.md)): its driver
is a module CyOS loads later, and it was not in the picture.

It does not have to be that way. The boot ROM is recompiled too. Give it a
flash to read and it finds CyOS, decompresses it and starts it, exactly as the
hardware does:

```
$ CYFLASH=flash_v1246.bin loader boot.img cyram.bin
Starting CyOS boot loader v1.1.2

Testing 512k of memory @200000
Data register test passed
Address bus test passed, memory ok

Preparing to load CyOS

Detected flash device model 3 [1019 blocks of 254 bytes]
OS loaded
Got header: magic 1C0FFAB (valid) LZSS compressed image
boot header size 12
Compressed size 72510 decompressed size 128260
decompressing...
Got header: magic 1234ABCD (valid) plain image
Starting...

Initializing dispatcher...
```

**The result is byte-for-byte the image MAME produced.** 128,260 bytes
decompressed; 55 differ from the MAME dump and all 55 are above `0x21F03A`,
in CyOS's variable region, because that dump was taken after CyOS had been
running for a while. Every byte of code and constant data matches.

`boot.img` is a `cyimage.py` build with an empty RAM half — the ROM fills it.

## What it took

Three bugs in the flash model, each of which the boot ROM diagnosed out loud.

**`0x57` is Status Register Read, not a page read.** The AT45DB has two
opcodes for status and the boot ROM uses the older one. Reading it as a page
read sent the model into address collection, so the ROM got the `0xFF` a
half-parsed command returns, pulled bits 5-3 out of it and printed

```
Detected flash device model 7 [-5 blocks of 0 bytes]
```

— a model number off the end of its own table. With `0x57` served as status,
`0x9C` reads back as model 3, which is the entry that says 2048 pages.

**Chip select is active low.** `and.b #0xEF, @0xFFFF62` before a command and
`or.b #0x10` after it, at `0x002DB4` and `0x002E1E`. The model had it
backwards and was resetting the state machine at the start of every command
rather than the end.

**Four don't-care bytes, on every read form, not one.** The ROM makes this
one easy to confirm rather than look up: at `0x002BB6` it builds the command
and the 24-bit address as a single 32-bit word, sends those four bytes, and
then sends the same four again as the don't-cares.

## And one bug in the CPU

With the flash answering, the loader ran, decompressed CyOS — and produced
`Im?mim?mz 2XQdiR ptcher!` where CyOS says `Initializing dispatcher...`.
Literal runs were right and some copies were right, which is what a
back-reference bug looks like.

It was one instruction. `01 F0 64 20` had been decoded as `tas @er2`; it is
**`or.l er2, er0`**. The `01 F0` prefix widens the 16-bit logic opcodes
`0x64`-`0x66` to longword — TAS is `01 E0 7B 0r 0C`, which looks similar and
appears nowhere in this image. There are 55 sites: 40 `or.l` and 15 `xor.l`,
every one of them previously emitted as "flag a byte and set its top bit",
and one of them is in the decompressor's inner loop at `0x00394A`.

Fixing that one line took the decompressed image from 81,671 wrong bytes to
zero.

## The codec is LZSS

The ROM says so — `Got header: magic 1C0FFAB (valid) LZSS compressed image` —
and then does it, at `0x0038B2`-`0x003996`. That is the same `0x02` method
that packs members inside a `.app` container and has been listed as
unidentified in [FORMATS.md](FORMATS.md) since the start. There is a
reference implementation in the boot ROM to read, and a running one to check
against.

## What it is for

A dump taken later. CyOS loads modules from flash at runtime — `keybd.app`
among them — and code that arrives at runtime cannot be translated ahead of
time. Now that the machine boots itself, the dump can be taken at any moment
rather than whenever MAME happened to be cooperating, and whatever is
resident at that moment becomes ordinary traced code.

As of now the loader gets CyOS as far as `Initializing memmgr...`, the same
place the MAME-dumped image reaches, and no module has loaded yet. Getting
further is now this project's own problem to debug with its own tools, which
is the point.
