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

    /* Optional periodic interrupt. The boot ROM's timeout loops wait on a
     * counter that only an interrupt handler advances, so without one they
     * wait forever -- correctly, since on real hardware a timer is ticking. */
    int vec = (argc > 3) ? atoi(argv[3]) : 0;
    uint64_t period = (argc > 4) ? strtoull(argv[4], NULL, 0) : 2000;
    if (vec) {
        while (c.cycles < budget && !c.trapped) {
            cy_run(&c, c.cycles + period);
            /* Only when the ROM has unmasked interrupts. It boots with
             * `orc #0x80, ccr` and clears the I bit once its handler table is
             * installed -- delivering before that vectors through an empty
             * slot straight to address zero. */
            if (!c.trapped && !c.iff)
                cy_interrupt(&c, vec);
        }
    } else {
        cy_run(&c, budget);
    }

    printf("stopped after %llu steps at pc=0x%06X\n",
           (unsigned long long)c.cycles, c.pc);
    printf("  ER0=%08X ER1=%08X ER2=%08X ER3=%08X\n",
           c.e[0], c.e[1], c.e[2], c.e[3]);
    printf("  ER4=%08X ER5=%08X ER6=%08X SP =%08X\n",
           c.e[4], c.e[5], c.e[6], c.e[7]);
    printf("  N=%d Z=%d V=%d C=%d\n", c.nf, c.zf, c.vf, c.cf);

    /* Walk the guest stack for return addresses. Nothing else says how the
     * ROM got where it is: a JSR pushes the address after itself, so a value
     * on the stack that points just past a call site names the caller. */
    printf("\ncall chain from the stack:\n");
    for (uint32_t k = 0, shown = 0; k < 64 && shown < 10; k++) {
        uint32_t sp = c.e[7] + 4 * k;
        uint32_t v = cy_read32(&c, sp) & CY_ADDR_MASK;
        if (v < 4 || v >= 0x8000 || (v & 1))
            continue;                     /* not a boot-ROM return address */
        uint8_t p0 = cy_read8(&c, v - 4), p2 = cy_read8(&c, v - 2);
        const char *how = (p0 == 0x5E) ? "jsr @aa:24"
                        : (p0 == 0x5C) ? "bsr d:16"
                        : (p2 == 0x5D) ? "jsr @ERn"
                        : (p2 == 0x55) ? "bsr d:8" : NULL;
        if (!how)
            continue;
        printf("  0x%06X  return into, called by %s\n", v, how);
        shown++;
    }

    if (c.serial_len) {
        printf("\nserial output (%u bytes):\n---\n%.*s\n---\n",
               c.serial_len, (int)c.serial_len, c.serial);
    }

    if (c.trapped == 2) {
        printf("UNIMPLEMENTED opcode at 0x%06X -- that is the next one to add\n",
               c.trap_pc);
        return 0;
    }
    if (c.trapped) {
        printf("FAIL: left the traced image, wanted 0x%06X\n", c.trap_pc);
        printf("  recent dispatches:");
        uint32_t first = c.recent_n > 16 ? c.recent_n - 16 : 0;
        for (uint32_t k = first; k < c.recent_n; k++)
            printf(" %06X", c.recent[k & 15]);
        printf("\n");
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
