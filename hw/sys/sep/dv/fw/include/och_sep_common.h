/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*******************************************************************************
 * OCH SEP Common Header
 *
 * This file provides common register access macros for OCH SEP firmware and tests.
 * Similar to tt_sep's sep_common.h but without the address offset.
 *
 * In tt_sep, WRITE_EXT/READ_EXT add SEP_EXT_BASE (0xc000_0000) to addresses.
 * In och_sep, WRITE_REG/READ_REG use addresses directly since sep.h / sep_addr.h
 * already provides absolute addresses.
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
 * Legacy alias for WRITE_REG (for compatibility)
 */
#define WRITE32(addr, value) WRITE_REG(addr, value)

/**
 * Legacy alias for READ_REG (for compatibility)
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
 * Legacy alias for WRITE_REG64 (for compatibility)
 */
#define WRITE64(addr, value) WRITE_REG64(addr, value)

/**
 * Legacy alias for READ_REG64 (for compatibility)
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

//==============================================================================
// Comparison with tt_sep
//==============================================================================
/*
 * tt_sep uses WRITE_EXT/READ_EXT which ADD SEP_EXT_BASE (0xc000_0000):
 *   #define SEP_EXT_BASE (0xc0000000)
 *   #define WRITE_EXT(addr, value) \
 *     (*((volatile uint32_t *)(uintptr_t)(SEP_EXT_BASE + addr)) = value)
 *   #define READ_EXT(addr) \
 *     (*((volatile uint32_t *)(uintptr_t)(SEP_EXT_BASE + addr)))
 *
 * och_sep uses WRITE_REG/READ_REG which use addresses DIRECTLY:
 *   #define WRITE_REG(addr, value) \
 *     (*((volatile uint32_t *)(uintptr_t)(addr)) = value)
 *   #define READ_REG(addr) \
 *     (*((volatile uint32_t *)(uintptr_t)(addr)))
 *
 * This is because sep.h / sep_addr.h already provides absolute addresses:
 *   #define OCH_SEP_TOP_OTBN_CMD_BASE_ADDR (0x40000010)  // Already absolute!
 *
 * Usage in firmware/tests:
 *   #include "sep.h"  // Get absolute addresses
 *   #include "och_sep_common.h"   // Get register access macros
 *
 *   WRITE_REG(OCH_SEP_TOP_OTBN_CMD_BASE_ADDR, OTBN_CMD_EXECUTE);
 *   uint32_t status = READ_REG(OCH_SEP_TOP_OTBN_STATUS_BASE_ADDR);
 */

//==============================================================================
// Generated-name compatibility aliases
//==============================================================================

/*
 * The spi_controller ERROR_STATUS register carries dynamic ->hwenable
 * assignments in the RDL, so PeakRDL-cheader (--type-style lexical) emits a
 * hash-suffixed type/macro prefix for it. Alias the stable names firmware
 * uses. Only available when the generated spi_controller.h has been included
 * (via sep.h).
 */
#ifdef SPI_CONTROLLER_H
typedef spi_controller__ERROR_STATUS_CMDBUSY_610d1fb8_CMDINVAL_5f890e60_CSIDINVAL_52ab238c_OVERFLOW_b3d067e6_UNDERFLOW_cfe1cef2_t
    spi_controller__ERROR_STATUS_t;
#define SPI_CONTROLLER__ERROR_STATUS__CMDBUSY_bm \
    SPI_CONTROLLER__ERROR_STATUS_CMDBUSY_610D1FB8_CMDINVAL_5F890E60_CSIDINVAL_52AB238C_OVERFLOW_B3D067E6_UNDERFLOW_CFE1CEF2__CMDBUSY_bm
#define SPI_CONTROLLER__ERROR_STATUS__OVERFLOW_bm \
    SPI_CONTROLLER__ERROR_STATUS_CMDBUSY_610D1FB8_CMDINVAL_5F890E60_CSIDINVAL_52AB238C_OVERFLOW_B3D067E6_UNDERFLOW_CFE1CEF2__OVERFLOW_bm
#define SPI_CONTROLLER__ERROR_STATUS__UNDERFLOW_bm \
    SPI_CONTROLLER__ERROR_STATUS_CMDBUSY_610D1FB8_CMDINVAL_5F890E60_CSIDINVAL_52AB238C_OVERFLOW_B3D067E6_UNDERFLOW_CFE1CEF2__UNDERFLOW_bm
#define SPI_CONTROLLER__ERROR_STATUS__CMDINVAL_bm \
    SPI_CONTROLLER__ERROR_STATUS_CMDBUSY_610D1FB8_CMDINVAL_5F890E60_CSIDINVAL_52AB238C_OVERFLOW_B3D067E6_UNDERFLOW_CFE1CEF2__CMDINVAL_bm
#define SPI_CONTROLLER__ERROR_STATUS__CSIDINVAL_bm \
    SPI_CONTROLLER__ERROR_STATUS_CMDBUSY_610D1FB8_CMDINVAL_5F890E60_CSIDINVAL_52AB238C_OVERFLOW_B3D067E6_UNDERFLOW_CFE1CEF2__CSIDINVAL_bm
#define SPI_CONTROLLER__ERROR_STATUS__ACCESSINVAL_bm \
    SPI_CONTROLLER__ERROR_STATUS_CMDBUSY_610D1FB8_CMDINVAL_5F890E60_CSIDINVAL_52AB238C_OVERFLOW_B3D067E6_UNDERFLOW_CFE1CEF2__ACCESSINVAL_bm
#define SPI_CONTROLLER__ERROR_STATUS__ACCESSINVAL_bp \
    SPI_CONTROLLER__ERROR_STATUS_CMDBUSY_610D1FB8_CMDINVAL_5F890E60_CSIDINVAL_52AB238C_OVERFLOW_B3D067E6_UNDERFLOW_CFE1CEF2__ACCESSINVAL_bp
#endif // SPI_CONTROLLER_H

#endif // OCH_SEP_COMMON_H
