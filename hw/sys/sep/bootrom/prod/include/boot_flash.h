/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

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
#include "sep.h"    /* SEP_TOP_SEP_SRAM_BASE_ADDR / SEP_TOP_SEP_SRAM_SIZE   */
#include "harden.h" /* fault-injection value launder (harden_u32)  */

/*
 * Boot-slot geometry on the SPI medium. A property of the flash layout, not of
 * the manifest format.
 *
 * Flash carries two independent boot slots, so a primary that fails validation
 * -- bad signature, revoked key, corrupt payload -- can be recovered from a
 * complete second copy. The `rotate_update` strap swaps which is tried first.
 * A slot opens with the SPI configuration TLV the Cadence controller reads
 * during bring-up; the manifest follows it, and the manifest's own
 * payload_offset field locates the payload after that.
 *
 *   slot 0   +0x00000  SPI configuration TLV
 *            +0x01000  manifest, then payload   <- PRIMARY_MANIFEST_OFFSET
 *   slot 1   +0x00000  SPI configuration TLV
 *            +0x01000  manifest, then payload   <- BACKUP_MANIFEST_OFFSET
 *
 * BOOT_SLOT_SIZE is the knob. It is the stride from one slot to the next, and
 * so the room a single manifest+payload bundle has to grow into. Raise it to
 * give a slot more space (pushing the backup further out), lower it to fit both
 * slots on a smaller part.
 *
 * Its ceiling is SEP SRAM: the ROM stages a slot's manifest and payload into
 * SRAM to authenticate them, so a slot bigger than SEP_TOP_SEP_SRAM_SIZE
 * has space the ROM can never consume. The default takes that ceiling exactly,
 * which is the reasoning behind the historical 0x40000 stride. The assertions
 * below are the only hard constraints; everything else is policy.
 *
 * Changing this moves no image by itself. The producer places the bundles --
 * configs/oca_*_image.yaml, keys manifest_offset / payload_offset / total_size
 * -- and those must be edited to match, or the ROM finds padding where the
 * backup manifest should be. doc/rom.adoc's boot-flash-layout table is
 * normative for producers and carries the same offsets.
 */
#ifndef BOOT_SLOT_SIZE
#define BOOT_SLOT_SIZE 0x40000u
#endif
#ifndef BOOT_SLOT_MANIFEST_OFFSET
#define BOOT_SLOT_MANIFEST_OFFSET 0x1000u
#endif

_Static_assert(BOOT_SLOT_SIZE <= (uint32_t)SEP_TOP_SEP_SRAM_SIZE,
               "BOOT_SLOT_SIZE exceeds SEP SRAM; the ROM stages manifest+payload into SRAM, so "
               "a slot cannot usefully be larger than it");
_Static_assert(BOOT_SLOT_MANIFEST_OFFSET < BOOT_SLOT_SIZE,
               "BOOT_SLOT_MANIFEST_OFFSET must place the manifest inside its own slot");

#ifndef PRIMARY_MANIFEST_OFFSET
#define PRIMARY_MANIFEST_OFFSET (0u * BOOT_SLOT_SIZE + BOOT_SLOT_MANIFEST_OFFSET)
#endif
#ifndef BACKUP_MANIFEST_OFFSET
#define BACKUP_MANIFEST_OFFSET (1u * BOOT_SLOT_SIZE + BOOT_SLOT_MANIFEST_OFFSET)
#endif

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
#define SEP_SPI_BASE ((uint32_t)SEP_TOP_SEP_EXTERNAL_XIP_REGION_BASE_ADDR)
#endif
#ifndef SEP_SPI_MAX_SIZE
#define SEP_SPI_MAX_SIZE ((uint32_t)SEP_TOP_SEP_EXTERNAL_XIP_REGION_SIZE)
#endif
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

/* Bring up the selected controller. Returns 0 on success, or a status code on
 * failure (non-fatal to the caller, which may fall back to the backup slot). */
static inline uint32_t boot_flash_init(const struct boot_straps *straps, uint16_t sysclk_mhz) {
#if BOOT_SPI_CONTROLLER_OT
    (void)straps; /* slot rotation is applied by the loader, not the driver */
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
static inline uint32_t boot_flash_read(uint32_t dst, uint32_t flash_off, uint32_t len) {
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
static inline bool boot_flash_bounds_ok(uint32_t flash_off, uint32_t len, uint32_t dst,
                                        uint32_t dst_len) {
#if BOOT_SPI_CONTROLLER_OT
    /* Static bound: the read must stay within the boot slot it started in, and
     * the destination within SEP SRAM. The window runs from the slot's manifest
     * to the end of that slot, so it is the slot size less the manifest's offset
     * within the slot. Sizing it from BOOT_SLOT_SIZE rather than SEP SRAM keeps
     * the primary window from reaching into the backup slot should the slot size
     * ever be reduced; the two are equal at the default geometry, where a slot is
     * exactly one SRAM in size. */
    const uint32_t slot_span = (uint32_t)BOOT_SLOT_SIZE - (uint32_t)BOOT_SLOT_MANIFEST_OFFSET;
    const uint32_t sram_base = (uint32_t)SEP_TOP_SEP_SRAM_BASE_ADDR;
    const uint32_t sram_size = (uint32_t)SEP_TOP_SEP_SRAM_SIZE;

    bool flash_ok_1 =
        boot_flash_range_within(flash_off, len, (uint32_t)PRIMARY_MANIFEST_OFFSET, slot_span) ||
        boot_flash_range_within(flash_off, len, (uint32_t)BACKUP_MANIFEST_OFFSET, slot_span);
    bool dst_ok_1 = boot_flash_range_within(dst, dst_len, sram_base, sram_size);
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
    bool dst_ok_2 = boot_flash_range_within(dst2, dlen2, sram_base, sram_size);
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
    return boot_flash_range_within(src, len, (uint32_t)SEP_SPI_BASE, (uint32_t)SEP_SPI_MAX_SIZE);
#endif
}

#endif /* BOOT_FLASH_H */
