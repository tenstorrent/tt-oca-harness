/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// smc_uart_log_engine_multi_entry_rr_test
//
// Round-robin arbitration test. Pre-loads every slot listed in ACTIVE with
// tagged byte patterns, triggers all of them back-to-back and reads the
// resulting UART byte stream via system loopback. Verifies:
//   * Each byte tags back to a known slot (set membership)
//   * Total byte count matches sum of triggered lengths
//   * Every active LOG_CTRL[i] eventually hwclrs to 0
//   * INTR_STATUS = 0
//
// The byte interleaving granularity across concurrently triggered entries is
// not specified, so this test does not pin an interleave pattern: it asserts
// set membership, total count and completion.

#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"

#define WRAP0_CTRL_REG \
    SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(0)
#define WRAP0_UART_BASE SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)
#define WRAP0_LE_BASE SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_CTRL_BASE_ADDR(0)

#define UART_RBR_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_IER_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_IIR_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_LCR_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_MCR_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_LSR_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))

#define LE_CTRL_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_CTRL_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_REGION_SIZE_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_REGION_SIZE_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_REGION_ADDR_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_REGION_ADDR_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_WRITE_ADDR_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_WRITE_ADDR_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_INTR_STATUS_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_STATUS_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_LOG_CTRL0_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_CTRL_BASE_ADDR(0, 0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))

#define LOG_BUFFER_BASE (SMC_TOP_SPM_MEMORY_BASE_ADDR + 0x48000u)
#define LOG_REGION_SIZE 0x100u
#define NUM_ENTRIES 16u
#define SLOT_SIZE (LOG_REGION_SIZE / NUM_ENTRIES)

// All 16 slots are active so every LOG_CTRL[i] hwclr/hwif path and every
// arbiter_tree req_i bit toggles. The per-slot byte pattern (i<<4)|j spans
// 0x00..0xFF, so every AXI-Lite r.data bit toggles through the fetch path.
#define NUM_ACTIVE 16u
static const uint32_t ACTIVE[NUM_ACTIVE] = {0u, 1u, 2u,  3u,  4u,  5u,  6u,  7u,
                                            8u, 9u, 10u, 11u, 12u, 13u, 14u, 15u};

static int read_byte_with_timeout(uint8_t *out) {
    for (uint32_t t = 0; t < 1000000u; t++) {
        if (read_reg(WRAP0_UART_BASE + UART_LSR_OFF) & 0x1u) {
            *out = (uint8_t)(read_reg(WRAP0_UART_BASE + UART_RBR_OFF) & 0xFFu);
            return 0;
        }
    }
    return -1;
}

// For each active slot, tag bytes so we can identify which slot they came
// from regardless of interleave: slot i, byte j = (i << 4) | j
// Decode by extracting (b >> 4) to get slot index.

