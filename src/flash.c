/* The AT45DB041 serial flash the Cybiko keeps CyOS and its files on.
 *
 * SPI is a shift register: every byte the CPU clocks out produces one coming
 * back. A command is a byte, usually some address bytes, then a run of data.
 * So the model is a small state machine over the byte stream, reset whenever
 * chip select is deasserted.
 *
 * The geometry is the unusual part and the reason the image is 540,672 bytes
 * rather than a round 512K: pages are **264** bytes, not 256. An address is
 * split accordingly -- 11 bits of page, 9 bits of byte-within-page -- so the
 * byte at page P offset B lives at P*264 + B in the dump, and treating the
 * address as flat lands in the wrong place by an increasing margin.
 */
#define _CRT_SECURE_NO_WARNINGS

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "cybikorecomp/h8s.h"

#define PAGE_BYTES 264u
#define PAGE_COUNT 2048u
#define FLASH_SIZE (PAGE_BYTES * PAGE_COUNT)   /* 540,672 */

/* The commands CyOS uses to read. The AT45DB has two of each, differing only
 * in whether it will run at the higher clock rate. */
#define CMD_READ_CONT_LOW   0x52u   /* continuous array read, legacy */
#define CMD_READ_CONT       0x68u
#define CMD_READ_PAGE       0xD2u   /* main memory page read */

/* Status has two opcodes and the boot ROM uses the older one. Reading 0x57
 * as a page read instead cost a boot: the ROM took the 0xFF that a
 * half-parsed command returns, pulled bits 5-3 out of it, and announced
 * "Detected flash device model 7 [-5 blocks of 0 bytes]" -- a model number
 * off the end of its own table. */
#define CMD_STATUS_LOW      0x57u
#define CMD_STATUS          0xD7u

/* Status: bit 7 set means "not busy", bits 5-2 are the density code, 0111 for
 * the AT45DB041. Nothing here is ever busy, so bit 7 stays set.
 *
 * The boot ROM takes bits 5-3 rather than 5-2 -- `shlr.w #2` then `shlr.w`
 * then `and #7` at 0x002E28 -- so what it reads out of 0x9C is 3, and 3 is
 * the entry in its table that says 2048 pages. */
#define STATUS_READY  0x9Cu

int cy_flash_load(cy_t *c, const void *data, uint32_t len)
{
    if (!c->flash) {
        c->flash = (uint8_t *)malloc(FLASH_SIZE);
        if (!c->flash)
            return -1;
        memset(c->flash, 0xFF, FLASH_SIZE);
    }
    if (len > FLASH_SIZE)
        len = FLASH_SIZE;
    memcpy(c->flash, data, len);
    return 0;
}

void cy_flash_deselect(cy_t *c)
{
    c->spi_state = 0;
    c->spi_cmd = 0;
    c->spi_argn = 0;
}

/* $CYFLASHLOG traces the command stream. What the chip is asked for is the
 * only way to tell a command that is unimplemented from one that is
 * implemented wrongly, and the two look identical from the guest. */
static void trace(const char *what, uint8_t v, uint32_t addr)
{
    static int on = -1;
    if (on < 0)
        on = getenv("CYFLASHLOG") != NULL;
    if (on)
        fprintf(stderr, "[flash] %-6s %02X  @%06X\n", what, v, addr);
}

uint8_t cy_flash_xfer(cy_t *c, uint8_t out)
{
    if (!c->flash)
        return 0xFF;

    switch (c->spi_state) {
    case 0:                                   /* expecting a command */
        c->spi_cmd = out;
        c->spi_argn = 0;
        c->spi_state = (out == CMD_STATUS || out == CMD_STATUS_LOW) ? 2 : 1;
        trace("cmd", out, 0);
        return 0xFF;

    case 1:                                   /* collecting address bytes */
        c->spi_arg[c->spi_argn++] = out;
        if (c->spi_argn < 3)
            return 0xFF;
        {
            /* 11 bits of page, 9 of offset, packed into 24 bits with the top
             * three unused. */
            uint32_t a = ((uint32_t)c->spi_arg[0] << 16)
                       | ((uint32_t)c->spi_arg[1] << 8)
                       |  (uint32_t)c->spi_arg[2];
            uint32_t page = (a >> 9) & (PAGE_COUNT - 1);
            uint32_t off = a & 0x1FFu;
            if (off >= PAGE_BYTES)
                off = PAGE_BYTES - 1;
            c->spi_addr = page * PAGE_BYTES + off;
        }
        /* Four don't-care bytes before the data starts, on every read form.
         * The boot ROM makes this unusually easy to confirm: it builds the
         * command and address as one 32-bit word at 0x002BB6, sends those
         * four bytes, then sends the same four again as the don't-cares. */
        c->spi_dummy = 4;
        c->spi_state = 3;
        trace("addr", c->spi_cmd, c->spi_addr);
        return 0xFF;

    case 2:                                   /* status register */
        return STATUS_READY;

    case 3:                                   /* don't-care bytes */
        if (c->spi_dummy) {
            c->spi_dummy--;
            return 0xFF;
        }
        c->spi_state = 4;
        /* fall through */

    case 4:                                   /* streaming data */
    default:
        {
            uint8_t v = c->flash[c->spi_addr % FLASH_SIZE];
            c->spi_addr++;
            return v;
        }
    }
}

/* Load the flash image named by $CYFLASH, if it is set. Every harness wants
 * this and none of them want their own copy of it. Returns the byte count,
 * or 0 if there was nothing to load. */
uint32_t cy_flash_load_env(cy_t *c)
{
    const char *path = getenv("CYFLASH");
    if (!path)
        return 0;
    FILE *f = fopen(path, "rb");
    if (!f)
        return 0;
    static uint8_t buf[FLASH_SIZE];
    size_t n = fread(buf, 1, sizeof buf, f);
    fclose(f);
    return cy_flash_load(c, buf, (uint32_t)n) == 0 ? (uint32_t)n : 0;
}
