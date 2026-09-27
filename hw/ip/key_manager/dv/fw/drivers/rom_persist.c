/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_persist.c
 * @brief ROM warm-persistent SRAM region driver.
 */

#include "rom_persist.h"
#include "rom_defs.h"
#include "rom_kmcsr.h"

/* Place the instance at the start of the .rom_persist section, which the
 * linker fixes at 0x0000_FC00 (top of SRAM, region 31). The `used` attribute
 * prevents the compiler from discarding it when there are no direct references
 * in a given translation unit. */
rom_persist_t rom_persist __attribute__((section(".rom_persist"), used));

/**
 * @brief Cold-initialize the warm-persist region.
 */
void rom_persist_cold_init(void) {
    rom_persist = (rom_persist_t){0};
}

/**
 * @brief Read the loaded mutable-firmware size.
 */
uint32_t rom_persist_get_sram_fw_size(void) {
    return rom_persist.sram_fw_size;
}

/**
 * @brief Set the loaded mutable-firmware size.
 */
void rom_persist_set_sram_fw_size(uint32_t size) {
    rom_persist.sram_fw_size = size;
}

/**
 * @brief Write-lock SRAM region 31 (warm-persist region).
 *
 * Triple write for glitch resistance (matches rom_kmcsr_sram_lock_set
 * convention). Called from the SRAM-firmware handover path.
 */
void rom_persist_lock(void) {
    rom_kmcsr_sram_lock_set(ROM_KM_PERSIST_LOCK_MASK);
}
