# The keyboard

72 keys in a 9 × 8 matrix. The matrix is implemented and a frontend can type
into it. **Nothing reads it yet**, and the reason is not that the hardware is
hard — it is that the code which scans it is not in the image.

---

## The matrix

Nine columns of eight rows. This is not inferred from the firmware; it is
read straight out of MAME's driver, which declares nine ports `A.0`–`A.8`
whose fields carry the bit mask of each key:

| bit | col 0 | col 1 | col 2 | col 3 | col 4 | col 5 | col 6 | col 7 | col 8 |
|---|---|---|---|---|---|---|---|---|---|
| 0 | F7 | F6 | F5 | F4 | Right | F2 | F1 | `-` | `'` |
| 1 | Esc | Up | F3 | 1 | Down | `;` | `/` | `.` | `=` |
| 2 | Del | Ins | Space | Tab | Select | Enter | BkSp | 0 | 9 |
| 3 | Left | 2 | 3 | 4 | 5 | 6 | 7 | 8 | P |
| 4 | Q | W | E | R | T | Y | U | I | O |
| 5 | A | S | D | F | G | H | J | K | L |
| 6 | `` ` `` | Z | X | C | V | B | N | M | `,` |
| 7 | Shift | Fn | Help | `[` | `]` | `\` | — | — | — |

Rows 4, 5 and 6 are QWERTY, ASDF and ZXCV read across the columns, which is
the arrangement you would expect and a useful check that the table is the
right way round.

`src/keyboard.c` holds one byte per column. `cy_key_rows` takes a column
*select mask* rather than a column number, because a matrix does not care how
many lines are driven at once — two columns selected together read as the
union of their rows, which is how ghosting happens on real hardware.

## Why nothing reads it

CyOS does not scan the keyboard. Not "we have not found the scan yet": the
resident image contains no read of a port input register at all. Every
absolute reference to `0xFFFF70`–`0xFFFF77` in the traced image is in the boot
ROM, and the boot ROM only touches them while configuring the pins.

The scan is in **`keybd.app`**, a module CyOS loads from flash at runtime. The
name is in the image — `keybd.app int_113.kbd` — and the file is in the flash
at offset `0x05070F`, alongside the keymaps `default.kbd`, `int_108.kbd` and
`int_113.kbd`. It is not resident in the RAM snapshot this project
recompiles: code lives at `0x203000`–`0x21F000` (CyOS) and `0x232000`–
`0x234000` (the flash filesystem repair module), and neither references a
port.

That is a wall a static recompiler runs into eventually, and it is the same
wall in a new place. Code that arrives at runtime cannot be translated ahead
of time — the answer for CyOS was to take the plaintext out of a running
MAME rather than solve the packer, and the answer here is the same: a RAM
dump taken after `keybd.app` has loaded. Then the scan is ordinary traced
code, it says which port drives the columns and which reads the rows, and
the hardware side is a dozen lines in `src/io.c`.

## What was measured, and what refused to be

Worth recording, because two of these look like results and are not.

**The port block is not where the manual index suggests.** The boot ROM
settles it at `0x000DFC`–`0x000E52`: it writes direction registers at
`0xFFFEB0`–`0xFFFEBF` and the matching data registers at `0xFFFF60`–`0xFFFF6F`
— the same value to `0xFFFEB1` and `0xFFFF61`, then to `0xFFFEB2` and
`0xFFFF62` — which puts the read-only PORT inputs at `0xFFFF70`–`0xFFFF77`.
An earlier probe swept `0xFFFFC0`–`0xFFFFFF` and found nothing, because
nothing is there.

**`0xFFFFF5` looked like it answered to a key. It does not.** Holding a key
and re-reading it gave `0xC0` → `0xD3`, which is exactly what a row register
should look like. Every key gave the same `0xD3`, and the value came back to
`0xC0` with the key still held: it was a register changing with time, sampled
one frame apart, and the key had nothing to do with it. A one-frame-apart
comparison is not a controlled experiment.

**MAME will not show the wiring while nothing scans it.** MAME's driver
answers the keyboard through a port read callback, so with no read there is
no evaluation and no observable difference — a tap over the whole address
space, with a key held for thirty seconds of emulated time, reports zero
differences outside RAM. Driving the ports by hand from Lua does not help
either: the pins are inputs until a direction register says otherwise, and
setting all of them at once is not a column select.

**MAME will not boot CyOS here.** Ten minutes of emulated time on the stock
flash leaves SRAM 14.7% non-zero with no CyOS code in it, against 31% in the
dump this project uses. Whatever produced that dump took a different route,
and finding it again is the next step for the keyboard.
