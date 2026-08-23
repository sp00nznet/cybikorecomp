# The indirect calls

[&larr; back to the README](../README.md)

---

On the Tamagotchi's 4-bit core every jump target was a build-time constant,
because the machine had nowhere to put a computed address. The H8S is a
register machine and the Cybiko's code is C++, so it is the other extreme.
This is what that actually looks like once measured.

## First: stop analysing halves

CyOS and the boot ROM are separate files but not separate worlds — CyOS calls
down into the boot ROM constantly, for `memcpy` and `memset` among others.
Analysed apart, every such call is a "target outside the image".
`tools/cyimage.py` glues them into one space (`0x000000` boot ROM, `0x200000`
SRAM), and that alone took unresolved transfers from **2,533 to 227**. It also
removed all 12 "undecodable opcodes", which were never decoder gaps — they were
misaligned decodes caused by tracing into a region the other half owned.

What is left is genuinely indirect.

## What defines the target register

Backward-scanning each site's basic block for the last write to the register
it calls through:

| defining instruction | sites | what it is |
|---|---|---|
| `mov.l @(d:16,ERm), ERn` | 178 | a field of a struct — **C++ virtual dispatch** |
| `mov.l @aa:16, ERn` | 43 | a fixed address in on-chip RAM |
| `mov.l @ERm, ERn` | 3 | a pointer |
| `mov.l @aa:24, ERn` | 1 | `0x200004` |
| nothing in the block | 2 | argument, or set further back |

Three different problems, not 227.

## The 43 are one mechanism

They all live in the boot ROM around `0x0016DC`–`0x001710` and load from
`0xFFECAC`, `0xFFECB0`, `0xFFECB4` — consecutive slots of a table in on-chip
RAM. Dumping that region out of MAME shows what it is:

```
FFEC90: 00001618      eleven slots, 0x1A apart
FFEC94: 00001632
...                   each pointing at its own trampoline:
FFECB4: 00001702
                      001702  stm.l (er0-er3), @-sp
                      001706  stm.l (er4-er6), @-sp
                      00170A  mov.l @0xECB4, er2
                      001710  jsr @er2
                      001712  ldm.l @sp+, (er4-er6)
                      001716  ldm.l @sp+, (er0-er3)
                      00171A  rte
```

An eleven-entry **interrupt handler table**, dispatched through trampolines.
Each slot points back at its own trampoline in the dump, which is the
uninstalled default — CyOS fills them in later. So these are not 43 unknowns;
they are one table, and it is readable.

Immediately below it, at `0xFFECC0`, is `77073096 EE0E612C 990951BA ...` — the
standard **CRC-32 table**, which independently confirms that the routine at
`0x002A26` found earlier is the flash driver, and explains its
`and.l #0x3FC` (a 256-entry table indexed by `byte * 4`).

## The 178 dispatch through vtables

C++ virtual calls take their target from a vtable, and a vtable is recognisable
once any code is known: a run of consecutive big-endian u32 that are *all*
addresses of traced instructions. Three in a row is well past coincidence.

`tools/vtables.py` finds **99 tables holding 650 pointers, 641 distinct
targets**, and they cluster in `0x202000`–`0x2034xx` — one contiguous region,
which is what a linker does with them.

```
20249E   28 entries   218F96 218F34 2051BC 21DA86 ...
20291E   17 entries   20A7AA 20A678 20A4D4 20AA2C ...
2029DE   15 entries   20C102 21770A 212F1A 21333C ...
```

It is a fixpoint: new targets reveal code, that code makes more pointers
recognisable. It settles in two rounds and adds ~3 KB of code nothing else
reaches.

## The trap: an unbounded fixpoint reports the whole image as code

The first version of that loop returned **1,073,877 instructions and 2,196,978
bytes** — more than the image contains. One bogus pointer sent the trace into
the `0xFF` fill between the mapped regions, and `0xFF` decodes as a perfectly
valid `mov.b #imm, r7l`, so it never stopped; the garbage then made more
"valid" pointers, and the fixpoint diverged.

The fix is `analyze.CYBIKO_REGIONS`: refuse to follow anything outside
`0x000000`–`0x008000` or `0x200000`–`0x240000`. This is the same failure that
the Tamagotchi's `JPBA` fan-out produced, in a different costume — feed
unproven targets back into a reachability trace and everything becomes code.

## What this means for the emitter

**Indirect calls are not a correctness problem.** The Tamagotchi emitter put a
label on every instruction word and one dense dispatch switch at the bottom, so
a computed transfer could never land somewhere without code. The same
construction works here: emit a label per traced instruction, and `jsr @ERn`
becomes a switch on the register.

The vtable analysis is what makes that dispatch *small* rather than what makes
it *correct* — 641 known targets instead of a switch over every address in the
image. Worth having, not load-bearing.

## Postscript: the slots really are uninstalled

The static reading above -- that each slot points at its own trampoline because
the boot ROM has not filled them in yet -- was confirmed by running it.
`tests/irqprobe.c` dumps the table once the ROM reaches its wait loop:

```
vec  7  slot 0xFFEC0C = 0x0012BE     the trampoline for vector 7
vec 16  slot 0xFFEC10 = 0x0012D8     the trampoline for vector 16
...
25 of 25 slots still hold their own trampoline
```

**The boot ROM never installs an interrupt handler.** CyOS does, later. So
delivering a timer interrupt to make the boot loader's timeout expire does not
work: the trampoline calls its own slot, recurses, and walks the stack pointer
negative. That is not an emulation bug, it is the machine saying the interrupt
should not have been delivered.

Which raises the question the tick counter was hiding. `0x00246E`:

```
002468  stm.l (er4-er5), @-sp
00246C  mov.l er0, er5          the timeout argument
00246E  beq 0x00247A            zero means...
002470  jsr @0x00129E           ...otherwise deadline = now + timeout
00247A  mov.l #0xFFFFFFF0, er4  ...wait forever
```

A zero timeout is a deliberate infinite wait, and the call site the boot
reaches passes zero. The boot loader is sitting in "wait for a host over
serial" -- listening for CyberLoad -- which is a legitimate state and not
something a timer was ever going to end.

Getting past it means one of two things, and they are worth distinguishing
before writing any more code:

1. **Answer it.** Feed the serial handshake CyberLoad would send, so RDRF goes
   true and the loop proceeds.
2. **Take the other branch.** Something upstream chooses between waiting for a
   host and booting from flash. Finding that condition is the more useful
   result, because booting from flash is what a Cybiko does when nothing is
   plugged into it.
