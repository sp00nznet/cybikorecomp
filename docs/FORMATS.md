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
