/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#ifndef ROM_PERSIST_H
#define ROM_PERSIST_H

#include <stdint.h>
#include "key_manager_addr.h"

#define ROM_PERSIST_SRAM_FW_SIZE_ADDR 0x00007E00u
#define ROM_PERSIST_LOCK_REGION_BIT 31u
#define ROM_KM_PERSIST_LOCK_MASK (1u << ROM_PERSIST_LOCK_REGION_BIT)

static inline volatile uint32_t *rom_persist_sram_fw_size_ptr(void) {
    return (volatile uint32_t *)ROM_PERSIST_SRAM_FW_SIZE_ADDR;
}

static inline void rom_persist_cold_init(void) {
    *rom_persist_sram_fw_size_ptr() = 0;
}

static inline void rom_persist_set_sram_fw_size(uint32_t size_bytes) {
    *rom_persist_sram_fw_size_ptr() = size_bytes;
}

static inline uint32_t rom_persist_get_sram_fw_size(void) {
    return *rom_persist_sram_fw_size_ptr();
}

static inline void rom_persist_lock(void) {
    *(volatile uint32_t *)KEY_MANAGER_KMCSR_SRAM_LOCK_BASE_ADDR = ROM_KM_PERSIST_LOCK_MASK;
}

#endif /* ROM_PERSIST_H */
