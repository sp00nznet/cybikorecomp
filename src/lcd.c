/* The HD66421, as far as anything on this machine uses it.
 *
 * Only three of its registers carry the frame: X, Y and the auto-incrementing
 * data port. The rest -- contrast, bias, the charge pump -- are stored so a
 * read gives back what was written and nothing more, because nothing here
 * depends on them and modelling a contrast voltage would be inventing detail
 * the display path cannot show.
 */
#include "cybikorecomp/lcd.h"

int cy_lcd_write(cy_lcd_t *l, uint32_t addr, uint8_t v)
{
    if (addr == CY_LCD_PORT) {
        l->index = (uint8_t)(v & 0x1F);
        return 1;
    }
    if (addr != CY_LCD_DATA)
        return 0;

    if (l->index == CY_LCD_R_DATA) {
        uint32_t x = l->reg[CY_LCD_R_X];
        uint32_t y = l->reg[CY_LCD_R_Y];
        if (x < CY_LCD_STRIDE && y < CY_LCD_H)
            l->vram[y * CY_LCD_STRIDE + x] = v;
        /* The column wraps rather than spilling into the next row: the
         * controller counts within a line, and the writer sets Y itself. */
        l->reg[CY_LCD_R_X] = (uint8_t)((x + 1) % CY_LCD_STRIDE);
        return 1;
    }
    l->reg[l->index] = v;
    return 1;
}

uint8_t cy_lcd_dot(const cy_lcd_t *l, int x, int y)
{
    if (x < 0 || x >= CY_LCD_W || y < 0 || y >= CY_LCD_H)
        return 3;
    /* Leftmost dot in the high bits: the boot ROM's clear writes 0xFF for a
     * blank line, so all four levels in a byte are the same and only the
     * order within a byte is a choice -- this one matches the controller. */
    uint8_t b = l->vram[y * CY_LCD_STRIDE + (x >> 2)];
    return (uint8_t)((b >> (2 * (3 - (x & 3)))) & 3);
}

int cy_lcd_on(const cy_lcd_t *l)
{
    return (l->reg[CY_LCD_R_DISP] & 0x40) != 0;
}
