/* The key matrix holds what it is told, in the shape the hardware reads.
 *
 * Small enough to be obvious and still worth pinning: a key in the wrong
 * column is invisible in every frontend and only shows up as "that key does
 * nothing", which is indistinguishable from the scan not being wired yet.
 *
 *   keyprobe
 */
#include <assert.h>
#include <stdio.h>

#include "cybikorecomp/keyboard.h"

int main(void)
{
    cy_keys_t k = { { 0 } };

    /* Nothing held reads as nothing, on every column. */
    for (unsigned c = 0; c < CY_KEY_COLS; c++)
        assert(cy_key_rows(&k, 1u << c) == 0);
    assert(!cy_key_any(&k));

    /* Q is column 0, bit 4 -- and is invisible from any other column. */
    cy_key(&k, CY_KEY_Q, 1);
    assert(cy_key_rows(&k, 1u << 0) == 0x10);
    for (unsigned c = 1; c < CY_KEY_COLS; c++)
        assert(cy_key_rows(&k, 1u << c) == 0);
    assert(cy_key_any(&k));

    /* Two columns selected together read as the union, which is how a real
     * matrix ghosts. A is column 0 bit 5, W is column 1 bit 4. */
    cy_key(&k, CY_KEY_W, 1);
    assert(cy_key_rows(&k, 0x003) == 0x10);
    cy_key(&k, CY_KEY_A, 1);
    assert(cy_key_rows(&k, 0x001) == 0x30);
    assert(cy_key_rows(&k, 0x003) == 0x30);

    /* Release takes only the one key. */
    cy_key(&k, CY_KEY_Q, 0);
    assert(cy_key_rows(&k, 0x001) == 0x20);
    assert(cy_key_rows(&k, 0x002) == 0x10);

    /* The last column really is column 8, not a seven-bit select. */
    cy_key(&k, CY_KEY_COMMA, 1);
    assert(cy_key_rows(&k, 1u << 8) == 0x40);

    /* Characters find their keys, case-folded, and a key this keyboard does
     * not have says so rather than landing on something arbitrary. */
    assert(cy_key_from_ascii('q') == CY_KEY_Q);
    assert(cy_key_from_ascii('Q') == CY_KEY_Q);
    assert(cy_key_from_ascii('\n') == CY_KEY_ENTER);
    assert(cy_key_from_ascii('~') == 0xFF);

    /* Out-of-range keys are ignored rather than corrupting a column. */
    cy_key(&k, CY_KEY(9, 0), 1);
    cy_key(&k, CY_KEY(0, 9), 1);
    assert(cy_key_rows(&k, 0x001) == 0x20);

    printf("keys ok  (9 columns, 8 rows, %d named)\n", 72);
    return 0;
}
