/* The HD66421 LCD controller.
 *
 * 160x100 dots, two bits per dot, so four grey levels and 40 bytes to a row.
 * It hangs off the external bus rather than any on-chip peripheral: an index
 * port at 0x600000 and a data port at 0x600001, so every access is two
 * writes -- name a register, then write it.
 *
 *     @0x600000 = 2   @0x600001 = x        column, 0..39
 *     @0x600000 = 3   @0x600001 = y        row, 0..99
 *     @0x600000 = 4   @0x600001 = <byte>   four dots, column auto-increments
 *
 * That is the whole of the frame path. CyOS's blit at 0x206F72 walks rows
 * from 0x63 downwards writing 40 bytes each, and the boot ROM clears the
 * panel the same way at 0x004A82.
 */
#ifndef CYBIKORECOMP_LCD_H
#define CYBIKORECOMP_LCD_H

#include <stdint.h>

#define CY_LCD_W       160
#define CY_LCD_H       100
#define CY_LCD_STRIDE  (CY_LCD_W / 4)     /* 4 dots to a byte */

#define CY_LCD_PORT    0x600000u          /* index */
#define CY_LCD_DATA    0x600001u

/* The registers this needs to name. */
#define CY_LCD_R_DISP  0x00               /* bit 6 turns the panel on */
#define CY_LCD_R_X     0x02
#define CY_LCD_R_Y     0x03
#define CY_LCD_R_DATA  0x04

typedef struct {
    uint8_t index;
    uint8_t reg[32];
    uint8_t vram[CY_LCD_H * CY_LCD_STRIDE];
} cy_lcd_t;

/* Handle a write to 0x600000 or 0x600001. Returns 1 if it was one. */
int cy_lcd_write(cy_lcd_t *l, uint32_t addr, uint8_t v);

/* The grey level 0-3 at a dot, 3 being the value the panel is cleared to. */
uint8_t cy_lcd_dot(const cy_lcd_t *l, int x, int y);

int cy_lcd_on(const cy_lcd_t *l);

#endif
