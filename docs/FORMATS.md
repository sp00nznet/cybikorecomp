# Cybiko file formats

[&larr; back to the README](../README.md)

---

## The `.app` container

Solved; `tools/cyapp.py` implements it and all 410 applications in the TOSEC
set parse.

```
offset  size    field
0       2       "Cy"
2       2       entry count
4       2       end of the name table
6       10*n    entries: u16 name_offset, u32 data_offset, u32 length
...             NUL-terminated names, at the offsets above
...             member data
```

The layout is dense: every byte after the header belongs to exactly one member
and the last ends at EOF. `cyapp.parse` asserts that, which is the cheapest
available check that the header was read correctly.

Member names are conventional rather than fixed. Across 410 applications:

| name | seen in | what it is |
|---|---|---|
| `root.inf` | 411 | application metadata |
| `root.ico` | 410 | icon |
| `main.e` | 410 | **the H8S executable** |
| `root.spl` | 406 | splash / sound |
| `0.help` | 385 | help text |
| `intro.pic` | 308 | title image |
| `score.inf` | 159 | high score table |

## Member compression — unsolved

Every member begins with a method byte.

**`0x00` — stored.** The rest of the member is the data. 2,373 of 11,011
members. `root.spl` is usually stored and begins with readable text, which is
how the method byte was identified in the first place.

**`0x02` — packed.** Followed by a big-endian u32 of the unpacked size, then
the stream. 8,638 members, averaging **2.21×**.

```
main.e from Calculator v1.12:
  02 00 00 1a fa | 12 d5 03 ...
  ^  ^^^^^^^^^^^   packed stream (4243 bytes -> 6906)
  |  unpacked size = 0x1AFA
  method
```

What is known:

- It is not zlib, gzip or bzip2 — no recognisable header, and the first
  stream byte varies freely across members.
- It packs small incompressible members to *slightly larger* than the input
  (`calc.pic`, 20 bytes in, 21 out), which is the behaviour of a byte-oriented
  LZ with literal runs rather than an entropy coder.
- The ratio on `main.e` members is consistently near 1.6×, and on text members
  near 3×, which is in the range of LZSS-family codecs.

Until it is identified, `main.e` cannot be lifted out of a `.app`. The two ways
forward:

1. **Find the unpacker in the firmware.** CyOS has to decompress these at load
   time, so the routine is in `flash_v1246.bin`. This is the reason the boot
   ROM and flash are worth disassembling first regardless.
2. **Recompile the firmware instead.** If CyOS itself is recompiled, it
   unpacks its own applications exactly as the hardware does and the codec
   never has to be understood at all — the same trick that made the Tamagotchi
   ROM's data encoding a non-problem.

The second is more in keeping with how this library usually works.

---

## The flash image

`flash_v1246.bin` is 540,672 bytes — 2048 pages of 264, an AT45DB041 serial
flash dump. It is **not a monolithic OS image**. It is a filesystem holding the
same `Cy` containers a `.app` uses: 38 magic hits, **34 of which parse in
place** with sensible member names (`0.help`, `root.ico`, `root.inf`,
`main.e`). CyOS ships its own applications the same way third-party ones ship.

Consequences:

- There is no contiguous "CyOS code" to point a recompiler at. There are dozens
  of containers, and their code members are packed.
- A code-likelihood sweep over the whole flash finds no uncompressed code. The
  one region that scored high, `0x081000`, is a **string table** — ASCII bytes
  decoding as plausible opcodes. Worth naming as a trap: any "is this code?"
  heuristic will rank text highly unless text is excluded first.

## Method `0x02` is real compression

Worth ruling out the cheaper explanation first: `0x02` could have been an
*executable* header, with the u32 being a memory-image size including BSS
rather than an unpacked size, and the payload being raw code. It is not.

Scoring payloads by how often a linear decode produces function-shaped
instructions:

| region | score |
|---|---|
| known H8S code (boot ROM `0x0D6A`–`0x2000`) | 0.466 |
| known data (boot ROM `0x5E00`–`0x6000`) | 0.021 |
| `main.e` payloads, median over 40 apps | **0.024** |

`main.e` payloads are statistically indistinguishable from data. The codec is
real and has to be understood or executed.

## Hunting the decompressor

Not found yet, and the boot ROM has been searched two ways.

A survey of *reached* functions found nothing shift-heavy enough — but that
only covers 34.5% of the image, so it proves little. A sliding-window scan over
a linear decode of the whole 25 KB ranked six candidates by shift density, back
edges and absence of calls.

The best of them, `0x002A26`, turned out to be the **flash driver**, not a
decompressor:

```
002A28  and.l #0x000003FC, er2      ; (byte ^ crc) & 0xFF, times 4
002A2E  mov.l @er4, er3             ; table lookup
002A32  shlr x4                     ; CRC-32, table-driven
002A56  bne 0x002A16
002A8A  or.l #0x82000000, er5       ; AT45DB opcode 0x82
002A96  mov.b @0x5E, r2l            ; poll SPI status
002A9A  beq 0x002A96
```

That is a table-driven CRC-32 feeding a page-program command. Useful to have
identified — it is how the boot ROM writes flash — but the unpacker is
elsewhere.

### Found: it is LZSS, at `0x0038B2`

The first of the two remaining options was "watch it happen", and that is what
did it — though not under MAME. Once the recompiled boot ROM had a working
flash to read, it loaded CyOS and narrated the whole thing:

```
Got header: magic 1C0FFAB (valid) LZSS compressed image
boot header size 12
Compressed size 72510 decompressed size 128260
decompressing...
```

The decompressor is `0x0038B2`-`0x003996`, and the search above had it
surrounded without ever landing on it: it is not shift-heavy, because the
match copy is a plain byte loop at `0x00396E` and the flag bits come out
through the 32-bit logic ops the decoder was misreading as `TAS`. Fixing that
one instruction is what made the decompression correct — see
[LOADER.md](LOADER.md).

So `0x02` inside a `.app` is LZSS, with a reference implementation in the boot
ROM and a running one to check any port of it against. `main.e` extraction is
no longer blocked on identifying a codec, only on writing it.
