# The peripherals CyOS boots through

Recompiled code is only half a machine. CyOS gets four instructions into its
own startup and then waits on hardware, so every peripheral below is here
because a run stopped dead without it — not because a datasheet listed it.

The method throughout: run, watch what it polls, read the code around the
poll, implement exactly that. `tests/ioprobe.c` counts reads and writes per
address, which turns "it hangs" into "it read 0xFFFF5E 4,964,191 times".

---

## The serial flash — `src/flash.c`

**Symptom.** `Initializing flash device...` on the debug serial, then
4.96 million reads of `0xFFFF5E`.

The code around the poll configures SCI1 for synchronous mode
(`SMR1 = 0x80`, `SCR1 = 0x30`), asserts a chip select with
`or.b #0x10, @0xFFFF62`, waits for bit 2 of `0xFFFF5E`, and clocks out `0x57`.
`0x57` is an AT45DB main-memory page read, so SCI1 is SPI and the chip on the
other end is the **AT45DB041**.

The geometry is the interesting part, and the reason a flash dump is 540,672
bytes rather than a round 512K: **pages are 264 bytes, not 256**. An address
splits into 11 bits of page and 9 of offset, so the byte at page *P* offset
*B* lives at `P*264 + B`. Treating the address as flat lands in the wrong
place by a margin that grows with the page number, which is the kind of bug
that looks like data corruption rather than an addressing error.

Commands implemented: `0x52`/`0x68` continuous read, `0xD2`/`0x57` page read,
`0xD7` status. Writes are not — nothing on the boot path needs them.

## The 8-bit timer — `src/io.c`

**Symptom.** Past the flash, 20 million reads of `0xFFFFB3`.

`0xFFFFB0` is the H8S 8-bit timer register file, two channels interleaved:

| | ch 0 | ch 1 | |
|---|---|---|---|
| TCR | B0 | B1 | bit 5 enables the overflow interrupt |
| TCSR | B2 | B3 | bit 5 is the overflow flag |
| TCNT | B8 | B9 | the counter |

Nothing writes the compare registers, so both channels are used purely for
overflow — and a delay is therefore written as a **negative preload**:

```
214336  not.b  r0l                  ; delay of n ticks becomes ~n
214338  mov.b  r0l, @0xFFFFB9       ; TCNT1
21433A  bclr   #5, @0xFFFFB3        ; clear OVF1
214342  mov.b  @0xFFFFB3, r2l       ; and wait for it
214344  btst   #5, r2l
214346  beq    0x214342
```

Channel 0 is the system tick: the handler reloads `0xF2` — 14 counts — and
increments a counter at `0x21F080` that `0x20743E` multiplies by 10 to get
milliseconds. So one tick is 10 ms, and the interrupt is **vector 66**,
through the boot ROM trampoline at `0x00157C` that calls whatever is in
`0xFFEC78`.

The counter is derived from the instruction count rather than stepped:
`value = preload + elapsed / TMR_DIV`. `TMR_DIV` is the one number here that
is a guess and the one knob worth turning — it is what ties guest time to how
fast this actually runs.

### Where an interrupt gets delivered

`cy_run` polls before every dispatch, but a spin loop inside one chunk never
re-dispatches. So the generated code also tests `CY_IRQ_DUE` on every backward
branch — the same edge that already carries the budget check, since every loop
has one. The test is a compare against a precomputed deadline, so it costs
nothing to sit there.

## The LCD — `src/lcd.c`

An **HD66421**: 160×100 dots, two bits per dot, four grey levels, 40 bytes to
a row. It is not an on-chip peripheral, which is why an I/O register sweep
never saw it — it sits on the external bus behind an index port at `0x600000`
and a data port at `0x600001`.

```
@0x600000 = 2   @0x600001 = x        column, 0..39
@0x600000 = 3   @0x600001 = y        row, 0..99
@0x600000 = 4   @0x600001 = <byte>   four dots, column auto-increments
```

CyOS's blit at `0x206F72` walks rows from `0x63` downwards writing 40 bytes
each; the boot ROM clears the panel the same way at `0x004A82`. Everything
else the controller can do — contrast, bias, the charge pump — is stored and
read back, because nothing on the display path depends on it.

`tests/lcdprobe.c` prints the panel as characters. Booting CyOS puts a four
level grey ramp on it, `FF AA 55 00` repeated, identical on all 100 rows.

## Still unidentified

**SCI0**, at `0xFFFF78`. CyOS configures it (`BRR0 = 6`, `SCR0 = 0x70`) and
sends exactly six bytes — `01 02 02 01 03 00` — with a chip select on bit 6
of `0xFFFF61` around them. The runtime reports the transmitter permanently
free and keeps the bytes in `cy_t.sci0` so the protocol can be read back; it
is not the LCD and not the flash, both of which are accounted for elsewhere.

**`0xE00000`**, referenced once from `0x217D82`.

**The keyboard**, which is what the machine is waiting on now.
