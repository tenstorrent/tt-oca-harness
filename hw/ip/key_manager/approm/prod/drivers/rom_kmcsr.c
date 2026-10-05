/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_kmcsr.c
 * @brief KMCSR driver for Key Manager firmware.
 */

#include "rom_kmcsr.h"

/**
 * @brief Read KMCSR hardware version register.
 *
 * @return Raw version register value.
 */
uint32_t rom_kmcsr_version_read(void) {
    return ROM_KMCSR_VERSION_REG.w;
}

/**
 * @brief Read KMCSR RECOVERABLE_ERR bit.
 *
 * @return 1 if RECOVERABLE_ERR is set, 0 otherwise.
 */
uint8_t rom_kmcsr_recoverable_err_bit_read(void) {
    return ROM_KMCSR_RECOVERABLE_ERR_REG.f.recoverable_err ? 1u : 0u;
}

/**
 * @brief Set or clear KMCSR RECOVERABLE_ERR bit.
 *
 * @param[in] value Non-zero sets the bit; zero clears it.
 */
void rom_kmcsr_recoverable_err_bit_write(uint8_t value) {
    km_csr__recoverable_err_reg_t reg;
    reg.w = ROM_KMCSR_RECOVERABLE_ERR_REG.w;
    reg.f.recoverable_err = value ? 1u : 0u;
    ROM_KMCSR_RECOVERABLE_ERR_REG.w = reg.w;
}

/**
 * @brief Read KMCSR SRAM scrambler enable bit.
 *
 * @return 1 if enabled, 0 otherwise.
 */
uint8_t rom_kmcsr_sram_scrambler_enable_bit_read(void) {
    return ROM_KMCSR_SCRAMBLER_CTRL_REG.f.enable ? 1u : 0u;
}

/**
 * @brief Write one word to the SRAM scrambler key register.
 *
 * @param[in] word Random key word.
 */
void rom_kmcsr_sram_scrambler_key_write(uint32_t word) {
    ROM_KMCSR_SCRAMBLER_KEY_REG.w = word;
}

/**
 * @brief Read KMCSR IRQ_ENTRY_ADDR.
 *
 * @return Programmed IRQ entry address.
 */
uint32_t rom_kmcsr_irq_entry_addr_read(void) {
    return ROM_KMCSR_IRQ_ENTRY_ADDR_REG.f.addr;
}

/**
 * @brief Write KMCSR IRQ_ENTRY_ADDR.
 *
 * @param addr Value for the `addr` field.
 */
void rom_kmcsr_irq_entry_addr_write(uint32_t addr) {
    km_csr__irq_entry_addr_reg_t w = {0};
    w.f.addr = addr;
    ROM_KMCSR_IRQ_ENTRY_ADDR_REG.w = w.w;
}

/**
 * @brief Read KMCSR IRQ_ENTRY_LOCK.lock.
 *
 * @return 1 if locked, 0 if not locked.
 */
uint8_t rom_kmcsr_irq_entry_lock_read(void) {
    return ROM_KMCSR_IRQ_ENTRY_LOCK_REG.f.lock ? 1u : 0u;
}

/**
 * @brief Set KMCSR IRQ_ENTRY_LOCK (write-1 to lock).
 */
void rom_kmcsr_irq_entry_lock_set(void) {
    km_csr__irq_entry_lock_reg_t w = {0};
    w.f.lock = 1u;
    ROM_KMCSR_IRQ_ENTRY_LOCK_REG.w = w.w;
}

/**
 * @brief Read BOOT_STATUS.COLD_BOOT_DONE bit.
 *
 * @return 1 if COLD_BOOT_DONE is set, 0 otherwise.
 */
uint8_t rom_kmcsr_cold_boot_done_read(void) {
    return ROM_KMCSR_BOOT_STATUS_REG.f.cold_boot_done ? 1u : 0u;
}

/**
 * @brief Mark cold boot as complete (write-1-only; sticky until cold reset).
 */
void rom_kmcsr_cold_boot_done_set(void) {
    km_csr__boot_status_reg_t w = {0};
    w.f.cold_boot_done = 1u;
    ROM_KMCSR_BOOT_STATUS_REG.w = w.w;
}
