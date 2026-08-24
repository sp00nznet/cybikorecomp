/* The key matrix.
 *
 * Nine columns, eight rows. Holding the state is all this does; what reads it
 * is the hardware side, and that is the part still missing -- see
 * docs/KEYBOARD.md for why the scan cannot be pinned down yet and what would
 * pin it down.
 *
 * cy_key_rows takes a column *select mask* rather than a column number,
 * because a matrix does not care how many lines are driven at once: two
 * columns selected together read as the union of their rows, and that is how
 * ghosting happens on real hardware. Whatever ends up driving the select can
 * pass what it has.
 */
#include "cybikorecomp/keyboard.h"

void cy_key(cy_keys_t *k, uint8_t key, int down)
{
    unsigned col = key >> 4, bit = key & 0xF;
    if (col >= CY_KEY_COLS || bit > 7)
        return;
    if (down)
        k->col[col] |= (uint8_t)(1u << bit);
    else
        k->col[col] &= (uint8_t)~(1u << bit);
}

uint8_t cy_key_rows(const cy_keys_t *k, unsigned select)
{
    uint8_t rows = 0;
    for (unsigned c = 0; c < CY_KEY_COLS; c++)
        if (select & (1u << c))
            rows |= k->col[c];
    return rows;
}

int cy_key_any(const cy_keys_t *k)
{
    uint8_t any = 0;
    for (unsigned c = 0; c < CY_KEY_COLS; c++)
        any |= k->col[c];
    return any != 0;
}

/* The printable keys, in the order a US keyboard has them. Everything not
 * listed -- the arrows, the function keys, Shift, Fn -- has no character and
 * a frontend names it by its CY_KEY_ constant. */
static const struct { char ch; uint8_t key; } ASCII[] = {
    { 'a', CY_KEY_A }, { 'b', CY_KEY_B }, { 'c', CY_KEY_C }, { 'd', CY_KEY_D },
    { 'e', CY_KEY_E }, { 'f', CY_KEY_F }, { 'g', CY_KEY_G }, { 'h', CY_KEY_H },
    { 'i', CY_KEY_I }, { 'j', CY_KEY_J }, { 'k', CY_KEY_K }, { 'l', CY_KEY_L },
    { 'm', CY_KEY_M }, { 'n', CY_KEY_N }, { 'o', CY_KEY_O }, { 'p', CY_KEY_P },
    { 'q', CY_KEY_Q }, { 'r', CY_KEY_R }, { 's', CY_KEY_S }, { 't', CY_KEY_T },
    { 'u', CY_KEY_U }, { 'v', CY_KEY_V }, { 'w', CY_KEY_W }, { 'x', CY_KEY_X },
    { 'y', CY_KEY_Y }, { 'z', CY_KEY_Z },
    { '0', CY_KEY_0 }, { '1', CY_KEY_1 }, { '2', CY_KEY_2 }, { '3', CY_KEY_3 },
    { '4', CY_KEY_4 }, { '5', CY_KEY_5 }, { '6', CY_KEY_6 }, { '7', CY_KEY_7 },
    { '8', CY_KEY_8 }, { '9', CY_KEY_9 },
    { ' ', CY_KEY_SPACE }, { '\n', CY_KEY_ENTER }, { '\t', CY_KEY_TAB },
    { '\b', CY_KEY_BKSP },
    { '-', CY_KEY_MINUS }, { '=', CY_KEY_EQUALS }, { '[', CY_KEY_LBRACE },
    { ']', CY_KEY_RBRACE }, { '\\', CY_KEY_BSLASH }, { ';', CY_KEY_SEMI },
    { '\'', CY_KEY_QUOTE }, { ',', CY_KEY_COMMA }, { '.', CY_KEY_PERIOD },
    { '/', CY_KEY_SLASH }, { '`', CY_KEY_GRAVE },
};

uint8_t cy_key_from_ascii(int ch)
{
    if (ch >= 'A' && ch <= 'Z')
        ch += 'a' - 'A';
    for (unsigned i = 0; i < sizeof ASCII / sizeof ASCII[0]; i++)
        if (ASCII[i].ch == ch)
            return ASCII[i].key;
    return 0xFF;
}
