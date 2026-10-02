/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @brief UART Log Engine Multi-Entry - Concurrent Entries Complete
 *
 * Verifies that when all 16 log entries are triggered back to back, the
 * expected number of bytes looped back from UART 0 are exactly the bytes of
 * every entry, each received once, and every entry completes without an error.
 * The interleave of bytes across entries is not specified, so the test does not
 * check the order or the fairness of arbitration.
 */

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

// Every entry is active, and the slot tags make the payload cover every byte
// value.
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

int main(void) {
    info_msg_s(0, "smc_uart_log_engine_multi_entry_rr_test start");

    //--------------------------------------------------------------------------
    // Each byte encodes its slot and offset, so the receiver can attribute it
    // to an entry whatever the interleave
    //--------------------------------------------------------------------------
    volatile uint8_t *buf = (volatile uint8_t *)(uintptr_t)LOG_BUFFER_BASE;
    for (uint32_t k = 0; k < NUM_ACTIVE; k++) {
        uint32_t i = ACTIVE[k];
        for (uint32_t j = 0; j < SLOT_SIZE; j++) {
            buf[i * SLOT_SIZE + j] = (uint8_t)((i << 4) | j);
        }
    }

    //--------------------------------------------------------------------------
    // UART at the fastest rate with 8-bit words, FIFOs and internal loopback,
    // so every byte the engine writes comes back on the receive side
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
    // Every received byte must belong to an active slot and arrive only once
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

    // No byte of an active slot may be missing
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
    // Hardware clears each entry's length when its transfer completes
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
}
