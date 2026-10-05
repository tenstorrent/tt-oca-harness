/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_mailbox.h
 * @brief Mailbox driver interface for Key Manager firmware.
 *
 * Provides register access wrappers for mailbox control, status, and data path.
 */

#ifndef ROM_MAILBOX_H
#define ROM_MAILBOX_H

#include <stdint.h>

#include "key_manager_fw.h"
#include "rom_defs.h"

/** @brief Outbound mailbox write-data register (volatile). */
#define ROM_MBOX_WRITE_DATA_REG \
    (*(volatile km_mailbox_km__write_data_reg_t *)KEY_MANAGER_MAILBOX_KM_KM_WRITE_DATA_BASE_ADDR)
/** @brief Outbound mailbox write-separator register (volatile). */
#define ROM_MBOX_WRITE_SEP_REG \
    (*(volatile km_mailbox_km__write_separator_reg_t *) \
         KEY_MANAGER_MAILBOX_KM_KM_WRITE_SEPARATOR_BASE_ADDR)
/** @brief Inbound mailbox read-data register (volatile). */
#define ROM_MBOX_READ_DATA_REG \
    (*(volatile km_mailbox_km__read_data_reg_t *)KEY_MANAGER_MAILBOX_KM_KM_READ_DATA_BASE_ADDR)
/** @brief Mailbox status register (volatile). */
#define ROM_MBOX_STATUS_REG \
    (*(volatile km_mailbox_km__status_reg_t *)KEY_MANAGER_MAILBOX_KM_KM_STATUS_BASE_ADDR)
/** @brief Mailbox control register (volatile). */
#define ROM_MBOX_CTRL_REG \
    (*(volatile km_mailbox_km__ctrl_reg_t *)KEY_MANAGER_MAILBOX_KM_KM_CTRL_BASE_ADDR)

/**
 * @brief Flush inbound and outbound mailbox FIFOs.
 */
void rom_mailbox_flush(void);

/**
 * @brief Check whether inbound mailbox FIFO is empty.
 *
 * @return 1 if empty, 0 otherwise.
 */
uint8_t rom_mailbox_inbound_empty(void);

/**
 * @brief Read number of words currently in the inbound FIFO.
 *
 * @return Inbound FIFO fill level (0 when empty).
 */
uint32_t rom_mailbox_inbound_depth_read(void);

/**
 * @brief Read number of words currently in the outbound FIFO.
 *
 * @return Outbound FIFO fill level (0 when empty).
 */
uint32_t rom_mailbox_outbound_depth_read(void);

/**
 * @brief Read number of free word slots in the outbound FIFO.
 *
 * Used by the mailbox ISR to cap the TX drain: transfer only whole frames
 * that fit in this space.
 *
 * @return Outbound FIFO free space (0 when full).
 */
uint32_t rom_mailbox_outbound_space_available_read(void);

/**
 * @brief Read inbound separator indicator from mailbox status register.
 *
 * @return 1 if separator is asserted, 0 otherwise.
 */
uint8_t rom_mailbox_inbound_separator(void);

/**
 * @brief Read one word from inbound mailbox FIFO.
 *
 * @return 32-bit data word.
 */
uint32_t rom_mailbox_read_data(void);

/**
 * @brief Assert outbound separator flag for the next write.
 */
void rom_mailbox_set_write_separator(void);

/**
 * @brief Write one word to outbound mailbox FIFO.
 *
 * @param word Data word to write.
 */
void rom_mailbox_write_data(uint32_t word);

#endif /* ROM_MAILBOX_H */
