/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_persist.h
 * @brief ROM warm-persistent SRAM region (region 31, 0x7E00-0x7FFF).
 *
 * The highest 512 bytes of KM SRAM are reserved as a ROM-managed data structure
 * that survives warm reset. SRAM storage is cold-domain hardware, so contents
 * are physically preserved across any warm or soft reset; only a cold reset
 * (power-on) erases them. ROM cold-initializes this region exactly once per
 * cold boot (detected via COLD_BOOT_DONE) and leaves it intact on warm boots.
 *
 * Ownership: this region belongs exclusively to ROM firmware. It holds ROM
 * state that must survive warm reset; it is NOT general-purpose scratch for
 * mutable (SRAM-loaded) firmware. Mutable firmware must not place its own data
 * here, and once ROM write-locks the region (see below) mutable firmware cannot
 * write it at all. The rest of SRAM (below 0x7E00) is the mutable-firmware load
 * area, stack, and BSS/data.
 *
 * The region is placed in the `.rom_persist` linker section, which is mapped
 * to `0x0000_7E00` (top of SRAM) as a NOLOAD section so it never appears in the
 * ROM/VROM hex images.
 *
 * Before handing control to mutable (SRAM-loaded) firmware, the caller must
 * invoke `rom_persist_lock()` to write-lock region 31 via SRAM_LOCK.
 */

#ifndef ROM_PERSIST_H
#define ROM_PERSIST_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief ROM warm-persistent data structure.
 *
 * Placed at the top of SRAM (0x0000_7E00) in the `.rom_persist` section.
 * Cold-initialized to zero by rom_persist_cold_init(); preserved across
 * warm resets. Read and written only by ROM firmware.
 *
 * Fields are declared in order of priority. New fields must be appended
 * at the end to preserve the layout of existing fields.
 */
typedef struct {
    /** @brief Size in bytes of mutable firmware currently loaded in SRAM.
     *  Zero means no mutable firmware is loaded. Updated by the SRAM-firmware
     *  load command before handing off to mutable code. */
    uint32_t sram_fw_size;
} rom_persist_t;

/** @brief The single ROM warm-persist instance, anchored at the top of SRAM. */
extern rom_persist_t rom_persist;

/**
 * @brief Cold-initialize the warm-persist region.
 *
 * Zeros all fields. Must be called exactly once per cold boot, after the SRAM
 * scrambler is enabled (so SRAM writes are scrambler-consistent). Must NOT be
 * called on a warm boot — the region must be left intact.
 *
 * Caller (rom_boot_init) gates this with `if (!rom_kmcsr_cold_boot_done_read())`.
 */
void rom_persist_cold_init(void);

/**
 * @brief Read the loaded mutable-firmware size.
 *
 * @return Byte count of the mutable firmware image currently loaded in SRAM,
 *         or 0 if no mutable firmware is loaded.
 */
uint32_t rom_persist_get_sram_fw_size(void);

/**
 * @brief Set the loaded mutable-firmware size.
 *
 * Called by the SRAM-firmware load command after a successful load.
 *
 * @param size Byte count of the loaded image. Pass 0 to indicate no firmware.
 */
void rom_persist_set_sram_fw_size(uint32_t size);

/**
 * @brief Write-lock SRAM region 31, protecting the warm-persist region.
 *
 * Sets SRAM_LOCK bit 31 (ROM_KM_PERSIST_LOCK_MASK) via a triple write for
 * glitch resistance. Once set, writes to 0x7E00-0x7FFF are silently dropped
 * and trigger a SRAM_WRITE_LOCK_VIOLATION IRQ. The lock is cleared on the
 * next warm or cold reset, and ROM re-establishes it on every boot before
 * handing control to mutable firmware.
 */
void rom_persist_lock(void);

#ifdef __cplusplus
}
#endif

#endif /* ROM_PERSIST_H */
