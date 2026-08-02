/*
 * Boot flash transport shim.
 *
 * The manifest loader reads the manifest and payload from flash without caring
 * which SPI controller is fitted. This header selects the controller at build
 * time (BOOT_SPI_CONTROLLER_OT) and presents one small interface in flash-offset
 * terms:
 *   - Cadence xSPI (default): flash is memory-mapped (XIP); a read is a DMA copy
 *     from SEP_SPI_BASE + offset.
 *   - OpenTitan SPI host: no memory-mapped window; a read is a command/FIFO
 *     transfer that streams into SRAM.
 *
 * Freestanding ROM: no libc, no heap.
 */
#ifndef BOOT_FLASH_H
#define BOOT_FLASH_H

#include <stdbool.h>
#include <stdint.h>

#include "boot_straps.h"
#include "manifest.h"          /* SEP_SPI_BASE, PRIMARY/BACKUP_MANIFEST_OFFSET */
#include "och_sep_top_reg.h"   /* SEP_SRAM_MEM_BASE_ADDR / SEP_SRAM_MEM_SIZE   */
#include "harden.h"            /* fault-injection value launder (harden_u32)  */

#if BOOT_SPI_CONTROLLER_OT
#include "sep_ot_spi.h"
/* RX-FIFO drain method for the OpenTitan controller: 0 = secure DMA (default),
 * 1 = CPU programmed I/O. Selected at build time. */
#ifndef BOOT_OT_SPI_USE_PIO
#define BOOT_OT_SPI_USE_PIO 0
#endif
#else
#include "sep_spi.h"
#include "sep_dma.h"
/* Cadence xSPI XIP window (memory-mapped flash), matching sep_dma.c. */
#ifndef SEP_SPI_BASE
#define SEP_SPI_BASE     ((uint32_t)SEP_AXI_EXTENSION_XIP_REGION_MEM_BASE_ADDR)
#endif
#ifndef SEP_SPI_MAX_SIZE
#define SEP_SPI_MAX_SIZE ((uint32_t)SEP_AXI_EXTENSION_XIP_REGION_MEM_SIZE)
#endif
#endif

/* True iff [addr, addr+len) lies within [base, base+size), with overflow guards.
 * A zero-length range is treated as in-bounds (no access is made). */
static inline bool boot_flash_range_within(uint32_t addr, uint32_t len,
                                           uint32_t base, uint32_t size) {
    if (len == 0u) {
        return true;
    }
    uint32_t end   = addr + len;   /* exclusive */
    uint32_t limit = base + size;  /* exclusive */
    if (end < addr || limit < base) {
        return false;              /* address overflow */
    }
    return (addr >= base) && (end <= limit);
}

/* Bring up the selected controller. Returns 0 on success, or a status code on
 * failure (non-fatal to the caller, which may fall back to the backup slot). */
static inline uint32_t boot_flash_init(const struct boot_straps *straps,
                                       uint16_t sysclk_mhz) {
#if BOOT_SPI_CONTROLLER_OT
    (void)straps;  /* slot rotation is applied by the loader, not the driver */
    ot_spi_set_sysclk(sysclk_mhz);
    return ot_spi_init();
#else
    spi_set_sysclk(sysclk_mhz);
    spi_set_rotate(straps->rotate_update);
    return spi_init();
#endif
}

/* Read `len` bytes at flash byte-offset `flash_off` into SRAM `dst`.
 * Returns 0 on success or a transport status code. */
static inline uint32_t boot_flash_read(uint32_t dst, uint32_t flash_off,
                                       uint32_t len) {
#if BOOT_SPI_CONTROLLER_OT
    /* The OpenTitan controller can drain the RX FIFO either with the secure DMA
     * (BOOT_OT_SPI_USE_PIO=0, default) or by CPU programmed I/O. Both read the
     * same bytes; the choice trades DMA offload against a simpler CPU-driven copy. */
#if BOOT_OT_SPI_USE_PIO
    return ot_spi_flash_read(flash_off, dst, len);
#else
    return ot_spi_flash_read_dma(flash_off, dst, len);
#endif
#else
    return sep_dma_copy(dst, (uint32_t)SEP_SPI_BASE + flash_off, len);
#endif
}

/* Re-bring-up the selected controller between manifest-slot attempts. Returns 0
 * on success or a status code. */
static inline uint32_t boot_flash_reinit(void) {
#if BOOT_SPI_CONTROLLER_OT
    return ot_spi_reinit();
#else
    return spi_reinit();
#endif
}

/* Validate a read before it is issued. Returns true iff it is in bounds. This is
 * a security gate, so the decision is evaluated twice — the second time over
 * optimizer-opaque operands (harden_u32, see harden.h) so the two evaluations
 * cannot be merged — and defaults to reject if they disagree (fault-injection
 * hardening). */
static inline bool boot_flash_bounds_ok(uint32_t flash_off, uint32_t len,
                                        uint32_t dst, uint32_t dst_len) {
#if BOOT_SPI_CONTROLLER_OT
    /* Static bound: the read must stay within a known primary/backup boot-slot
     * window, and the destination within SEP SRAM. A slot's flash span cannot
     * exceed the max staged size (header + payload <= SEP SRAM). */
    const uint32_t slot_span = (uint32_t)SEP_SRAM_MEM_SIZE;
    const uint32_t sram_base = (uint32_t)SEP_SRAM_MEM_BASE_ADDR;
    const uint32_t sram_size = (uint32_t)SEP_SRAM_MEM_SIZE;

    bool flash_ok_1 =
        boot_flash_range_within(flash_off, len, (uint32_t)PRIMARY_MANIFEST_OFFSET, slot_span) ||
        boot_flash_range_within(flash_off, len, (uint32_t)BACKUP_MANIFEST_OFFSET,  slot_span);
    bool dst_ok_1  = boot_flash_range_within(dst, dst_len, sram_base, sram_size);
    bool ok_first  = flash_ok_1 && dst_ok_1;

    /* Independent re-evaluation over optimizer-opaque copies of the operands, so
     * the compiler cannot prove this equal to the first and fold the two into a
     * single computation; disagreement ⇒ reject. */
    uint32_t off2  = harden_u32(flash_off);
    uint32_t len2  = harden_u32(len);
    uint32_t dst2  = harden_u32(dst);
    uint32_t dlen2 = harden_u32(dst_len);
    bool flash_ok_2 =
        boot_flash_range_within(off2, len2, (uint32_t)PRIMARY_MANIFEST_OFFSET, slot_span) ||
        boot_flash_range_within(off2, len2, (uint32_t)BACKUP_MANIFEST_OFFSET,  slot_span);
    bool dst_ok_2  = boot_flash_range_within(dst2, dlen2, sram_base, sram_size);
    bool ok_second = flash_ok_2 && dst_ok_2;

    if (ok_first != ok_second) {
        return false;
    }
    return ok_first;
#else
    /* Cadence: flash is memory-mapped; the read source must lie within the XIP
     * region. (Destination is checked by sep_dma_copy.) */
    (void)dst;
    (void)dst_len;
    uint32_t src = (uint32_t)SEP_SPI_BASE + flash_off;
    return boot_flash_range_within(src, len, (uint32_t)SEP_SPI_BASE,
                                   (uint32_t)SEP_SPI_MAX_SIZE);
#endif
}

#endif /* BOOT_FLASH_H */
