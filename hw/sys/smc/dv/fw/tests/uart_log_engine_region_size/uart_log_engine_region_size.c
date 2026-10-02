/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @brief UART Log Engine Region Size - Per-Entry Slot Addressing
 *
 * Verifies that the log engine divides its log region evenly among its 16
 * entries: with a 256-byte region, each entry triggered alone sends exactly its
 * own 16-byte slot in order, and no error is raised.
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

#define LE_INTR_ENABLE_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_ENABLE_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))

#define LE_INTR_TEST_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_TEST_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_LOG_CTRL0_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_CTRL_BASE_ADDR(0, 0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))

#define LOG_BUFFER_BASE (SMC_TOP_SPM_MEMORY_BASE_ADDR + 0x44000u)
#define LOG_REGION_SIZE 0x100u // 256 bytes
#define NUM_ENTRIES 16u
#define SLOT_SIZE (LOG_REGION_SIZE / NUM_ENTRIES) // 16 bytes

static int read_byte_with_timeout(uint8_t *out) {
    /* Poll bound: 200 register reads dwarf a single byte's latency and expire
     * before the harness timeout. */
    for (uint32_t t = 0; t < 200u; t++) {
        if (read_reg(WRAP0_UART_BASE + UART_LSR_OFF) & 0x1u) {
            *out = (uint8_t)(read_reg(WRAP0_UART_BASE + UART_RBR_OFF) & 0xFFu);
            return 0;
        }
    }
    return -1;
}

int main(void) {
    info_msg_s(0, "smc_uart_log_engine_region_size_test start");

    //--------------------------------------------------------------------------
    // Each byte encodes its slot and its offset within the slot
    //--------------------------------------------------------------------------
    volatile uint8_t *buf = (volatile uint8_t *)(uintptr_t)LOG_BUFFER_BASE;
    for (uint32_t i = 0; i < NUM_ENTRIES; i++) {
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
    // Show both error status bits can be set and cleared, so the zero status
    // checked at the end of the test is meaningful.
    {
        const uint32_t both =
            LOG_ENGINE__INTR_TEST__LOG_FETCH_ERR_bm | LOG_ENGINE__INTR_TEST__LOG_WRITE_ERR_bm;
        uint32_t s;
        write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, both);
        write_reg(WRAP0_LE_BASE + LE_INTR_TEST_OFF, both);
        s = read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & both;
        if (s != both) {
            info_msg_hex32_s(0, "FAIL: INTR_TEST did not set both status bits, got=", s);
            test_fail(0);
        }
        info_msg_hex32_s(0, "  positive control: INTR_TEST set status=", s);
        write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, 0u);
        write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, both);
        s = read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & both;
        if (s != 0u) {
            info_msg_hex32_s(0, "FAIL: could not clear the positive control, left=", s);
            test_fail(0);
        }
        write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, both);
    }

    //--------------------------------------------------------------------------
    // Each entry must send exactly its own slot's bytes, in order
    //--------------------------------------------------------------------------
    for (uint32_t i = 0; i < NUM_ENTRIES; i++) {
        info_msg_hex32_s(0, "region_size: entry=", i);

        write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF + (i * 4u), SLOT_SIZE);

        for (uint32_t j = 0; j < SLOT_SIZE; j++) {
            uint8_t b;
            if (read_byte_with_timeout(&b) != 0) {
                info_msg_s(0, "FAIL: region_size RX timeout");
                info_msg_hex32_s(0, "  entry =", i);
                info_msg_hex32_s(0, "  byte  =", j);
                test_fail(0);
            }
            uint8_t want = (uint8_t)((i << 4) | j);
            if (b != want) {
                info_msg_s(0, "FAIL: region_size byte mismatch");
                info_msg_hex32_s(0, "  entry   =", i);
                info_msg_hex32_s(0, "  byte    =", j);
                info_msg_hex32_s(0, "  expected=", (uint32_t)want);
                info_msg_hex32_s(0, "  got     =", (uint32_t)b);
                test_fail(0);
            }
        }

        // Hardware clears the entry length when the transfer completes
        {
            uint32_t t = 200u; /* bound expires before the harness timeout */
            while (t > 0u &&
                   (read_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF + (i * 4u)) & 0xFFFFu) != 0u) {
                t--;
            }
            if (t == 0u) {
                info_msg_s(0, "FAIL: region_size LOG_CTRL[i] did not hwclr");
                info_msg_hex32_s(0, "  entry =", i);
                test_fail(0);
            }
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

    info_msg_s(0, "smc_uart_log_engine_region_size_test done");
    test_pass(0);
}
