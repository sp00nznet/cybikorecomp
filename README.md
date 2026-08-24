# cybikorecomp

**A static-recompilation toolkit for the Cybiko — a 2000 handheld with a Hitachi H8S, a keyboard, and a 900 MHz radio in it.**

The Cybiko Classic runs a **Hitachi H8S/2246** at 11 MHz in advanced mode:
32-bit registers, 24-bit addresses, big-endian, variable-length instructions.
Around it sit 512 KB of flash holding **CyOS**, a 32 KB internal boot ROM, a
QWERTY keyboard, and a 900 MHz packet radio that let a room full of them form
an ad-hoc mesh. Roughly 400 applications shipped for it.

That makes it a very different target from the last one in this library. The
[Tamagotchi](https://github.com/sp00nznet/tamarecomp) was recompilable *because
of* its ISA — a 4-bit core whose only page-changing instruction took an
immediate, so every jump target in the ROM was a build-time constant. The H8S
is a general-purpose register machine, and its calls go through registers. That
changes what "statically recompilable" is even allowed to mean here, and the
first job is measuring it honestly rather than assuming.

> **No ROM data here.** Firmware images and `.app` files are `.gitignore`d.
> This repo is the decoder, the analyzer and the tools — bring your own dumps.

---

## Status

**CyOS boots.** It initialises its dispatcher, name list, flash and memory
manager, reads its own filesystem over SPI, runs on a 10 ms tick and draws to
the LCD. It is waiting on the keyboard now.

| Stage | State |
|---|---|
| **`.app` container format** — parse, list, extract | ✅ 410/410 apps parse |
| **H8S/2000 decoder** — lengths, control flow, operands | ✅ 0 undecodable |
| **Control-flow analysis** | ✅ 39,975 instructions, 1,980 entry points |
| **CyOS extraction** — unpacked, out of MAME | ✅ see [docs/CYOS.md](docs/CYOS.md) |
| **Indirect calls** — 227 sites | ✅ three mechanisms, see [docs/INDIRECT.md](docs/INDIRECT.md) |
| **C emitter** | ✅ 100.0% of traced instructions |
| **Runtime** — CPU state, memory, flags, interrupts | ✅ |
| **Peripherals** — flash, timers, LCD | ✅ see [docs/PERIPHERALS.md](docs/PERIPHERALS.md) |
| **Frontends** — terminal, and an SDL window | ✅ |
| **Keyboard** — the 9x8 matrix, and typing into it | 🔨 nothing scans it, see [docs/KEYBOARD.md](docs/KEYBOARD.md) |
| **Peripherals** — sound, radio | ⬜ not started |
| **`0x02` compression** | 🔨 unidentified, and no longer blocking |

![the Cybiko's panel in a window](docs/screenshot.png)

The four bars are CyOS's own grey ramp — `FF AA 55 00` repeated, identical on
all 100 rows — which is the last thing it draws before it starts waiting for a
key. It is a real frame off a real controller model, not a test card.

```
$ smoke cybiko.img 20000000 cyos
CyOS header ok, entry 0x21965C
serial output (110 bytes):
---
Initializing dispatcher...
Initializing names list...
Initializing flash device...
Initializing memmgr...
---
ok: ran the whole budget inside the image
```

```
$ python tests/test_decode.py cyrom112.bin apps/
lengths  ok  (11 encodings, one of every instruction size)
stm/ldm  ok  (register ranges, both directions)
branches ok  (relative targets, and indirects report no target)
rom      ok  (2763 instructions, 101 entries, 110 stm/ldm pairs, 0 undecodable)
apps     ok  (410 containers, 11011 members: 2373 stored, 8638 packed)
```

## The short version

The Cybiko is the opposite of the last target in this library. The
[Tamagotchi](https://github.com/sp00nznet/tamarecomp) was recompilable because
its 4-bit core had nowhere to put a computed address, so every jump target was
a build-time constant. Here almost nothing is: the H8S is a register machine
running C++, and 227 call sites go through a register.

That turned out not to matter. The emitter puts a label on every traced
instruction and one dense dispatch switch at the bottom, so `jsr @ERn` becomes
a switch on the register and cannot land somewhere without code. Resolving the
targets — 99 vtables, 641 of them — makes that dispatch *small*, not correct.

Two other things that looked like walls were not:

- **CyOS is packed with an unidentified codec.** It also unpacks itself at
  every boot, so MAME dumps the plaintext. [docs/CYOS.md](docs/CYOS.md).
- **65% of the boot ROM was unreachable.** It was calls into CyOS and vice
  versa; analysing the two as one address space took unresolved transfers from
  2,533 to 227. [docs/INDIRECT.md](docs/INDIRECT.md).

And one that is a wall, handled rather than solved. A C++ method nothing calls
directly is reachable only through its own vtable — and the vtable detector
will not believe a run containing an address no trace has reached, because
loosening that test to "looks like code" took the trace from 39,959
instructions to 203,519, more code than the image holds. So those are not
guessed at: the dispatch reports the address it was refused, that address goes
in the seeds file, and the image is emitted again. Two rounds settled it.

## What the boot ROM looks like

`cyrom112.bin` is the 32 KB H8S internal ROM — the first thing that runs, and
the natural first target because it is self-contained.

```
size            32768 bytes (0x8000); 25332 before the 0xFF padding
vectors filled  44
entry points    101 (57 of them call targets)
instructions    2763
bytes reached   8740  (34.5% of the non-padding image)

unresolved      47
  indirect jsr    47   0x001710 0x0016F6 0x0016DC 0x0016C2 ...
```

**34.5%, and 47 unresolved indirect calls.** That is the honest starting point
and it is the whole story of this project so far. On the Tamagotchi the
equivalent number was 100% with zero unresolved transfers, because a 4-bit core
has nowhere to *put* a computed address. Here the compiler emits `jsr @ER2` and
the target arrives in a register from somewhere else entirely — a vtable, a
callback, a jump table built at runtime. Resolving those is the actual work of
recompiling an H8S image, and no amount of looking at one instruction does it.

## Instruction lengths are the whole game

The H8S encodes instructions in 2, 4, 6, 8 or 10 bytes. On a fixed-width
machine a wrong opcode costs you one instruction. Here it costs you *the rest
of the stream*, because the next decode starts on the wrong byte.

The first sweep over the boot ROM left 3.4% of instructions undecodable, and
they were not scattered — 260 of them were `01 10`, `01 20` and `01 30`,
always followed by `6D`:

```
000F26: 01 20 6d f4     0012BE: 01 30 6d f0
001276: 01 20 6d 76     0012D2: 01 30 6d 73
```

Those are **STM.L and LDM.L**, which push and pop a run of two to four
consecutive registers. `01 n0 6D Fm` stores `ERm..ERm+n`; `01 n0 6D 7m` loads
them back, encoding the *last* register because it restores in reverse. They
are function prologues and epilogues — which is why they turned up in exactly
matched pairs, 76/76, 43/43 and 11/11, and why that balance is now an assertion
in the test suite.

They are four bytes long and the decoder was calling them two, so the stream
desynchronised at every function boundary in the ROM. Fixing that one
instruction took undecodable instructions from **262 to 2** — and both
survivors are inside a data region a linear sweep walked through, identifiable
because the decode there produces `brn`, "branch never", which no compiler has
ever emitted.

## The `.app` container

A `.app` is not an executable. It is a small archive holding everything an
application needs, with the H8S code as one member named `main.e`:

```
0   2      "Cy"
2   2      entry count
4   2      end of the name table
6   10*n   entries: u16 name_offset, u32 data_offset, u32 length
...        NUL-terminated names
...        member data
```

Every member starts with a compression method byte: `0x00` stored, `0x02`
packed with a big-endian u32 unpacked size after it. The layout is dense — the
last member ends exactly at EOF — which is a cheap way to know the header was
read correctly, and `tools/cyapp.py` raises if it ever does not hold.

**All 410 applications parse**, 11,011 members between them. 2,373 are stored
and come out whole; 8,638 are packed at an average of 2.21×.

The `0x02` codec is not yet identified — it is not zlib and the packed streams
have no recognisable header. Until it is, `main.e` cannot be extracted from a
`.app`, which is one of the two things standing between here and recompiling an
application. See [docs/FORMATS.md](docs/FORMATS.md).

## Layout

```
cybikorecomp/
├── tools/
│   ├── h8s.py           H8S/2000 decoder — lengths, operands, control flow
│   ├── analyze.py       trace from the vector table, report what is unresolved
│   ├── vtables.py       find the tables the indirect calls dispatch through
│   ├── cyimage.py       glue the boot ROM and SRAM into one address space
│   ├── emit.py          traced image → C
│   ├── cyapp.py         the .app container: parse, list, extract
│   ├── mame_dump.lua    dump CyOS out of a running MAME
│   ├── mame_lcd.lua     reconstruct a real Cybiko's panel, to compare against
│   ├── mame_iomap.lua   what a real Cybiko touches outside ROM and SRAM
│   └── mame_probe.lua   hunt a routine by how it writes memory
├── tests/
│   ├── test_decode.py   encoding checks, plus whole-ROM and whole-library ones
│   ├── smoke.c          does the recompiled image execute?
│   ├── ioprobe.c        which I/O registers does it actually touch?
│   ├── lcdprobe.c       print the panel as characters
│   └── keyprobe.c       the key matrix holds what it is told
├── include/cybikorecomp/  h8s.h  lcd.h
├── src/
│   ├── mem.c            memory and condition codes
│   ├── io.c             the peripherals, and interrupt delivery
│   ├── flash.c          the AT45DB041 behind SCI1
│   ├── lcd.c            the HD66421
│   ├── keyboard.c       the 9x8 key matrix
│   └── sdl_main.c       the panel in a window
└── docs/  CYOS.md  INDIRECT.md  FORMATS.md  PERIPHERALS.md  KEYBOARD.md
```

## Usage

```sh
python tools/cyimage.py  cyrom112.bin cyram.bin -o cybiko.img
python tools/analyze.py  cyrom112.bin          # what the boot ROM's flow looks like
python tools/vtables.py  cybiko.img cyio.bin   # the indirect-call target tables
python tools/emit.py     cybiko.img cyos.c --io cyio.bin --pc seeds.txt
python tools/cyapp.py    Calculator.app        # list a container
python tools/cyapp.py    Calculator.app -x out # extract its stored members
python tests/test_decode.py cyrom112.bin apps/ # self-checks
```

The encoding checks run with no arguments; the ROM and app checks are skipped
if you do not pass paths.

To build and run what the emitter produced:

```sh
cc -std=c11 -O1 -Iinclude -c cyos.c src/mem.c src/io.c src/flash.c src/lcd.c
cc -std=c11 -O1 -Iinclude -c tests/smoke.c tests/lcdprobe.c
cc cyos.o mem.o io.o flash.o smoke.o -o smoke
cc cyos.o mem.o io.o flash.o lcd.o lcdprobe.o -o lcdprobe

CYFLASH=flash_v1246.bin ./smoke    cybiko.img 20000000 cyos
CYFLASH=flash_v1246.bin ./lcdprobe cybiko.img 20000000 cyos
```

`smoke` prints what CyOS said on the debug serial and whether control ever
left the image; `lcdprobe` prints the panel as characters. When `smoke`
reports an address it was refused, add it to the seeds file and emit again.

The window needs SDL2 and nothing else:

```sh
cc -std=c11 -O1 -Iinclude $(pkg-config --cflags sdl2) -c src/sdl_main.c
cc cyos.o mem.o io.o flash.o lcd.o sdl_main.o $(pkg-config --libs sdl2) -o cybiko-sdl

CYFLASH=flash_v1246.bin ./cybiko-sdl cybiko.img cyos
CYFLASH=flash_v1246.bin SDL_VIDEODRIVER=dummy ./cybiko-sdl cybiko.img cyos --shot screen.bmp 6
```

`--shot` runs flat out to a mark and writes one frame, which is how the
renderer gets checked without a display.

Typing goes into the key matrix, and stops there. Nothing scans it: the code
that does is `keybd.app`, a module CyOS loads from flash at runtime, and it is
not in the RAM snapshot this recompiles. [docs/KEYBOARD.md](docs/KEYBOARD.md)
has the matrix, and what it would take to close the last link.

## Where the images come from

Nothing here ships one. The boot ROM and flash images are in MAME's `cybikov1`
set (`cyrom112.bin`, `flash_v1246.bin`, and the v2 and Xtreme variants);
applications are `.app` files from the TOSEC collection or the Cybiko Game CD.

## License

MIT. See [LICENSE](LICENSE) — that covers the code in this repository.

It does not and cannot cover any firmware or application you point it at, and
anything the tools produce from those is a derivative of your own dump.

*Cybiko* is a trademark of its respective owner. This project is not affiliated
with or endorsed by them; the name is used only to say which hardware it is.