int main(void) {
    info_msg_s(0, "smc_uart_log_engine_multi_entry_rr_test start");

    //--------------------------------------------------------------------------
    // Pre-load the active slots
    //--------------------------------------------------------------------------
    volatile uint8_t *buf = (volatile uint8_t *)(uintptr_t)LOG_BUFFER_BASE;
    for (uint32_t k = 0; k < NUM_ACTIVE; k++) {
        uint32_t i = ACTIVE[k];
        for (uint32_t j = 0; j < SLOT_SIZE; j++) {
            buf[i * SLOT_SIZE + j] = (uint8_t)((i << 4) | j);
        }
    }

    //--------------------------------------------------------------------------
    // UART loopback + engine setup
    //--------------------------------------------------------------------------
    write_reg(WRAP0_CTRL_REG, 1u);
    write_reg(WRAP0_UART_BASE + UART_LCR_OFF, 0x80u);
    write_reg(WRAP0_UART_BASE + UART_RBR_OFF, 0x01u);
    write_reg(WRAP0_UART_BASE + UART_IER_OFF, 0x00u);
    write_reg(WRAP0_UART_BASE + UART_LCR_OFF, 0x03u);
    write_reg(WRAP0_UART_BASE + UART_MCR_OFF, 0x10u);
    write_reg(WRAP0_UART_BASE + UART_IIR_OFF, 0x01u);
    write_reg(WRAP0_UART_BASE + UART_IER_OFF, 0x01u);

    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, LOG_REGION_SIZE);
    write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF, LOG_BUFFER_BASE);
    write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
    write_reg(WRAP0_LE_BASE + LE_WRITE_ADDR_OFF, WRAP0_UART_BASE + UART_RBR_OFF);
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, 0x11u);
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);

    //--------------------------------------------------------------------------
    // Trigger all active entries back-to-back
    //--------------------------------------------------------------------------
    for (uint32_t k = 0; k < NUM_ACTIVE; k++) {
        uint32_t i = ACTIVE[k];
        write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF + (i * 4u), SLOT_SIZE);
    }

    //--------------------------------------------------------------------------
    // Read all SLOT_SIZE * NUM_ACTIVE bytes; for each byte, decode slot tag
    // and check that (a) it is one of ACTIVE, (b) within-slot byte index j is
    // unique per slot (we only ever expect to see each (i,j) exactly once).
    //--------------------------------------------------------------------------
    uint32_t total = SLOT_SIZE * NUM_ACTIVE;
    uint8_t seen_count[NUM_ENTRIES][SLOT_SIZE];
    for (uint32_t i = 0; i < NUM_ENTRIES; i++)
        for (uint32_t j = 0; j < SLOT_SIZE; j++) seen_count[i][j] = 0;

    for (uint32_t n = 0; n < total; n++) {
        uint8_t b;
        if (read_byte_with_timeout(&b) != 0) {
            info_msg_s(0, "FAIL: multi_entry_rr RX timeout");
            info_msg_hex32_s(0, "  byte_n =", n);
            test_fail(0);
        }
        uint32_t slot = (uint32_t)(b >> 4) & 0xFu;
        uint32_t j = (uint32_t)(b & 0xFu);

        // Set membership: slot must be in ACTIVE
        int active = 0;
        for (uint32_t k = 0; k < NUM_ACTIVE; k++) {
            if (ACTIVE[k] == slot) {
                active = 1;
                break;
            }
        }
        if (!active) {
            info_msg_s(0, "FAIL: byte from unexpected slot");
            info_msg_hex32_s(0, "  byte =", (uint32_t)b);
            info_msg_hex32_s(0, "  slot =", slot);
            test_fail(0);
        }

        if (seen_count[slot][j] != 0u) {
            info_msg_s(0, "FAIL: duplicate byte received");
            info_msg_hex32_s(0, "  byte =", (uint32_t)b);
            test_fail(0);
        }
        seen_count[slot][j] = 1u;
    }

    // Confirm we saw every (slot, j) in ACTIVE
    for (uint32_t k = 0; k < NUM_ACTIVE; k++) {
        uint32_t i = ACTIVE[k];
        for (uint32_t j = 0; j < SLOT_SIZE; j++) {
            if (seen_count[i][j] == 0u) {
                info_msg_s(0, "FAIL: missing byte from active slot");
                info_msg_hex32_s(0, "  slot=", i);
                info_msg_hex32_s(0, "  j   =", j);
                test_fail(0);
            }
        }
    }

    //--------------------------------------------------------------------------
    // Every active LOG_CTRL[i] must hwclr to 0
    //--------------------------------------------------------------------------
    for (uint32_t k = 0; k < NUM_ACTIVE; k++) {
        uint32_t i = ACTIVE[k];
        uint32_t t = 200000u;
        while (t > 0u && (read_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF + (i * 4u)) & 0xFFFFu) != 0u) {
            t--;
        }
        if (t == 0u) {
            info_msg_s(0, "FAIL: LOG_CTRL did not hwclr");
            info_msg_hex32_s(0, "  slot=", i);
            test_fail(0);
        }
    }

    {
        uint32_t s = read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & 0x11u;
        if (s != 0u) {
            info_msg_hex32_s(0, "FAIL: INTR_STATUS set at end=", s);
            test_fail(0);
        }
    }

    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    write_reg(WRAP0_UART_BASE + UART_MCR_OFF, 0u);
    write_reg(WRAP0_CTRL_REG, 0u);

    info_msg_s(0, "smc_uart_log_engine_multi_entry_rr_test done");
    test_pass(0);

    while (1) __asm__("wfi");
    return 0;
}
