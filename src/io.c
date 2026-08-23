/* The Cybiko's peripherals, in one place.
 *
 * Three things provide memory accessors -- the real runtime and two test
 * harnesses that log what passes through them -- and each used to carry its
 * own copy of the peripheral behaviour. That is not a style problem: an I/O
 * probe whose registers behave differently from the runtime's is measuring a
 * different machine, and the first run of that probe sat in the serial poll
 * loop the runtime had already been taught to escape, reporting half a million
 * reads of a register that was no longer a problem.
 *
 * So the behaviour lives here and everything calls it.
 */
#include "cybikorecomp/h8s.h"

/* An H8S interrupt in advanced mode pushes one longword: the 24-bit return
 * address with CCR in the top byte. RTE pops exactly that, which is why the
 * generated code has to restore CCR from it rather than only the PC. */
void cy_interrupt(cy_t *c, int vector)
{
    uint32_t frame = ((uint32_t)CY_CCR_GET(c) << 24) | (c->pc & CY_ADDR_MASK);
    c->e[7] -= 4;
    cy_write32(c, c->e[7], frame);
    c->iff = 1;
    c->pc = cy_read32(c, (uint32_t)(4 * vector)) & CY_ADDR_MASK;
}


int cy_io_read(cy_t *c, uint32_t a, uint8_t *out)
{
    switch (a) {
    case CY_SSR2:
        /* Always ready to send, never anything received. The boot ROM will
         * not proceed until the transmitter reports itself free. */
        *out = CY_SSR_TDRE | CY_SSR_TEND;
        return 1;
    default:
        (void)c;
        return 0;
    }
}

int cy_io_write(cy_t *c, uint32_t a, uint8_t v)
{
    switch (a) {
    case CY_TDR2:
        /* Wired to the debug serial port on real hardware. */
        if (c->serial_len < sizeof(c->serial) - 1)
            c->serial[c->serial_len++] = (char)v;
        return 0;                 /* still store it; the ROM reads it back */
    case CY_SSR2:
        /* Status bits are cleared by writing zero and cannot be set by
         * writing one, so a store here must not become the new value. The
         * boot ROM clears TDRE with `bclr #7, @0xFFFF8C` after a transmit. */
        return 1;
    default:
        return 0;
    }
}
