/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_kmcsr.h
 * @brief KMCSR driver interface for Key Manager firmware.
 *
 * Provides helpers for KMCSR registers that are not part of interrupt
 * controller handling. IRQ_STATUS / IRQ_ENABLE / IRQ_SET access remains in
 * irq_common.h / irq_common.c.
 */

#ifndef ROM_KMCSR_H
#define ROM_KMCSR_H

#include <stdint.h>

#include "key_manager.h"
#include "key_manager_addr.h"

/** @brief KMCSR hardware version register (volatile, read-only). */
#define ROM_KMCSR_VERSION_REG \
    (*(volatile km_csr__version_reg_t *)KEY_MANAGER_KMCSR_VERSION_BASE_ADDR)
/** @brief KMCSR boot status register (volatile, write-1-only on COLD_BOOT_DONE field). */
#define ROM_KMCSR_BOOT_STATUS_REG \
    (*(volatile km_csr__boot_status_reg_t *)KEY_MANAGER_KMCSR_BOOT_STATUS_BASE_ADDR)
/** @brief KMCSR recoverable-error register (volatile, R/W). */
#define ROM_KMCSR_RECOVERABLE_ERR_REG \
    (*(volatile km_csr__recoverable_err_reg_t *)KEY_MANAGER_KMCSR_RECOVERABLE_ERR_BASE_ADDR)
/** @brief SRAM scrambler key register (volatile, write-only). */
#define ROM_KMCSR_SCRAMBLER_KEY_REG \
    (*(volatile km_csr__scrambler_key_reg_t *)KEY_MANAGER_KMCSR_SCRAMBLER_KEY_BASE_ADDR)
/** @brief SRAM scrambler control register (volatile, R/W). */
#define ROM_KMCSR_SCRAMBLER_CTRL_REG \
    (*(volatile km_csr__scrambler_ctrl_reg_t *)KEY_MANAGER_KMCSR_SCRAMBLER_CTRL_BASE_ADDR)
/** @brief Programmable IRQ vector address (volatile, R/W; SW-wel gated when lock is set). */
#define ROM_KMCSR_IRQ_ENTRY_ADDR_REG \
    (*(volatile km_csr__irq_entry_addr_reg_t *)KEY_MANAGER_KMCSR_IRQ_ENTRY_ADDR_BASE_ADDR)
/** @brief IRQ entry address lock (volatile; write-1 set, not cleared by writing 0). */
#define ROM_KMCSR_IRQ_ENTRY_LOCK_REG \
    (*(volatile km_csr__irq_entry_lock_reg_t *)KEY_MANAGER_KMCSR_IRQ_ENTRY_LOCK_BASE_ADDR)
/** @brief SRAM region write-lock register. */
#define ROM_KMCSR_SRAM_LOCK_REG \
    (*(volatile km_csr__sram_lock_reg_t *)KEY_MANAGER_KMCSR_SRAM_LOCK_BASE_ADDR)

/**
 * @brief Read KMCSR hardware version register.
 *
 * @return Raw version register value.
 */
uint32_t rom_kmcsr_version_read(void);

/**
 * @brief Read KMCSR RECOVERABLE_ERR bit.
 *
 * @return 1 if RECOVERABLE_ERR is set, 0 otherwise.
 */
uint8_t rom_kmcsr_recoverable_err_bit_read(void);

/**
 * @brief Set or clear KMCSR RECOVERABLE_ERR bit.
 *
 * @param value Non-zero sets the bit; zero clears it.
 */
void rom_kmcsr_recoverable_err_bit_write(uint8_t value);

/**
 * @brief Read KMCSR SRAM scrambler enable bit.
 *
 * @return 1 if enabled, 0 otherwise.
 */
uint8_t rom_kmcsr_sram_scrambler_enable_bit_read(void);

/**
 * @brief Write one word to the SRAM scrambler key register.
 *
 * @param word Random key word.
 */
void rom_kmcsr_sram_scrambler_key_write(uint32_t word);

/**
 * @brief Read `IRQ_ENTRY_ADDR` (programmed IRQ entry PC).
 *
 * @return Current `addr` field.
 */
uint32_t rom_kmcsr_irq_entry_addr_read(void);

/**
 * @brief Write `IRQ_ENTRY_ADDR` (ignored when `IRQ_ENTRY_LOCK` is set).
 *
 * @param addr Entry address to store in `addr`.
 */
void rom_kmcsr_irq_entry_addr_write(uint32_t addr);

/**
 * @brief Read `IRQ_ENTRY_LOCK.lock`.
 *
 * @return 1 if locked, 0 if unlocked.
 */
uint8_t rom_kmcsr_irq_entry_lock_read(void);

/**
 * @brief Set `IRQ_ENTRY_LOCK` (write 1 to `lock`; sticky until KM reset).
 */
void rom_kmcsr_irq_entry_lock_set(void);

static inline uint32_t rom_kmcsr_sram_lock_read(void) {
    return ROM_KMCSR_SRAM_LOCK_REG.w;
}

static inline void rom_kmcsr_sram_lock_set(uint32_t mask) {
    ROM_KMCSR_SRAM_LOCK_REG.w = mask;
}

/**
 * @brief Read BOOT_STATUS.COLD_BOOT_DONE bit.
 *
 * @return 1 if COLD_BOOT_DONE is set, 0 otherwise.
 */
uint8_t rom_kmcsr_cold_boot_done_read(void);

/**
 * @brief Mark cold boot as complete by writing 1 to BOOT_STATUS.COLD_BOOT_DONE.
 *
 * Write-1-only field: the hardware ignores writes of 0; the bit is sticky
 * until the next cold reset.  Warm resets do NOT clear this bit.
 */
void rom_kmcsr_cold_boot_done_set(void);

#endif /* ROM_KMCSR_H */
