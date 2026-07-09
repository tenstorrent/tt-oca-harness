/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_mailbox.c
 * @brief Mailbox driver for Key Manager firmware.
 */

#include "rom_mailbox.h"

/**
 * @brief Flush inbound and outbound mailbox FIFOs.
 *
 * Asserts CTRL.flush and spins until the hardware clears the bit,
 * ensuring subsequent WRITE_DATA words are not discarded by a
 * still-active flush.
 */
void rom_mailbox_flush(void) {
    km_mailbox_km__ctrl_reg_t ctrl = {0};
    ctrl.f.flush = 1;
    ROM_MBOX_CTRL_REG.w = ctrl.w;
    while (ROM_MBOX_CTRL_REG.f.flush) {
    }
}

/**
 * @brief Check whether inbound mailbox FIFO is empty.
 *
 * @return 1 if empty, 0 otherwise.
 */
uint8_t rom_mailbox_inbound_empty(void) {
    return ROM_MBOX_STATUS_REG.f.inbound_empty ? 1u : 0u;
}

/**
 * @brief Read number of words currently in the inbound FIFO.
 *
 * @return Inbound FIFO fill level (0 when empty).
 */
uint32_t rom_mailbox_inbound_depth_read(void) {
    return (uint32_t)ROM_MBOX_STATUS_REG.f.inbound_depth;
}

/**
 * @brief Read number of words currently in the outbound FIFO.
 *
 * @return Outbound FIFO fill level (0 when empty).
 */
uint32_t rom_mailbox_outbound_depth_read(void) {
    return (uint32_t)ROM_MBOX_STATUS_REG.f.outbound_depth;
}

/**
 * @brief Read number of free word slots in the outbound FIFO.
 *
 * Used by the mailbox ISR to cap the TX drain: transfer only whole frames
 * that fit in this space.
 *
 * @return Outbound FIFO free space (0 when full).
 */
uint32_t rom_mailbox_outbound_space_available_read(void) {
    return (uint32_t)ROM_KM_MAILBOX_FIFO_DEPTH - rom_mailbox_outbound_depth_read();
}

/**
 * @brief Read inbound separator indicator from mailbox status register.
 *
 * @return 1 if separator is asserted, 0 otherwise.
 */
uint8_t rom_mailbox_inbound_separator(void) {
    return ROM_MBOX_STATUS_REG.f.inbound_separator ? 1u : 0u;
}

/**
 * @brief Read one word from inbound mailbox FIFO.
 *
 * @return 32-bit data word.
 */
uint32_t rom_mailbox_read_data(void) {
    return ROM_MBOX_READ_DATA_REG.w;
}

/**
 * @brief Assert outbound separator flag for the next write.
 */
void rom_mailbox_set_write_separator(void) {
    ROM_MBOX_WRITE_SEP_REG.w = 1u;
}

/**
 * @brief Write one word to outbound mailbox FIFO.
 *
 * @param[in] word Data word to write.
 */
void rom_mailbox_write_data(uint32_t word) {
    ROM_MBOX_WRITE_DATA_REG.w = word;
}
