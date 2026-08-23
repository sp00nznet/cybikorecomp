/* Which interrupt vector drives the boot ROM's tick counter?
 *
 * The boot loader waits for a host over serial with a timeout, and the timeout
 * is a counter at 0xFFEC04 that only an interrupt handler ever increments. It
 * is read half a million times and never changes, so the wait never ends.
 *
 * Rather than work out from the datasheet which on-chip timer the ROM has
 * programmed, run it once per candidate vector and see which one makes the
 * counter move. The vector table names them; there are only eighteen filled.
 *
 *   irqprobe <cybiko.img>
 */
#define _CRT_SECURE_NO_WARNINGS

#include <stdio.h>
#include <stdlib.h>

#include "cybikorecomp/h8s.h"

#define TICK 0xFFEC04u

static uint8_t img[CY_MEM_SIZE];
static size_t img_len;

/* Run to the point where the boot ROM is sitting in its wait loop, then
 * deliver `vec` a few times and see whether the tick counter advances. */
static uint32_t try_vector(int vec, uint32_t *before)
{
    cy_t c;
    if (cy_init(&c) != 0)
        exit(2);
    cy_load(&c, 0, img, (uint32_t)img_len);
    c.pc = cy_read32(&c, 0) & CY_ADDR_MASK;
    c.e[7] = 0x23FF00;

    cy_run(&c, 400000);                 /* into the wait loop */
    *before = cy_read32(&c, TICK);

    for (int k = 0; k < 8; k++) {
        if (c.trapped)
            break;
        cy_interrupt(&c, vec);
        cy_run(&c, c.cycles + 20000);
    }
    uint32_t after = cy_read32(&c, TICK);
    cy_free(&c);
    return after;
}

/* Each vector points at a 26-byte trampoline in the boot ROM that loads its
 * real handler from a slot in on-chip RAM. The slots run consecutively from
 * 0xFFEC0C, one per vector in table order, and the ROM fills them during init
 * -- so a vector is only live once its slot is. */
#define SLOT_BASE 0xFFEC0Cu

static uint32_t slot_of(int index) { return SLOT_BASE + 4u * (uint32_t)index; }

static void dump_slots(void)
{
    cy_t c;
    if (cy_init(&c) != 0)
        exit(2);
    cy_load(&c, 0, img, (uint32_t)img_len);
    c.pc = cy_read32(&c, 0) & CY_ADDR_MASK;
    c.e[7] = 0x23FF00;
    cy_run(&c, 400000);

    printf("handler slots once the ROM reaches its wait loop:\n");
    int idx = 0, self_ref = 0;
    for (int v = 0; v < 64; v++) {
        uint32_t t = ((uint32_t)img[4 * v] << 24) | ((uint32_t)img[4 * v + 1] << 16)
                   | ((uint32_t)img[4 * v + 2] << 8) | img[4 * v + 3];
        if (!t || t == 0xFFFFFFFFu || v == 0)
            continue;
        uint32_t h = cy_read32(&c, slot_of(idx)) & CY_ADDR_MASK;
        printf("  vec %2d  slot 0x%06X = 0x%06X%s\n", v, slot_of(idx), h,
               h == 0x001286 ? "   <-- the tick ISR"
               : (h == (t & CY_ADDR_MASK) ? "   (uninstalled: points at its own"
                                            " trampoline)" : ""));
        if (h == (t & CY_ADDR_MASK))
            self_ref++;
        idx++;
    }
    if (self_ref)
        printf("\n%d of %d slots still hold their own trampoline. The boot ROM\n"
               "does not install handlers -- CyOS does. Delivering an interrupt\n"
               "here recurses through the trampoline until the stack runs out.\n",
               self_ref, idx);
    printf("\n");
    cy_free(&c);
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: irqprobe <cybiko.img>\n");
        return 2;
    }
    FILE *f = fopen(argv[1], "rb");
    if (!f)
        return 2;
    img_len = fread(img, 1, CY_MEM_SIZE, f);
    fclose(f);

    dump_slots();
    printf("vector  handler   tick 0x%06X\n", TICK);
    int found = 0;
    for (int v = 0; v < 64; v++) {
        uint32_t h = ((uint32_t)img[4 * v] << 24) | ((uint32_t)img[4 * v + 1] << 16)
                   | ((uint32_t)img[4 * v + 2] << 8) | img[4 * v + 3];
        if (!h || h == 0xFFFFFFFFu || v == 0)
            continue;
        uint32_t before = 0;
        uint32_t after = try_vector(v, &before);
        printf("  %2d    0x%06X   %u -> %u%s\n", v, h & CY_ADDR_MASK,
               before, after, after != before ? "   <-- advances" : "");
        if (after != before)
            found++;
    }
    printf("\n%d vector(s) advance the tick counter\n", found);
    return found ? 0 : 1;
}
