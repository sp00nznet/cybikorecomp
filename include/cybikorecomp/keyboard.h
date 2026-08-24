/* The Cybiko keyboard: 9 columns of 8 keys.
 *
 * A frontend calls cy_key() when a key goes down or up and the matrix keeps
 * the state, one byte per column, exactly the shape the hardware presents:
 * select a column, read eight rows.
 *
 * The layout is not guessed. It is MAME's, read out of the driver's own port
 * definitions -- nine ports A.0 to A.8, each field carrying the bit mask of
 * its key -- so a key here sits in the same column and the same bit as it
 * does on the machine this is a copy of. See docs/KEYBOARD.md.
 */
#ifndef CYBIKORECOMP_KEYBOARD_H
#define CYBIKORECOMP_KEYBOARD_H

#include <stdint.h>

#define CY_KEY_COLS 9

/* Column and bit packed into one byte: 0xCB, column in the high nibble. */
#define CY_KEY(col, bit) ((uint8_t)(((col) << 4) | (bit)))

#define CY_KEY_F7      CY_KEY(0, 0)
#define CY_KEY_ESC     CY_KEY(0, 1)
#define CY_KEY_DEL     CY_KEY(0, 2)
#define CY_KEY_LEFT    CY_KEY(0, 3)
#define CY_KEY_Q       CY_KEY(0, 4)
#define CY_KEY_A       CY_KEY(0, 5)
#define CY_KEY_GRAVE   CY_KEY(0, 6)
#define CY_KEY_SHIFT   CY_KEY(0, 7)

#define CY_KEY_F6      CY_KEY(1, 0)
#define CY_KEY_UP      CY_KEY(1, 1)
#define CY_KEY_INS     CY_KEY(1, 2)
#define CY_KEY_2       CY_KEY(1, 3)
#define CY_KEY_W       CY_KEY(1, 4)
#define CY_KEY_S       CY_KEY(1, 5)
#define CY_KEY_Z       CY_KEY(1, 6)
#define CY_KEY_FN      CY_KEY(1, 7)

#define CY_KEY_F5      CY_KEY(2, 0)
#define CY_KEY_F3      CY_KEY(2, 1)
#define CY_KEY_SPACE   CY_KEY(2, 2)
#define CY_KEY_3       CY_KEY(2, 3)
#define CY_KEY_E       CY_KEY(2, 4)
#define CY_KEY_D       CY_KEY(2, 5)
#define CY_KEY_X       CY_KEY(2, 6)
#define CY_KEY_HELP    CY_KEY(2, 7)

#define CY_KEY_F4      CY_KEY(3, 0)
#define CY_KEY_1       CY_KEY(3, 1)
#define CY_KEY_TAB     CY_KEY(3, 2)
#define CY_KEY_4       CY_KEY(3, 3)
#define CY_KEY_R       CY_KEY(3, 4)
#define CY_KEY_F       CY_KEY(3, 5)
#define CY_KEY_C       CY_KEY(3, 6)
#define CY_KEY_LBRACE  CY_KEY(3, 7)

#define CY_KEY_RIGHT   CY_KEY(4, 0)
#define CY_KEY_DOWN    CY_KEY(4, 1)
#define CY_KEY_SELECT  CY_KEY(4, 2)
#define CY_KEY_5       CY_KEY(4, 3)
#define CY_KEY_T       CY_KEY(4, 4)
#define CY_KEY_G       CY_KEY(4, 5)
#define CY_KEY_V       CY_KEY(4, 6)
#define CY_KEY_RBRACE  CY_KEY(4, 7)

#define CY_KEY_F2      CY_KEY(5, 0)
#define CY_KEY_SEMI    CY_KEY(5, 1)
#define CY_KEY_ENTER   CY_KEY(5, 2)
#define CY_KEY_6       CY_KEY(5, 3)
#define CY_KEY_Y       CY_KEY(5, 4)
#define CY_KEY_H       CY_KEY(5, 5)
#define CY_KEY_B       CY_KEY(5, 6)
#define CY_KEY_BSLASH  CY_KEY(5, 7)

#define CY_KEY_F1      CY_KEY(6, 0)
#define CY_KEY_SLASH   CY_KEY(6, 1)
#define CY_KEY_BKSP    CY_KEY(6, 2)
#define CY_KEY_7       CY_KEY(6, 3)
#define CY_KEY_U       CY_KEY(6, 4)
#define CY_KEY_J       CY_KEY(6, 5)
#define CY_KEY_N       CY_KEY(6, 6)

#define CY_KEY_MINUS   CY_KEY(7, 0)
#define CY_KEY_PERIOD  CY_KEY(7, 1)
#define CY_KEY_0       CY_KEY(7, 2)
#define CY_KEY_8       CY_KEY(7, 3)
#define CY_KEY_I       CY_KEY(7, 4)
#define CY_KEY_K       CY_KEY(7, 5)
#define CY_KEY_M       CY_KEY(7, 6)

#define CY_KEY_QUOTE   CY_KEY(8, 0)
#define CY_KEY_EQUALS  CY_KEY(8, 1)
#define CY_KEY_9       CY_KEY(8, 2)
#define CY_KEY_P       CY_KEY(8, 3)
#define CY_KEY_O       CY_KEY(8, 4)
#define CY_KEY_L       CY_KEY(8, 5)
#define CY_KEY_COMMA   CY_KEY(8, 6)

typedef struct {
    uint8_t col[CY_KEY_COLS];     /* a set bit is a key held down */
} cy_keys_t;

void    cy_key(cy_keys_t *k, uint8_t key, int down);
uint8_t cy_key_rows(const cy_keys_t *k, unsigned select);
int     cy_key_any(const cy_keys_t *k);

/* An ASCII character to a key, or 0xFF if this keyboard has no such key.
 * Only the unshifted characters -- the frontend has the host's shift state
 * and passes CY_KEY_SHIFT itself. */
uint8_t cy_key_from_ascii(int ch);

#endif
