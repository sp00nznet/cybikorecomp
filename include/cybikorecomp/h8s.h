/* H8S/2000 execution context for recompiled Cybiko code.
 *
 * The recompiled image is one C function with a label per instruction, so this
 * holds only architectural state. There is no instruction pointer to maintain
 * except at a computed transfer, where `pc` is set and the generated dispatch
 * takes over.
 *
 * Registers are held as eight uint32 and accessed through masks, because the
 * H8S aliases them three ways: ER0 is E0:R0, and R0 is R0H:R0L. An 8-bit write
 * has to leave the other 24 bits alone, so the emitter never assigns a whole
 * register unless the instruction really is 32-bit.
 */
#ifndef CYBIKORECOMP_H8S_H
#define CYBIKORECOMP_H8S_H

#include <stdint.h>

#include "cybikorecomp/lcd.h"

/* Advanced mode: 24-bit addresses. 16 MB of flat memory is less than the
 * machine this runs on has in a browser tab, and it makes every access a
 * bounds-masked array index rather than a region search. */
/* Where the 512K SRAM lives, and the header the loaded CyOS image carries at
 * the bottom of it: the magic, then its entry point. */
#define CY_RAM_BASE  0x200000u
#define CY_RAM_SIZE  0x080000u
#define CY_OS_MAGIC  0x1234ABCDu

#define CY_ADDR_BITS 24
#define CY_ADDR_MASK 0x00FFFFFFu
#define CY_MEM_SIZE  (1u << CY_ADDR_BITS)

typedef struct cy {
    uint32_t e[8];            /* ER0-ER7; ER7 is the stack pointer */
    uint32_t pc;              /* only meaningful at a computed transfer */

    uint8_t  nf, zf, vf, cf;  /* CCR condition flags, one byte each */
    uint8_t  hf;              /* half carry, for the decimal adjust ops */
    uint8_t  iff;             /* interrupt mask */

    uint8_t  trapped;         /* dispatched somewhere with no code */
    uint32_t trap_pc;
    /* A ring of recent dispatch targets. When a trap says "wanted 0x00004E"
     * the useful question is what was running just before, and reconstructing
     * that from the image by hand is far more work than keeping sixteen. */
    uint32_t recent[16];
    uint32_t recent_n;
    uint64_t cycles;          /* dispatch iterations, not instructions:
                               * straight-line runs inside a chunk are free */

    uint8_t *mem;             /* CY_MEM_SIZE bytes, big-endian contents */

    /* Whatever the boot ROM sends out of SCI2, which is wired to the debug
     * serial port on real hardware. Capturing it is the cheapest window into
     * what the firmware thinks it is doing. */
    char     serial[4096];
    uint32_t serial_len;

    /* The SPI flash, and where the chip is in the command being clocked into
     * it. An SPI transfer sends and receives at once, so spi_in holds the byte
     * that came back from the last write to TDR1. */
    uint8_t *flash;
    uint8_t  spi_in, spi_pending;
    uint8_t  spi_state, spi_cmd, spi_argn, spi_dummy;
    uint8_t  spi_arg[3];
    uint32_t spi_addr;

    /* The two 8-bit timer channels. The counter is derived from `cycles`
     * rather than stepped, so only the preload and its anchor are kept. */
    uint8_t  tmr_pre[2], tmr_csr[2];
    uint64_t tmr_at[2];
    uint64_t irq_at;          /* cycle of the next tick interrupt */

    /* What CyOS clocks out of SCI0, kept so the protocol can be read back.
     * Diagnostic only -- nothing in the runtime consumes it. */
    uint8_t  sci0[512];
    uint32_t sci0_len;

    cy_lcd_t lcd;
} cy_t;

void cy_io_reset(cy_t *c);
void cy_irq_poll(cy_t *c);

/* Cheap enough to sit on every loop back-edge: one compare against a
 * precomputed deadline. cy_irq_poll does the rest, from the run loop. */
#define CY_IRQ_DUE(c) ((c)->cycles >= (c)->irq_at && !(c)->iff)

