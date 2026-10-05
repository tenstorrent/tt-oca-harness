/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file irq_common.h
 * @brief KMCSR and mailbox interrupt register accessors.
 */

#ifndef IRQ_COMMON_H
#define IRQ_COMMON_H

#include <stdint.h>
#include "key_manager_fw.h"

/** @brief KMCSR IRQ status register (volatile, W1C). */
#define KMCSR_IRQ_STATUS_REG \
    (*(volatile km_csr__irq_status_reg_t *)KEY_MANAGER_KMCSR_IRQ_STATUS_BASE_ADDR)
/** @brief KMCSR IRQ enable register (volatile). */
#define KMCSR_IRQ_ENABLE_REG \
    (*(volatile km_csr__irq_enable_reg_t *)KEY_MANAGER_KMCSR_IRQ_ENABLE_BASE_ADDR)
/** @brief KMCSR IRQ software-set register (volatile, single-pulse). */
#define KMCSR_IRQ_SET_REG (*(volatile km_csr__irq_set_reg_t *)KEY_MANAGER_KMCSR_IRQ_SET_BASE_ADDR)
/** @brief Mailbox IRQ status register (volatile, W1C). */
#define MBOX_IRQ_STATUS_REG \
    (*(volatile km_mailbox_km__irq_status_reg_t *)KEY_MANAGER_MAILBOX_KM_KM_IRQ_STATUS_BASE_ADDR)
/** @brief Mailbox IRQ enable register (volatile). */
#define MBOX_IRQ_ENABLE_REG \
    (*(volatile km_mailbox_km__irq_enable_reg_t *)KEY_MANAGER_MAILBOX_KM_KM_IRQ_ENABLE_BASE_ADDR)

/**
 * @brief Read the current IRQ status.
 *
 * @return Current KMCSR IRQ_STATUS register value.
 */
uint32_t rom_kmcsr_irq_status_read(void);

/**
 * @brief Clear IRQ status bits (write-1-to-clear).
 *
 * @param bits Bits to clear (W1C).
 */
void rom_kmcsr_irq_status_clear(uint32_t bits);

/**
 * @brief Read the current IRQ enable mask.
 *
 * @return Current KMCSR IRQ_ENABLE register value.
 */
uint32_t rom_kmcsr_irq_enable_read(void);

/**
 * @brief Set IRQ enable bits.
 *
 * @param value New IRQ enable mask.
 */
void rom_kmcsr_irq_enable_write(uint32_t value);

/**
 * @brief Set software interrupt bits via IRQ_SET register.
 *
 * All fields are single-pulse; writing 1 sets the corresponding
 * sticky IRQ_STATUS bit via hwset.
 *
 * @param bits Bits to set (single-pulse).
 */
void rom_kmcsr_irq_set(uint32_t bits);

/**
 * @brief Read mailbox IRQ status register.
 *
 * @return Raw IRQ status bits.
 */
uint32_t rom_mailbox_irq_status_read(void);

/**
 * @brief Clear mailbox IRQ status bits (write-1-to-clear).
 *
 * @param bits Bits to clear.
 */
void rom_mailbox_irq_status_clear(uint32_t bits);

/**
 * @brief Read mailbox IRQ enable register.
 *
 * @return Raw IRQ enable bits.
 */
uint32_t rom_mailbox_irq_enable_read(void);

/**
 * @brief Write mailbox IRQ enable register.
 *
 * @param bits New IRQ enable mask.
 */
void rom_mailbox_irq_enable_write(uint32_t bits);

#endif /* IRQ_COMMON_H */
