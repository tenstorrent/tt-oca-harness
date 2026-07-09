/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file irq_common.c
 * @brief KMCSR and mailbox interrupt register accessors.
 */

#include "irq_common.h"

/**
 * @brief Read the current IRQ status.
 *
 * @return Current KMCSR IRQ_STATUS register value.
 */
uint32_t rom_kmcsr_irq_status_read(void) {
    return KMCSR_IRQ_STATUS_REG.w;
}

/**
 * @brief Clear IRQ status bits (write-1-to-clear).
 *
 * @param[in] bits Bits to clear (W1C).
 */
void rom_kmcsr_irq_status_clear(uint32_t bits) {
    KMCSR_IRQ_STATUS_REG.w = bits;
}

/**
 * @brief Read the current IRQ enable mask.
 *
 * @return Current KMCSR IRQ_ENABLE register value.
 */
uint32_t rom_kmcsr_irq_enable_read(void) {
    return KMCSR_IRQ_ENABLE_REG.w;
}

/**
 * @brief Set IRQ enable bits.
 *
 * @param[in] value New IRQ enable mask.
 */
void rom_kmcsr_irq_enable_write(uint32_t value) {
    KMCSR_IRQ_ENABLE_REG.w = value;
}

/**
 * @brief Set software interrupt bits via IRQ_SET register.
 *
 * All fields are single-pulse; writing 1 sets the corresponding
 * sticky IRQ_STATUS bit via hwset.
 *
 * @param[in] bits Bits to set (single-pulse).
 */
void rom_kmcsr_irq_set(uint32_t bits) {
    KMCSR_IRQ_SET_REG.w = bits;
}

/**
 * @brief Read mailbox IRQ status register.
 *
 * @return Raw IRQ status bits.
 */
uint32_t rom_mailbox_irq_status_read(void) {
    return MBOX_IRQ_STATUS_REG.w;
}

/**
 * @brief Clear mailbox IRQ status bits (write-1-to-clear).
 *
 * @param[in] bits Bits to clear.
 */
void rom_mailbox_irq_status_clear(uint32_t bits) {
    MBOX_IRQ_STATUS_REG.w = bits;
}

/**
 * @brief Read mailbox IRQ enable register.
 *
 * @return Raw IRQ enable bits.
 */
uint32_t rom_mailbox_irq_enable_read(void) {
    return MBOX_IRQ_ENABLE_REG.w;
}

/**
 * @brief Write mailbox IRQ enable register.
 *
 * @param[in] bits New IRQ enable mask.
 */
void rom_mailbox_irq_enable_write(uint32_t bits) {
    MBOX_IRQ_ENABLE_REG.w = bits;
}
