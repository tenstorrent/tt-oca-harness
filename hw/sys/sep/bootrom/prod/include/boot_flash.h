/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Boot flash transport shim.
 *
 * Presents the manifest loader one interface in flash-offset terms over the
 * OpenTitan SPI host. Flash is not memory-mapped, so a read is a command/FIFO
 * transfer that streams into SRAM rather than an address-space access.
 *
 * Freestanding ROM: no libc, no heap.
 */
#ifndef BOOT_FLASH_H
#define BOOT_FLASH_H

#include <stdbool.h>
#include <stdint.h>

#include "boot_straps.h"
#include "manifest.h" /* PRIMARY/BACKUP_MANIFEST_OFFSET */
#include "sep.h"      /* OCH_SEP_TOP_SEP_SRAM_BASE_ADDR / OCH_SEP_TOP_SEP_SRAM_SIZE   */
#include "sep_smc_interface.h" /* sep_get_smc_sram_base, SMC_SRAM_SIZE_BYTES */
#include "harden.h"   /* fault-injection value launder (harden_u32)  */
#include "sep_ot_spi.h"

/* RX-FIFO drain method: 0 = secure DMA (default), 1 = CPU programmed I/O.
 * Selected at build time. */
#ifndef BOOT_OT_SPI_USE_PIO
#define BOOT_OT_SPI_USE_PIO 0
#endif

/* True iff [addr, addr+len) lies within [base, base+size), with overflow guards.
 * A zero-length range is treated as in-bounds (no access is made). */
static inline bool boot_flash_range_within(uint32_t addr, uint32_t len, uint32_t base,
                                           uint32_t size) {
    if (len == 0u) {
        return true;
    }
    uint32_t end = addr + len;    /* exclusive */
    uint32_t limit = base + size; /* exclusive */
    if (end < addr || limit < base) {
        return false; /* address overflow */
    }
    return (addr >= base) && (end <= limit);
}

/* Bring up the SPI controller. Returns 0 on success, or a status code on
 * failure (non-fatal to the caller, which may fall back to the backup slot). */
static inline uint32_t boot_flash_init(const struct boot_straps *straps, uint16_t sysclk_mhz) {
    (void)straps; /* slot rotation is applied by the loader, not the driver */
    ot_spi_set_sysclk(sysclk_mhz);
    return ot_spi_init();
}

/* Read `len` bytes at flash byte-offset `flash_off` into SRAM `dst`.
 * Returns 0 on success or a transport status code. */
static inline uint32_t boot_flash_read(uint32_t dst, uint32_t flash_off, uint32_t len) {
    /* The RX FIFO drains either with the secure DMA (BOOT_OT_SPI_USE_PIO=0,
     * default) or by CPU programmed I/O. Both read the same bytes; the choice
     * trades DMA offload against a simpler CPU-driven copy. */
#if BOOT_OT_SPI_USE_PIO
    return ot_spi_flash_read(flash_off, dst, len);
#else
    return ot_spi_flash_read_dma(flash_off, dst, len);
#endif
}

/* Re-bring-up the SPI controller between manifest-slot attempts. Returns 0
 * on success or a status code. */
static inline uint32_t boot_flash_reinit(void) {
    return ot_spi_reinit();
}

/* Validate a read before it is issued. Returns true iff it is in bounds. This is
 * a security gate, so the decision is evaluated twice — the second time over
 * optimizer-opaque operands (harden_u32, see harden.h) so the two evaluations
 * cannot be merged — and defaults to reject if they disagree (fault-injection
 * hardening). */
static inline bool boot_flash_bounds_ok(uint32_t flash_off, uint32_t len, uint32_t dst,
                                        uint32_t dst_len) {
    /* Static bound: the read must stay within a known primary/backup boot-slot
     * window, and the destination within one of the two regions the driver can
     * stage into -- SEP SRAM, or SMC SRAM for a manifest asking use_ext_sram=0.
     * A slot's flash span cannot exceed the max staged size (header + payload <=
     * SEP SRAM). The region list here must stay in step with
     * ot_spi_dst_regions[] in sep_ot_spi.c, which is what programs the DMA. */
    const uint32_t slot_span = (uint32_t)OCH_SEP_TOP_SEP_SRAM_SIZE;
    const uint32_t sram_base = (uint32_t)OCH_SEP_TOP_SEP_SRAM_BASE_ADDR;
    const uint32_t sram_size = (uint32_t)OCH_SEP_TOP_SEP_SRAM_SIZE;
    const uint32_t smc_sram = sep_get_smc_sram_base();
    const uint32_t smc_size = (uint32_t)SMC_SRAM_SIZE_BYTES;

    bool flash_ok_1 =
        boot_flash_range_within(flash_off, len, (uint32_t)PRIMARY_MANIFEST_OFFSET, slot_span) ||
        boot_flash_range_within(flash_off, len, (uint32_t)BACKUP_MANIFEST_OFFSET, slot_span);
    bool dst_ok_1 = boot_flash_range_within(dst, dst_len, sram_base, sram_size) ||
                    boot_flash_range_within(dst, dst_len, smc_sram, smc_size);
    bool ok_first = flash_ok_1 && dst_ok_1;

    /* Independent re-evaluation over optimizer-opaque copies of the operands, so
     * the compiler cannot prove this equal to the first and fold the two into a
     * single computation; disagreement ⇒ reject. */
    uint32_t off2 = harden_u32(flash_off);
    uint32_t len2 = harden_u32(len);
    uint32_t dst2 = harden_u32(dst);
    uint32_t dlen2 = harden_u32(dst_len);
    bool flash_ok_2 =
        boot_flash_range_within(off2, len2, (uint32_t)PRIMARY_MANIFEST_OFFSET, slot_span) ||
        boot_flash_range_within(off2, len2, (uint32_t)BACKUP_MANIFEST_OFFSET, slot_span);
    bool dst_ok_2 = boot_flash_range_within(dst2, dlen2, sram_base, sram_size) ||
                    boot_flash_range_within(dst2, dlen2, smc_sram, smc_size);
    bool ok_second = flash_ok_2 && dst_ok_2;

    if (ok_first != ok_second) {
        return false;
    }
    return ok_first;
}

#endif /* BOOT_FLASH_H */