/* The AT45DB041 behind SCI1. Pages are 264 bytes, not 256. */
int     cy_flash_load(cy_t *c, const void *data, uint32_t len);
uint8_t cy_flash_xfer(cy_t *c, uint8_t out);
void    cy_flash_deselect(cy_t *c);
uint32_t cy_flash_load_env(cy_t *c);

/* --- H8S/2246 on-chip peripherals ---------------------------------------
 *
 * Only the ones the boot ROM waits on. It polls SSR2 half a million times
 * before doing anything else, because it will not proceed until the serial
 * transmitter says it is ready. */
#define CY_WDT_TCSR  0xFFFF3Cu    /* watchdog */

#define CY_SMR2      0xFFFF88u    /* serial mode */
#define CY_BRR2      0xFFFF89u    /* baud rate */
#define CY_SCR2      0xFFFF8Au    /* control: TE/RE enable */
#define CY_TDR2      0xFFFF8Bu    /* transmit data */
#define CY_SSR2      0xFFFF8Cu    /* status */
#define CY_RDR2      0xFFFF8Du    /* receive data */

/* SSR bits. TDRE says the transmit register is free, TEND that the last byte
 * has gone. Reporting both always is what a port with nothing attached and
 * infinite speed looks like. */
#define CY_SSR_TDRE  0x80u
#define CY_SSR_RDRF  0x40u
#define CY_SSR_TEND  0x04u

/* SCI1, wired as the SPI port to the AT45DB flash. CyOS puts it in
 * synchronous mode, asserts chip select through bit 4 of 0xFFFF62, waits for
 * bit 2 of 0xFFFF5E, then clocks command bytes out of TDR1. */
#define CY_TDR0      0xFFFF7Bu    /* SCI0, believed to be the LCD */
#define CY_SSR0      0xFFFF7Cu
#define CY_SMR1      0xFFFF80u
#define CY_BRR1      0xFFFF81u
#define CY_SCR1      0xFFFF82u
#define CY_TDR1      0xFFFF83u
#define CY_SSR1      0xFFFF84u
#define CY_RDR1      0xFFFF85u
#define CY_SPI_RDY   0xFFFF5Eu    /* bit 2: the port is ready to be driven */
#define CY_SPI_CS    0xFFFF62u    /* bit 4: chip select */
#define CY_SPI_RDY_BIT 0x04u
#define CY_SPI_CS_BIT  0x10u

int  cy_init(cy_t *c);
void cy_free(cy_t *c);

/* Load an image at an address. Returns 0 on success. */
int  cy_load(cy_t *c, uint32_t addr, const void *data, uint32_t len);

/* Big-endian, because the H8S is. */
uint8_t  cy_read8(cy_t *c, uint32_t a);
uint16_t cy_read16(cy_t *c, uint32_t a);
uint32_t cy_read32(cy_t *c, uint32_t a);
void cy_write8(cy_t *c, uint32_t a, uint8_t v);
void cy_write16(cy_t *c, uint32_t a, uint16_t v);
void cy_write32(cy_t *c, uint32_t a, uint32_t v);

/* Deliver an interrupt: push the return address with CCR packed into its top
 * byte, mask further interrupts, and vector. This is what the boot ROM's
 * timeout loops are waiting for -- they poll a tick counter that only an
 * interrupt handler ever advances. */
void cy_interrupt(cy_t *c, int vector);

/* Peripheral behaviour, in src/io.c. Both return nonzero when they have
 * handled the access; every provider of the accessors below must call them,
 * or it is emulating a different machine from the one being measured. */
int cy_io_read(cy_t *c, uint32_t a, uint8_t *out);
int cy_io_write(cy_t *c, uint32_t a, uint8_t v);

/* Generated. Runs from c->pc until a trap or `budget` cycles. */
void cy_run(cy_t *c, uint64_t budget);

/* Evaluate a condition code 0-15, for the branch forms the emitter does not
 * special-case. Order is the H8S Bcc table: bra brn bhi bls bcc bcs bne beq
 * bvc bvs bpl bmi bge blt bgt ble. */
int cy_cond(const cy_t *c, int cc);

/* --- flag helpers used by generated code -------------------------------- */

#define CY_MASK_b 0xFFu
#define CY_MASK_w 0xFFFFu
#define CY_MASK_l 0xFFFFFFFFu
#define CY_SIGN_b 0x80u
#define CY_SIGN_w 0x8000u
#define CY_SIGN_l 0x80000000u

