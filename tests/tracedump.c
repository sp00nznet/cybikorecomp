/* Dump the recompiled core's per-instruction state, to diff against MAME.
 *
 * Build with -DCY_TRACING so the generated trace hook is live:
 *
 *   tracedump <cybiko.img> <count> <out.bin>
 *
 * Record format matches tools/mame_difftrace.lua exactly -- 40 big-endian
 * bytes per instruction: pc, ER0..ER7, CCR. Big-endian rather than native
 * because that is what the Lua side can write without effort, and a format
 * mismatch between the two halves of a differential test is a bug that looks
 * exactly like a CPU divergence.
 */
#define _CRT_SECURE_NO_WARNINGS

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cybikorecomp/h8s.h"

#define REC 40

static unsigned char *buf;
static long cap, n;

static void put_be32(unsigned char *p, uint32_t v)
{
    p[0] = (unsigned char)(v >> 24);
    p[1] = (unsigned char)(v >> 16);
    p[2] = (unsigned char)(v >> 8);
    p[3] = (unsigned char)v;
}

void cy_trace_hook(const cy_t *c, uint32_t addr)
{
    if (n >= cap)
        return;
    unsigned char *p = buf + n * REC;
    put_be32(p, addr);
    for (int i = 0; i < 8; i++)
        put_be32(p + 4 + 4 * i, c->e[i]);
    put_be32(p + 36, CY_CCR_GET(c));
    n++;
}

int main(int argc, char **argv)
{
    if (argc < 4) {
        fprintf(stderr, "usage: tracedump <cybiko.img> <count> <out.bin>\n");
        return 2;
    }
    cap = strtol(argv[2], NULL, 0);
    buf = (unsigned char *)malloc((size_t)cap * REC);

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

    /* The budget counts dispatches, not instructions, so give it plenty and
     * let the trace buffer be what stops us. */
    while (n < cap && !c.trapped)
        cy_run(&c, c.cycles + 100000);

    f = fopen(argv[3], "wb");
    if (!f)
        return 2;
    fwrite(buf, REC, (size_t)n, f);
    fclose(f);
    fprintf(stderr, "traced %ld instructions%s\n", n,
            c.trapped == 2 ? " (unimplemented)" :
            c.trapped ? " (trapped)" : "");
    return 0;
}
