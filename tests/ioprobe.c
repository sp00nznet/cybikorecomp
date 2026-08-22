/* Which I/O registers does the recompiled boot ROM actually touch?
 *
 * Link this instead of src/mem.c. It provides the same accessors with counting
 * on top, so a run reports exactly which addresses matter -- which is a much
 * better way to decide what to implement than reading a datasheet and guessing
 * at what a 2000 handheld's boot code cares about.
 *
 *   ioprobe <cybiko.img> [dispatches]
 */
#define _CRT_SECURE_NO_WARNINGS

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cybikorecomp/h8s.h"

/* On-chip RAM starts at 0xFFEC00 and the I/O block at 0xFFFE00, but the
 * boot ROM also reaches high addresses through @aa:16 sign extension, so
 * watch everything above on-chip RAM. */
#define IO_LO 0xFFE000
#define IO_HI 0xFFFFFF
#define IO_N  (IO_HI - IO_LO + 1)

static uint32_t *rd_count, *wr_count;
static uint32_t *last_written;

static void note_read(uint32_t a)
{
    if (a >= IO_LO && a <= IO_HI)
        rd_count[a - IO_LO]++;
}

static void note_write(uint32_t a, uint32_t v)
{
    if (a >= IO_LO && a <= IO_HI) {
        wr_count[a - IO_LO]++;
        last_written[a - IO_LO] = v;
    }
}

int cy_init(cy_t *c)
{
    memset(c, 0, sizeof(*c));
    c->mem = (uint8_t *)calloc(CY_MEM_SIZE, 1);
    rd_count = (uint32_t *)calloc(IO_N, sizeof(uint32_t));
    wr_count = (uint32_t *)calloc(IO_N, sizeof(uint32_t));
    last_written = (uint32_t *)calloc(IO_N, sizeof(uint32_t));
    return (c->mem && rd_count && wr_count && last_written) ? 0 : -1;
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
    a &= CY_ADDR_MASK; note_read(a);
    return c->mem[a];
}
uint16_t cy_read16(cy_t *c, uint32_t a)
{
    a &= CY_ADDR_MASK; note_read(a);
    return (uint16_t)((c->mem[a] << 8) | c->mem[(a + 1) & CY_ADDR_MASK]);
}
uint32_t cy_read32(cy_t *c, uint32_t a)
{
    a &= CY_ADDR_MASK; note_read(a);
    return ((uint32_t)c->mem[a] << 24)
         | ((uint32_t)c->mem[(a + 1) & CY_ADDR_MASK] << 16)
         | ((uint32_t)c->mem[(a + 2) & CY_ADDR_MASK] << 8)
         |  (uint32_t)c->mem[(a + 3) & CY_ADDR_MASK];
}
void cy_write8(cy_t *c, uint32_t a, uint8_t v)
{
    a &= CY_ADDR_MASK; note_write(a, v);
    c->mem[a] = v;
}
void cy_write16(cy_t *c, uint32_t a, uint16_t v)
{
    a &= CY_ADDR_MASK; note_write(a, v);
    c->mem[a] = (uint8_t)(v >> 8);
    c->mem[(a + 1) & CY_ADDR_MASK] = (uint8_t)v;
}
void cy_write32(cy_t *c, uint32_t a, uint32_t v)
{
    a &= CY_ADDR_MASK; note_write(a, v);
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

/* Names for the H8S/2246 on-chip peripherals the Cybiko leans on. */
static const char *io_name(uint32_t a)
{
    switch (a) {
    case 0xFFFF3C: return "WDT   watchdog";
    case 0xFFFEB0: case 0xFFFEB1: return "P1DDR/P1DR  port 1";
    case 0xFFFEB2: case 0xFFFEB3: return "P2DDR/P2DR  port 2";
    case 0xFFFF60: return "TSTR  timer start";
    case 0xFFFF61: return "TSNC  timer sync";
    case 0xFFFF64: case 0xFFFF65: return "TCR   timer control";
    case 0xFFFFB0: return "SMR   serial mode";
    case 0xFFFFB1: return "BRR   serial baud";
    case 0xFFFFB2: return "SCR   serial control";
    case 0xFFFFB3: return "TDR   serial transmit";
    case 0xFFFFB4: return "SSR   serial status";
    case 0xFFFFB5: return "RDR   serial receive";
    case 0xFFFFB8: return "SMR1  serial 1 mode";
    case 0xFFFFBC: return "SSR1  serial 1 status";
    default:       return "";
    }
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: ioprobe <cybiko.img> [dispatches]\n");
        return 2;
    }
    uint64_t budget = (argc > 2) ? strtoull(argv[2], NULL, 0) : 500000;

    FILE *f = fopen(argv[1], "rb");
    if (!f)
        return 2;
    static uint8_t img[CY_MEM_SIZE];
    size_t n = fread(img, 1, CY_MEM_SIZE, f);
    fclose(f);

    cy_t c;
    if (cy_init(&c) != 0)
        return 2;
    cy_load(&c, 0, img, (uint32_t)n);
    c.pc = cy_read32(&c, 0) & CY_ADDR_MASK;
    c.e[7] = 0x23FF00;

    cy_run(&c, budget);

    printf("after %llu dispatches, pc=0x%06X%s\n\n",
           (unsigned long long)c.cycles, c.pc,
           c.trapped == 2 ? "  (unimplemented opcode)" :
           c.trapped ? "  (left the image)" : "");

    printf("%-9s %10s %10s  %-10s %s\n",
           "addr", "reads", "writes", "last write", "register");
    int touched = 0;
    for (uint32_t i = 0; i < IO_N; i++) {
        if (!rd_count[i] && !wr_count[i])
            continue;
        touched++;
        uint32_t a = IO_LO + i;
        printf("0x%06X %10u %10u  0x%08X  %s\n",
               a, rd_count[i], wr_count[i], last_written[i], io_name(a));
    }
    printf("\n%d addresses touched above 0x%06X\n", touched, IO_LO);
    return 0;
}
