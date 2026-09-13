/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*******************************************************************************
 * OCH SEP Common Header
 *
 * Register access macros for OCH SEP firmware and tests. WRITE_REG/READ_REG
 * take the absolute addresses that sep.h / sep_addr.h provide; no base offset
 * is added.
 *
 ******************************************************************************/

#ifndef OCH_SEP_COMMON_H
#define OCH_SEP_COMMON_H

#include <stdint.h>

//==============================================================================
// Register Access Macros - 32-bit
//==============================================================================

/**
 * Write a 32-bit value to a register at the specified address
 *
 * @param addr  Absolute address of the register (from sep.h / sep_addr.h)
 * @param value 32-bit value to write
 *
 * Example:
 *   WRITE_REG(OCH_SEP_TOP_OTBN_CMD_BASE_ADDR, OTBN_CMD_EXECUTE);
 */
#define WRITE_REG(addr, value) (*((volatile uint32_t *)(uintptr_t)(addr)) = (value))

/**
 * Read a 32-bit value from a register at the specified address
 *
 * @param addr Absolute address of the register (from sep.h / sep_addr.h)
 * @return     32-bit value read from the register
 *
 * Example:
 *   uint32_t status = READ_REG(OCH_SEP_TOP_OTBN_STATUS_BASE_ADDR);
 */
#define READ_REG(addr) (*((volatile uint32_t *)(uintptr_t)(addr)))

/**
 * Alias for WRITE_REG
 */
#define WRITE32(addr, value) WRITE_REG(addr, value)

/**
 * Alias for READ_REG
 */
#define READ32(addr) READ_REG(addr)

//==============================================================================
// Register Access Macros - 64-bit
//==============================================================================

/**
 * Write a 64-bit value to a register at the specified address
 *
 * @param addr  Absolute address of the register (from sep.h / sep_addr.h)
 * @param value 64-bit value to write
 *
 * Example:
 *   WRITE_REG64(SOME_64BIT_REG_ADDR, value64);
 */
#define WRITE_REG64(addr, value) (*((volatile uint64_t *)(uintptr_t)(addr)) = (value))

/**
 * Read a 64-bit value from a register at the specified address
 *
 * @param addr Absolute address of the register (from sep.h / sep_addr.h)
 * @return     64-bit value read from the register
 *
 * Example:
 *   uint64_t value = READ_REG64(SOME_64BIT_REG_ADDR);
 */
#define READ_REG64(addr) (*((volatile uint64_t *)(uintptr_t)(addr)))

/**
 * Alias for WRITE_REG64
 */
#define WRITE64(addr, value) WRITE_REG64(addr, value)

/**
 * Alias for READ_REG64
 */
#define READ64(addr) READ_REG64(addr)

//==============================================================================
// Memory Access Macros
//==============================================================================

/**
 * Write data to memory using word (32-bit) access
 *
 * @param base_addr Base address of the memory
 * @param word_idx  Word index (0-based)
 * @param value     32-bit value to write
 */
#define WRITE_MEM_WORD(base_addr, word_idx, value) WRITE_REG((base_addr) + ((word_idx)*4), (value))

/**
 * Read data from memory using word (32-bit) access
 *
 * @param base_addr Base address of the memory
 * @param word_idx  Word index (0-based)
 * @return          32-bit value read from memory
 */
#define READ_MEM_WORD(base_addr, word_idx) READ_REG((base_addr) + ((word_idx)*4))

//==============================================================================
// Bitfield Manipulation Macros
//==============================================================================

/**
 * Set bits in a register (read-modify-write)
 */
#define SET_BITS(addr, mask) WRITE_REG(addr, READ_REG(addr) | (mask))

/**
 * Clear bits in a register (read-modify-write)
 */
#define CLEAR_BITS(addr, mask) WRITE_REG(addr, READ_REG(addr) & ~(mask))

/**
 * Toggle bits in a register (read-modify-write)
 */
#define TOGGLE_BITS(addr, mask) WRITE_REG(addr, READ_REG(addr) ^ (mask))

/**
 * Read-modify-write: clear bits specified by mask, then set bits from value
 */
#define MODIFY_BITS(addr, mask, value) \
    WRITE_REG(addr, (READ_REG(addr) & ~(mask)) | ((value) & (mask)))

//==============================================================================
// Polling/Wait Macros
//==============================================================================

/**
 * Poll a register until a condition is met (with timeout)
 *
 * @param addr      Register address to poll
 * @param mask      Bit mask to check
 * @param expected  Expected value (after masking)
 * @param timeout   Maximum number of iterations
 * @return          0 if condition met, -1 if timeout
 */
static inline int poll_reg_timeout(uintptr_t addr, uint32_t mask, uint32_t expected, int timeout) {
    while (timeout-- > 0) {
        if ((READ_REG(addr) & mask) == expected) {
            return 0;
        }
    }
    return -1; // Timeout
}

/**
 * Wait for a register bit to be set
 */
#define WAIT_FOR_BIT_SET(addr, bit, timeout) \
    poll_reg_timeout((addr), (1U << (bit)), (1U << (bit)), (timeout))

/**
 * Wait for a register bit to be clear
 */
#define WAIT_FOR_BIT_CLEAR(addr, bit, timeout) poll_reg_timeout((addr), (1U << (bit)), 0, (timeout))

//==============================================================================
// Address Validation (Optional - for debug builds)
//==============================================================================

#ifdef OCH_SEP_DEBUG_REG_ACCESS
#define CHECK_REG_ADDR(addr) \
    do { \
        if ((addr) < 0x40000000 || (addr) >= 0x50000000) { \
            /* Address out of expected OCH SEP range */ \
            __builtin_trap(); \
        } \
    } while (0)
#else
#define CHECK_REG_ADDR(addr) ((void)0)
#endif

/*
 * Usage in firmware/tests:
 *   #include "sep.h"            // absolute register addresses
 *   #include "och_sep_common.h" // register access macros
 *
 *   WRITE_REG(OCH_SEP_TOP_OTBN_CMD_BASE_ADDR, OTBN_CMD_EXECUTE);
 *   uint32_t status = READ_REG(OCH_SEP_TOP_OTBN_STATUS_BASE_ADDR);
 */

#endif // OCH_SEP_COMMON_H
