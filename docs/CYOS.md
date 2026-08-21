# Getting at CyOS

[&larr; back to the README](../README.md)

---

## The problem

CyOS is not a monolithic image sitting in the flash waiting to be recompiled.
`flash_v1246.bin` is a filesystem of `Cy` containers, and their code members are
packed with a codec nobody has identified. Reading the boot ROM for the
unpacker did not find it, and 65% of that ROM is behind indirect calls anyway.

## The answer: take the plaintext, not the codec

CyOS decompresses itself every time the machine boots. Rather than work out how,
run the machine and take the result.

MAME emulates `cybikov1` accurately enough to boot it, and its Lua interface can
read the address space. `tools/mame_dump.lua` waits for the run to end and
writes the whole 256 KB SRAM to a file:

```sh
mame cybikov1 -video none -sound none -seconds_to_run 30 -nothrottle \
     -autoboot_script tools/mame_dump.lua
```

Thirty emulated seconds is enough, and runs at about 4x real time.

The dump is CyOS, unpacked, at its real load address of `0x200000`:

```
code-likelihood across RAM, 8KB blocks
   200000  0.019
   202000  0.117  ######
   204000  0.480  ############################
   208000  0.526  ###############################
   218000  0.606  ####################################
   21C000  0.495  #############################
   21E000  0.151  #########
   222000  0.000
```

For reference the boot ROM -- known-good H8S code -- scores 0.466, and known
data scores 0.021. So `0x202000`-`0x220000` is roughly 120 KB of genuine code.

**And none of it appears in the flash verbatim.** Sampling 32-byte windows from
the three highest-scoring blocks and searching the whole flash image finds no
match for any of them. That is the proof that it arrives unpacked, and it means
the dump is a plaintext whose packed source is somewhere in the flash -- useful
later for identifying the codec, and not needed at all before then.

## Entry points

A RAM dump has no vector table and no symbols. The compiler supplies the entry
points anyway, because it opens nearly every non-leaf function by saving
registers:

```
01 n0 6D Fm      stm.l (ERm-ERm+n), @-sp
```

Seeding the trace with all 1,145 of those and letting it discover the rest
through direct calls:

```
$ python tools/analyze.py cyram.bin --base 0x200000 --prologues
seeded with     1145 function prologues
entry points    1900 (801 of them call targets)
instructions    35040
bytes reached   110548   (87.4% of the 0x202000-0x220000 code extent)

unresolved      2533
  target outside the image   2337
  indirect jsr                179
  undecodable opcode           12
  indirect jmp                  5
```

**87.4% of the code extent, from a dump and one heuristic.** The 2,337
"outside the image" are calls down into the boot ROM at `0x000000`, which is
simply not part of a RAM dump; combining the two into one address space
removes them. What is left is 179 indirect calls and 5 indirect jumps, which
is the real remaining work, plus 12 undecodable opcodes to chase.

## What this does not solve

The `0x02` codec is still unidentified, and third-party `.app` files still
cannot be unpacked without it. But CyOS itself no longer needs it — the same
way the Tamagotchi's data encoding stopped mattering once its ROM was being
executed rather than parsed.

The dump also gives a way to attack the codec later on much better terms: a
known plaintext, with its packed source in the flash to match it against.
