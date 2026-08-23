/* What is on the screen?
 *
 * Runs the image and prints the HD66421's display RAM as characters, two
 * dots to a column so a 160-wide panel fits an 80-column terminal. Four grey
 * levels map onto four glyphs, densest first.
 *
 *   lcdprobe <cybiko.img> [dispatches] [cyos]
 */
#define _CRT_SECURE_NO_WARNINGS

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cybikorecomp/h8s.h"

/* Level 3 is what the panel is cleared to, so it is the background. */
static const char *GLYPH = "@%. ";

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: lcdprobe <cybiko.img> [dispatches] [cyos]\n");
        return 2;
    }
    uint64_t budget = (argc > 2) ? strtoull(argv[2], NULL, 0) : 20000000;

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
    cy_flash_load_env(&c);

    if (argc > 3 && strcmp(argv[3], "cyos") == 0) {
        c.pc = cy_read32(&c, CY_RAM_BASE + 4) & CY_ADDR_MASK;
        c.e[7] = 0x27FF00;
    } else {
        c.pc = cy_read32(&c, 0) & CY_ADDR_MASK;
        c.e[7] = 0x23FF00;
    }
    cy_run(&c, budget);

    printf("after %llu dispatches, pc=0x%06X, display %s\n",
           (unsigned long long)c.cycles, c.pc,
           cy_lcd_on(&c.lcd) ? "on" : "off");

    /* Two rows of dots per line of text, so the aspect ratio survives. */
    for (int y = 0; y < CY_LCD_H; y += 2) {
        for (int x = 0; x < CY_LCD_W; x += 2)
            putchar(GLYPH[cy_lcd_dot(&c.lcd, x, y)]);
        putchar('\n');
    }

    printf("\nregisters:");
    for (int i = 0; i < 32; i++)
        printf("%s%02X", (i % 16) ? " " : "\n  ", c.lcd.reg[i]);
    printf("\n");
    return 0;
}
