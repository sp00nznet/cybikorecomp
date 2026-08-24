/* Let the machine load its own OS, then keep what it loaded.
 *
 * Everything in this project so far has been recompiled from a RAM image
 * dumped out of MAME, which makes MAME a build dependency and caps what can
 * be recompiled at whatever happened to be resident when the dump was taken.
 * It does not have to be that way: the boot ROM is recompiled too, and given
 * a flash to read it will find CyOS, decompress it and start it exactly as
 * the hardware does.
 *
 * So run the ROM from its reset vector, wait for CyOS to appear at 0x200000,
 * and write SRAM out. The result is a dump this project produced itself, and
 * a later one -- taken after the modules CyOS loads at runtime have loaded --
 * is how code that is not resident at boot gets into the recompiler at all.
 *
 *   CYFLASH=flash_v1246.bin loader <boot.img> <out.bin> [dispatches]
 *
 * boot.img is a cyimage.py build with an empty RAM half; the ROM fills it.
 */
#define _CRT_SECURE_NO_WARNINGS

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cybikorecomp/h8s.h"

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: loader <boot.img> <out.bin> [dispatches]\n");
        return 2;
    }
    uint64_t budget = (argc > 3) ? strtoull(argv[3], NULL, 0) : 40000000;

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
    if (!cy_flash_load_env(&c)) {
        fprintf(stderr, "no flash: set $CYFLASH\n");
        return 2;
    }

    c.pc = cy_read32(&c, 0) & CY_ADDR_MASK;
    c.e[7] = 0x23FF00;

    /* Run in slices so the moment CyOS lands can be reported rather than
     * guessed at -- the loader decompresses into RAM and then jumps, and the
     * useful dump is any time after that. */
    uint64_t found = 0;
    while (c.cycles < budget && !c.trapped) {
        cy_run(&c, c.cycles + 1000000);
        if (!found && cy_read32(&c, CY_RAM_BASE) == CY_OS_MAGIC) {
            found = c.cycles;
            printf("CyOS header at %llu dispatches, entry 0x%06X\n",
                   (unsigned long long)found,
                   cy_read32(&c, CY_RAM_BASE + 4) & CY_ADDR_MASK);
        }
    }

    printf("stopped after %llu dispatches at pc=0x%06X%s\n",
           (unsigned long long)c.cycles, c.pc,
           c.trapped == 2 ? "  (unimplemented opcode)"
                          : c.trapped ? "  (left the image)" : "");
    if (c.serial_len)
        printf("---\n%.*s\n---\n", (int)c.serial_len, c.serial);

    FILE *o = fopen(argv[2], "wb");
    if (!o) {
        fprintf(stderr, "cannot write %s\n", argv[2]);
        return 2;
    }
    fwrite(c.mem + CY_RAM_BASE, 1, CY_RAM_SIZE, o);
    fclose(o);
    printf("%s: %u bytes of SRAM\n", argv[2], CY_RAM_SIZE);

    cy_free(&c);
    return found ? 0 : 1;
}
