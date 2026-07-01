/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

/*******************************************************************************
 * SEP Outbound Filter Initialization
 *
 * This header provides initialization for the SEP outbound filter to allow
 * firmware access to the testbench mailbox at 0x8000_0000 (STDOUT).
 *
 * By default, the outbound filter blocks all transactions. This function
 * configures filter 0 to allow read/write access to the testpass mailbox
 * address range.
 *
 * Usage:
 *   #include "sep_outbound_filter.h"
 *
 *   int main(void) {
 *       sep_outbound_filter_init();  // Call FIRST before any mailbox access
 *       // ... rest of test code
 *   }
 *
 ******************************************************************************/

#ifndef SEP_OUTBOUND_FILTER_H
#define SEP_OUTBOUND_FILTER_H

#include <stdint.h>
#include "och_sep_common.h"
#include "sep.h"

//==============================================================================
// Outbound Filter Register Definitions
//==============================================================================

// Outbound filter 0 base address from the normalized SEP register header
#define OUTBOUND_FILTER_BASE OCH_SEP_TOP_OUTBOUND_FILTER_CTRL_BASE_ADDR(0)

// Register offsets (each filter occupies 0x100 bytes)
#define FILTER_CONFIG_OFFSET 0x0   // 64-bit: Configuration and control
#define START_ADDR_OFFSET    0x8   // 64-bit: Start of address range
#define END_ADDR_OFFSET      0x10  // 64-bit: End of address range

//==============================================================================
// Filter Configuration Values
//==============================================================================

// FILTER_CONFIG bitfield values:
// [0]      read_en = 1         (Allow read transactions)
// [1]      write_en = 1        (Allow write transactions)
// [4]      addr_mode = 1       (Enable filter)
// [8]      allow_ns = 1        (Allow non-secure transactions)
// [24]     allow_burst = 1     (Allow burst transactions)
// [63]     locked = 0          (Allow reconfiguration)
// All other fields = 0 (no source/group filtering)
#define FILTER_CONFIG_VALUE 0x0000000101000013ULL

// Address range for testpass mailbox at 0x8000_0000
#define FILTER_START_ADDR 0x0000000080000000ULL
#define FILTER_END_ADDR   0x00000000800000FFULL  // Extended range for multiple writes

//==============================================================================
// Initialization Function
//==============================================================================

/**
 * Initialize SEP outbound filter 0 for testpass mailbox access
 *
 * Configures filter 0 to allow read/write access to 0x8000_0000, which is
 * used by the testbench to detect test completion (PASS/FAIL signaling).
 *
 * This function should be called at the start of main() before any writes
 * to the testpass mailbox address.
 *
 * Filter configuration:
 *   - Address range: 0x8000_0000 to 0x8000_0003 (single 32-bit word)
 *   - Read enabled: YES
 *   - Write enabled: YES
 *   - Non-secure access: Allowed
 *   - Burst transfers: Allowed
 *   - Locked: NO (can be reconfigured)
 */
static inline void sep_outbound_filter_init(void) {
    // Write START_ADDR register (must be configured before enabling filter)
    WRITE_REG64(OUTBOUND_FILTER_BASE + START_ADDR_OFFSET, FILTER_START_ADDR);

    // Write END_ADDR register (must be configured before enabling filter)
    WRITE_REG64(OUTBOUND_FILTER_BASE + END_ADDR_OFFSET, FILTER_END_ADDR);

    // Write FILTER_CONFIG register (enables filter atomically)
    // This must be written LAST to ensure address range is configured first
    WRITE_REG64(OUTBOUND_FILTER_BASE + FILTER_CONFIG_OFFSET, FILTER_CONFIG_VALUE);
}

#endif // SEP_OUTBOUND_FILTER_H
