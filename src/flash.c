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
#define CMD_READ_PAGE_LOW   0xD2u   /* main memory page read */
#define CMD_READ_PAGE       0x57u
#define CMD_STATUS          0xD7u

/* Status: bit 7 set means "not busy", bits 5-2 are the density code. 0b1100
 * is the AT45DB041. Nothing here is ever busy, so bit 7 stays set. */
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

uint8_t cy_flash_xfer(cy_t *c, uint8_t out)
{
    if (!c->flash)
        return 0xFF;

    switch (c->spi_state) {
    case 0:                                   /* expecting a command */
        c->spi_cmd = out;
        c->spi_argn = 0;
        c->spi_state = (out == CMD_STATUS) ? 2 : 1;
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
        /* Both read commands need don't-care bytes before data starts: four
         * for the fast forms, one for the legacy ones. */
        c->spi_dummy = (c->spi_cmd == CMD_READ_CONT
                        || c->spi_cmd == CMD_READ_PAGE) ? 4 : 1;
        c->spi_state = 3;
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
