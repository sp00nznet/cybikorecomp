/* Memory and condition codes for recompiled Cybiko code.
 *
 * The address space is flat here. A real Cybiko has the boot ROM at 0, SRAM at
 * 0x200000, on-chip RAM and I/O at the top, and an SPI flash reached through
 * registers rather than memory -- but every one of those is plain storage
 * until something needs to react to being written, so the map can stay a
 * single array and grow hooks where they turn out to be needed.
 *
 * ponytail: flat 16 MB, no region dispatch, and exactly one register with
 * behaviour -- the serial status the boot ROM refuses to proceed without. The
 * rest of the I/O block at 0xFFFE00 (timers, the LCD controller, the flash
 * chip select) gets modelled when something is measured waiting on it, not
 * before.
 */
#include <stdlib.h>
#include <string.h>

#include "cybikorecomp/h8s.h"

int cy_init(cy_t *c)
{
    memset(c, 0, sizeof(*c));
    cy_io_reset(c);
    c->mem = (uint8_t *)calloc(CY_MEM_SIZE, 1);
    return c->mem ? 0 : -1;
}

void cy_free(cy_t *c)
{
    free(c->mem);
    c->mem = NULL;
}

int cy_load(cy_t *c, uint32_t addr, const void *data, uint32_t len)
{
    if ((uint64_t)addr + len > CY_MEM_SIZE)
        return -1;
    memcpy(c->mem + addr, data, len);
    return 0;
}

uint8_t cy_read8(cy_t *c, uint32_t a)
{
    uint8_t v;
    a &= CY_ADDR_MASK;
    if (cy_io_read(c, a, &v))
        return v;
    return c->mem[a];
}

uint16_t cy_read16(cy_t *c, uint32_t a)
{
    a &= CY_ADDR_MASK;
    return (uint16_t)((c->mem[a] << 8) | c->mem[(a + 1) & CY_ADDR_MASK]);
}

uint32_t cy_read32(cy_t *c, uint32_t a)
{
    a &= CY_ADDR_MASK;
    return ((uint32_t)c->mem[a] << 24)
         | ((uint32_t)c->mem[(a + 1) & CY_ADDR_MASK] << 16)
         | ((uint32_t)c->mem[(a + 2) & CY_ADDR_MASK] << 8)
         |  (uint32_t)c->mem[(a + 3) & CY_ADDR_MASK];
}

void cy_write8(cy_t *c, uint32_t a, uint8_t v)
{
    a &= CY_ADDR_MASK;
    if (cy_io_write(c, a, v))
        return;
    c->mem[a] = v;
}

void cy_write16(cy_t *c, uint32_t a, uint16_t v)
{
    a &= CY_ADDR_MASK;
    c->mem[a] = (uint8_t)(v >> 8);
    c->mem[(a + 1) & CY_ADDR_MASK] = (uint8_t)v;
}

void cy_write32(cy_t *c, uint32_t a, uint32_t v)
{
    a &= CY_ADDR_MASK;
    c->mem[a] = (uint8_t)(v >> 24);
    c->mem[(a + 1) & CY_ADDR_MASK] = (uint8_t)(v >> 16);
    c->mem[(a + 2) & CY_ADDR_MASK] = (uint8_t)(v >> 8);
    c->mem[(a + 3) & CY_ADDR_MASK] = (uint8_t)v;
}

/* The H8S Bcc table, in encoding order. Only the ones the emitter does not
 * special-case reach here, but all sixteen are defined so a generated switch
 * never has a hole. */
int cy_cond(const cy_t *c, int cc)
{
    switch (cc & 0xF) {
    case 0x0: return 1;                              /* bra */
    case 0x1: return 0;                              /* brn */
    case 0x2: return !(c->cf | c->zf);               /* bhi */
    case 0x3: return  (c->cf | c->zf);               /* bls */
    case 0x4: return !c->cf;                         /* bcc */
    case 0x5: return  c->cf;                         /* bcs */
    case 0x6: return !c->zf;                         /* bne */
    case 0x7: return  c->zf;                         /* beq */
    case 0x8: return !c->vf;                         /* bvc */
    case 0x9: return  c->vf;                         /* bvs */
    case 0xA: return !c->nf;                         /* bpl */
    case 0xB: return  c->nf;                         /* bmi */
    case 0xC: return !(c->nf ^ c->vf);               /* bge */
    case 0xD: return  (c->nf ^ c->vf);               /* blt */
    case 0xE: return !((c->nf ^ c->vf) | c->zf);     /* bgt */
    default:  return  ((c->nf ^ c->vf) | c->zf);     /* ble */
    }
}
