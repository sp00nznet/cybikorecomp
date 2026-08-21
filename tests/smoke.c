/* Does the recompiled image execute?
 *
 * There are no peripherals yet, so it cannot get far -- the first thing it
 * waits on will never answer. What this checks is the part that would be
 * broken if the emitter were wrong: that control flow stays inside the traced
 * image. A bad jump, a mangled stack or a miscomputed indirect target shows up
 * immediately, because the dispatch only knows addresses that were traced and
 * refuses anything else.
 *
 *   smoke <cybiko.img> [instructions]
 */
#define _CRT_SECURE_NO_WARNINGS

#include <stdio.h>
#include <stdlib.h>

#include "cybikorecomp/h8s.h"

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: smoke <cybiko.img> [instructions]\n");
        return 2;
    }
    uint64_t budget = (argc > 2) ? strtoull(argv[2], NULL, 0) : 1000000;

    FILE *f = fopen(argv[1], "rb");
    if (!f) {
        fprintf(stderr, "cannot open %s\n", argv[1]);
        return 2;
    }
    static uint8_t img[CY_MEM_SIZE];
    size_t n = fread(img, 1, CY_MEM_SIZE, f);
    fclose(f);

    cy_t c;
    if (cy_init(&c) != 0)
        return 2;
    cy_load(&c, 0, img, (uint32_t)n);

    /* Reset vector, and a stack somewhere sane until the ROM sets its own. */
    c.pc = cy_read32(&c, 0) & CY_ADDR_MASK;
    c.e[7] = 0x23FF00;
    printf("image %s: %zu bytes, reset vector 0x%06X\n", argv[1], n, c.pc);

    cy_run(&c, budget);

    printf("stopped after %llu steps at pc=0x%06X\n",
           (unsigned long long)c.cycles, c.pc);
    printf("  ER0=%08X ER1=%08X ER2=%08X ER3=%08X\n",
           c.e[0], c.e[1], c.e[2], c.e[3]);
    printf("  ER4=%08X ER5=%08X ER6=%08X SP =%08X\n",
           c.e[4], c.e[5], c.e[6], c.e[7]);
    printf("  N=%d Z=%d V=%d C=%d\n", c.nf, c.zf, c.vf, c.cf);

    if (c.trapped == 2) {
        printf("UNIMPLEMENTED opcode at 0x%06X -- that is the next one to add\n",
               c.trap_pc);
        return 0;
    }
    if (c.trapped) {
        printf("FAIL: left the traced image, wanted 0x%06X\n", c.trap_pc);
        return 1;
    }
    if (c.cycles < budget) {
        printf("FAIL: stopped early without trapping\n");
        return 1;
    }
    printf("ok: ran the whole budget inside the image\n");
    cy_free(&c);
    return 0;
}