/* N and Z from a result; V cleared, as the logic and move ops do. */
#define SETNZ(res, sz)                                                    \
    do {                                                                  \
        uint32_t cy__r = (uint32_t)(res) & CY_MASK_##sz;                  \
        c->nf = (cy__r & CY_SIGN_##sz) != 0;                              \
        c->zf = (cy__r == 0);                                             \
        c->vf = 0;                                                        \
    } while (0)

/* Carry out of the top bit, and signed overflow: the operands agreed on sign
 * and the result disagrees with them. */
#define SETFLAGS_ADD(a, b, res, sz)                                       \
    do {                                                                  \
        uint32_t cy__a = (uint32_t)(a) & CY_MASK_##sz;                    \
        uint32_t cy__b = (uint32_t)(b) & CY_MASK_##sz;                    \
        uint32_t cy__r = (uint32_t)(res) & CY_MASK_##sz;                  \
        c->cf = ((cy__a + cy__b) > CY_MASK_##sz);                         \
        c->vf = (((cy__a ^ cy__r) & (cy__b ^ cy__r) & CY_SIGN_##sz) != 0);\
        c->nf = (cy__r & CY_SIGN_##sz) != 0;                              \
        c->zf = (cy__r == 0);                                             \
        c->hf = (((cy__a & 0xF) + (cy__b & 0xF)) > 0xF);                  \
    } while (0)

/* Borrow, and overflow when the operands differed in sign and the result took
 * the subtrahend's. */
#define SETFLAGS_SUB(a, b, res, sz)                                       \
    do {                                                                  \
        uint32_t cy__a = (uint32_t)(a) & CY_MASK_##sz;                    \
        uint32_t cy__b = (uint32_t)(b) & CY_MASK_##sz;                    \
        uint32_t cy__r = (uint32_t)(res) & CY_MASK_##sz;                  \
        c->cf = (cy__a < cy__b);                                          \
        c->vf = (((cy__a ^ cy__b) & (cy__a ^ cy__r) & CY_SIGN_##sz) != 0);\
        c->nf = (cy__r & CY_SIGN_##sz) != 0;                              \
        c->zf = (cy__r == 0);                                             \
        c->hf = ((cy__a & 0xF) < (cy__b & 0xF));                          \
    } while (0)

/* CMP is SUB without the writeback, so the flags are identical. */
#define SETFLAGS_CMP(a, b, res, sz) SETFLAGS_SUB(a, b, res, sz)

/* CCR as the hardware packs it. The flags live in separate bytes for speed,
 * so the ops that treat the whole register as a value have to pack and unpack:
 *
 *   bit  7   6   5   4   3   2   1   0
 *        I   UI  H   U   N   Z   V   C
 *
 * U and UI are user bits with no meaning to the CPU; they are kept only so a
 * store-then-load round-trips. */
#define CY_CCR_GET(c)                                                     \
    ((uint8_t)(((c)->iff << 7) | ((c)->hf << 5) | ((c)->nf << 3)          \
             | ((c)->zf << 2) | ((c)->vf << 1) | (c)->cf))

#define CY_CCR_SET(c, v)                                                  \
    do {                                                                  \
        uint8_t cy__v = (uint8_t)(v);                                     \
        (c)->iff = (cy__v >> 7) & 1;                                      \
        (c)->hf  = (cy__v >> 5) & 1;                                      \
        (c)->nf  = (cy__v >> 3) & 1;                                      \
        (c)->zf  = (cy__v >> 2) & 1;                                      \
        (c)->vf  = (cy__v >> 1) & 1;                                      \
        (c)->cf  =  cy__v       & 1;                                      \
    } while (0)

/* An instruction the emitter has not learned yet. It stops rather than
 * guessing, so a run that reaches one says exactly which opcode to add next
 * instead of quietly computing the wrong thing. */
#define UNIMPLEMENTED(addr)                                               \
    do {                                                                  \
        c->trapped = 2;                                                   \
        c->trap_pc = (addr);                                              \
        return;                                                           \
    } while (0)

#endif
