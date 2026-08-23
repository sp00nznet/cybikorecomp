/* Record every byte the recompiled core writes, to diff against MAME.
 *
 * Links in place of src/mem.c and provides the same accessors with logging.
 * Every store is decomposed to single bytes, most significant first, matching
 * tools/mame_writetrace.lua -- the CPU's wider stores reach a real bus as
 * narrower accesses, so byte granularity is the only width both sides can
 * agree on.
 *
 *   writedump <cybiko.img> <count> <out.bin>
 */
#define _CRT_SECURE_NO_WARNINGS

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cybikorecomp/h8s.h"

#define REC 8

static unsigned char *buf;
static uint32_t *wpc;        /* the PC each write came from, for diagnosis */
static uint32_t cur_pc;
static long cap, n;

static void put_be32(unsigned char *p, uint32_t v)
{
    p[0] = (unsigned char)(v >> 24);
    p[1] = (unsigned char)(v >> 16);
    p[2] = (unsigned char)(v >> 8);
    p[3] = (unsigned char)v;
}

static void logw(uint32_t a, uint8_t v)
{
    if (n >= cap)
        return;
    unsigned char *p = buf + n * REC;
    put_be32(p, a);
    put_be32(p + 4, v);
    wpc[n] = cur_pc;
    n++;
}

/* The generated code calls this at every instruction when built with
 * -DCY_TRACING, which is how a diverging write can name the instruction that
 * made it instead of leaving it to be found by hand. */
#define RING 32
static uint32_t ring[RING];
static uint64_t ring_n;

void cy_trace_hook(const cy_t *c, uint32_t addr)
{
    (void)c;
    cur_pc = addr;
    ring[ring_n++ % RING] = addr;
}

int cy_init(cy_t *c)
{
    memset(c, 0, sizeof(*c));
    c->mem = (uint8_t *)calloc(CY_MEM_SIZE, 1);
    return c->mem ? 0 : -1;
}
void cy_free(cy_t *c) { free(c->mem); c->mem = NULL; }

int cy_load(cy_t *c, uint32_t addr, const void *data, uint32_t len)
{
    if ((uint64_t)addr + len > CY_MEM_SIZE)
        return -1;
    memcpy(c->mem + addr, data, len);
    return 0;
}

uint8_t cy_read8(cy_t *c, uint32_t a)
{
    uint8_t v;
    a &= CY_ADDR_MASK;
    if (cy_io_read(c, a, &v))
        return v;
    return c->mem[a];
}
uint16_t cy_read16(cy_t *c, uint32_t a)
{
    a &= CY_ADDR_MASK;
    return (uint16_t)((c->mem[a] << 8) | c->mem[(a + 1) & CY_ADDR_MASK]);
}
uint32_t cy_read32(cy_t *c, uint32_t a)
{
    a &= CY_ADDR_MASK;
    return ((uint32_t)c->mem[a] << 24)
         | ((uint32_t)c->mem[(a + 1) & CY_ADDR_MASK] << 16)
         | ((uint32_t)c->mem[(a + 2) & CY_ADDR_MASK] << 8)
         |  (uint32_t)c->mem[(a + 3) & CY_ADDR_MASK];
}

void cy_write8(cy_t *c, uint32_t a, uint8_t v)
{
    a &= CY_ADDR_MASK;
    logw(a, v);
    if (cy_io_write(c, a, v))
        return;
    c->mem[a] = v;
}
void cy_write16(cy_t *c, uint32_t a, uint16_t v)
{
    a &= CY_ADDR_MASK;
    logw(a, (uint8_t)(v >> 8));
    logw((a + 1) & CY_ADDR_MASK, (uint8_t)v);
    c->mem[a] = (uint8_t)(v >> 8);
    c->mem[(a + 1) & CY_ADDR_MASK] = (uint8_t)v;
}
void cy_write32(cy_t *c, uint32_t a, uint32_t v)
{
    a &= CY_ADDR_MASK;
    for (int k = 0; k < 4; k++)
        logw((a + k) & CY_ADDR_MASK, (uint8_t)(v >> (24 - 8 * k)));
    c->mem[a] = (uint8_t)(v >> 24);
    c->mem[(a + 1) & CY_ADDR_MASK] = (uint8_t)(v >> 16);
    c->mem[(a + 2) & CY_ADDR_MASK] = (uint8_t)(v >> 8);
    c->mem[(a + 3) & CY_ADDR_MASK] = (uint8_t)v;
}

int cy_cond(const cy_t *c, int cc)
{
    switch (cc & 0xF) {
    case 0x0: return 1;
    case 0x1: return 0;
    case 0x2: return !(c->cf | c->zf);
    case 0x3: return  (c->cf | c->zf);
    case 0x4: return !c->cf;
    case 0x5: return  c->cf;
    case 0x6: return !c->zf;
    case 0x7: return  c->zf;
    case 0x8: return !c->vf;
    case 0x9: return  c->vf;
    case 0xA: return !c->nf;
    case 0xB: return  c->nf;
    case 0xC: return !(c->nf ^ c->vf);
    case 0xD: return  (c->nf ^ c->vf);
    case 0xE: return !((c->nf ^ c->vf) | c->zf);
    default:  return  ((c->nf ^ c->vf) | c->zf);
    }
}

int main(int argc, char **argv)
{
    if (argc < 4) {
        fprintf(stderr, "usage: writedump <cybiko.img> <count> <out.bin>\n");
        return 2;
    }
    cap = strtol(argv[2], NULL, 0);
    buf = (unsigned char *)malloc((size_t)cap * REC);
    wpc = (uint32_t *)calloc((size_t)cap, sizeof(uint32_t));

    FILE *f = fopen(argv[1], "rb");
    if (!f || !buf)
        return 2;
    static uint8_t img[CY_MEM_SIZE];
    size_t len = fread(img, 1, CY_MEM_SIZE, f);
    fclose(f);

    cy_t c;
    if (cy_init(&c) != 0)
        return 2;
    cy_load(&c, 0, img, (uint32_t)len);
    c.pc = cy_read32(&c, 0) & CY_ADDR_MASK;
    c.e[7] = 0x23FF00;

    while (n < cap && !c.trapped)
        cy_run(&c, c.cycles + 100000);

    f = fopen(argv[3], "wb");
    if (!f)
        return 2;
    fwrite(buf, REC, (size_t)n, f);
    fclose(f);

    if (argc > 4) {                 /* optional: the PC behind each write */
        f = fopen(argv[4], "wb");
        if (f) {
            for (long k = 0; k < n; k++) {
                unsigned char p[4];
                put_be32(p, wpc[k]);
                fwrite(p, 1, 4, f);
            }
            fclose(f);
        }
    }
    if (c.trapped) {
        fprintf(stderr, "last %d instructions before the trap:\n ", RING);
        uint64_t first = ring_n > RING ? ring_n - RING : 0;
        for (uint64_t k = first; k < ring_n; k++)
            fprintf(stderr, " %06X", ring[k % RING]);
        fprintf(stderr, "\n");
    }
    fprintf(stderr, "logged %ld byte-writes%s (pc=0x%06X)\n", n,
            c.trapped == 2 ? " (unimplemented)" : c.trapped ? " (trapped)" : "",
            c.trapped ? c.trap_pc : c.pc);
    return 0;
}
