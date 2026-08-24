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

/* --- the 8-bit timer (TMR) -------------------------------------------------
 *
 * Two channels sharing an interleaved register file at 0xFFFFB0. The Cybiko
 * uses both: channel 0 free-runs as the 10 ms system tick, channel 1 is a
 * stopwatch CyOS busy-waits on to time hardware it talks to a byte at a time.
 *
 *   B0 TCR0   B1 TCR1     control: bit 5 enables the overflow interrupt,
 *                         bits 2-0 pick the clock
 *   B2 TCSR0  B3 TCSR1    status: bit 5 is the overflow flag
 *   B8 TCNT0  B9 TCNT1    the counter
 *
 * Nothing writes the compare registers, so both channels are used purely for
 * overflow -- and a delay is therefore written as a *negative* preload:
 * `not.b r0l` then store, so the count from ~n up to 0x100 is n ticks. The
 * tick handler reloads 0xF2, which is 14 counts.
 *
 * The counter is derived rather than stepped: value = preload + elapsed/DIV,
 * so nothing has to run per instruction. DIV converts our instruction count
 * into timer ticks and is the one number here that is a guess. The timer is
 * configured for phi/8192, about 1.3 kHz at 11 MHz; 14 of those is the 10 ms
 * the tick handler's callers assume, so DIV is set to put 14 ticks in the
 * instructions this runs in 10 ms. Speed the machine up or down with
 * CY_TMR_DIV in h8s.h, which the frontends read to pace themselves.
 */
#define TMR_DIV CY_TMR_DIV

#define TCR0  0xFFFFB0u
#define TCSR0 0xFFFFB2u
#define TCNT  0xFFFFB8u

#define TCSR_OVF  0x20u
#define TCR_OVIE  0x20u
#define TMR_TICK_VECTOR 66     /* the boot ROM trampoline at 0x00157C */

static uint32_t tmr_count(cy_t *c, int ch)
{
    uint64_t d = (c->cycles - c->tmr_at[ch]) / TMR_DIV;
    return (uint32_t)(c->tmr_pre[ch] + d);
}

/* When channel 0 will next overflow, or "never" if it already has and the
 * handler has not rearmed it. One interrupt per arming is the whole of the
 * scheduling here. */
static void tmr_rearm(cy_t *c)
{
    uint32_t now = tmr_count(c, 0);
    c->irq_at = (now >= 0x100)
        ? (uint64_t)-1
        : c->tmr_at[0] + (uint64_t)(0x100 - now) * TMR_DIV;
}

void cy_io_reset(cy_t *c)
{
    c->irq_at = (uint64_t)-1;
}

/* Called from the dispatch in the generated code. */
void cy_irq_poll(cy_t *c)
{
    if (c->iff || c->cycles < c->irq_at)
        return;
    c->irq_at = (uint64_t)-1;
    if (c->mem[TCR0] & TCR_OVIE)
        cy_interrupt(c, TMR_TICK_VECTOR);
}

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
    case CY_SSR0:
        /* Always ready to send, never anything received. The boot ROM will
         * not proceed until the transmitter reports itself free. */
        *out = CY_SSR_TDRE | CY_SSR_TEND;
        return 1;

    /* The SPI side. SSR1 reports the transmitter free and, once a byte has
     * been clocked out, a byte received -- an SPI transfer is a simultaneous
     * send and receive, so every write to TDR1 produces one. */
    case CY_SSR1:
        *out = (uint8_t)(CY_SSR_TDRE | CY_SSR_TEND
                         | (c->spi_pending ? CY_SSR_RDRF : 0));
        return 1;
    case CY_RDR1:
        *out = c->spi_in;
        c->spi_pending = 0;
        return 1;
    case CY_SPI_RDY:
        *out = CY_SPI_RDY_BIT;
        return 1;

    case TCSR0: case TCSR0 + 1: {
        int ch = (int)(a - TCSR0);
        *out = (uint8_t)(c->tmr_csr[ch]
                         | (tmr_count(c, ch) >= 0x100 ? TCSR_OVF : 0));
        return 1;
    }
    case TCNT: case TCNT + 1:
        *out = (uint8_t)tmr_count(c, (int)(a - TCNT));
        return 1;
    default:
        (void)c;
        return 0;
    }
}

int cy_io_write(cy_t *c, uint32_t a, uint8_t v)
{
    /* The LCD is not an on-chip peripheral -- it sits on the external bus at
     * 0x600000, which is why nothing in the I/O register sweep ever saw it. */
    if (a == CY_LCD_PORT || a == CY_LCD_DATA)
        return cy_lcd_write(&c->lcd, a, v);

    switch (a) {
    case CY_TDR2:
        /* Wired to the debug serial port on real hardware. */
        if (c->serial_len < sizeof(c->serial) - 1)
            c->serial[c->serial_len++] = (char)v;
        return 0;                 /* still store it; the ROM reads it back */
    case CY_SSR2:
    case CY_SSR1:
    case CY_SSR0:
        /* Status bits are cleared by writing zero and cannot be set by
         * writing one, so a store here must not become the new value. The
         * boot ROM clears TDRE with `bclr #7, @0xFFFF8C` after a transmit. */
        return 1;

    case CY_TDR1:
        /* One byte clocked to the flash. What comes back depends on where the
         * chip is in its command, which cy_flash_xfer tracks. */
        c->spi_in = cy_flash_xfer(c, v);
        c->spi_pending = 1;
        return 0;

    case CY_TDR0:
        if (c->sci0_len < sizeof c->sci0)
            c->sci0[c->sci0_len++] = v;
        return 0;

    case CY_SPI_CS:
        /* Chip select is active *low*: the boot ROM clears bit 4 with
         * `and.b #0xEF` before a command and sets it again with
         * `or.b #0x10` afterwards, so a one here is the end of a command. */
        if (v & CY_SPI_CS_BIT)
            cy_flash_deselect(c);
        return 0;

    /* Writing the counter restarts the measurement; the status flags are
     * write-zero-to-clear, and clearing OVF has to move the anchor with it or
     * the derived count would still be past 0x100 and the flag would come
     * straight back -- which is exactly how a delay loop hangs. */
    case TCNT: case TCNT + 1: {
        int ch = (int)(a - TCNT);
        c->tmr_pre[ch] = v;
        c->tmr_at[ch] = c->cycles;
        if (ch == 0)
            tmr_rearm(c);
        return 1;
    }
    case TCSR0: case TCSR0 + 1: {
        int ch = (int)(a - TCSR0);
        if (!(v & TCSR_OVF) && tmr_count(c, ch) >= 0x100) {
            c->tmr_pre[ch] = (uint8_t)tmr_count(c, ch);
            c->tmr_at[ch] = c->cycles;
            if (ch == 0)
                tmr_rearm(c);
        }
        c->tmr_csr[ch] = (uint8_t)(v & ~TCSR_OVF);
        return 1;
    }
    default:
        return 0;
    }
}
