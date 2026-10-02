/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @brief UART Log Engine Boundary and Backpressure Test
 *
 * Verifies that the log engine of UART wrapper 0 transmits exactly the
 * effective log length: the requested length when it fits in the slot, the
 * slot capacity when the request is larger, and whole 8-byte words when the
 * slot is not word aligned. It also checks that a log longer than the UART
 * transmit FIFO arrives complete and in order under transmit backpressure.
 * Each log entry must complete without a fetch or write error. The log region
 * is split into 16 equal slots, so the region size sets the slot capacity.
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

#define LOG_BUFFER_BASE (SMC_TOP_SPM_MEMORY_BASE_ADDR + 0x40000u)

// Enable the UART pads and set the fastest baud rate, 8N1 framing, internal loopback and FIFOs.
static void setup_uart_8n1_fifo(void) {
    write_reg(WRAP0_CTRL_REG, 1u);
    write_reg(WRAP0_UART_BASE + UART_LCR_OFF, 0x80u);
    write_reg(WRAP0_UART_BASE + UART_RBR_OFF, 0x01u);
    write_reg(WRAP0_UART_BASE + UART_IER_OFF, 0x00u);
    write_reg(WRAP0_UART_BASE + UART_LCR_OFF, 0x03u);
    write_reg(WRAP0_UART_BASE + UART_MCR_OFF, 0x10u);
    write_reg(WRAP0_UART_BASE + UART_IIR_OFF, 0x01u);
}

// Wait for the engine to clear the entry's length, which marks the log as written.
static int wait_log_done(uint32_t ctrl_off, uint32_t timeout) {
    while (timeout > 0u) {
        if ((read_reg(WRAP0_LE_BASE + ctrl_off) & 0xFFFFu) == 0u) return 0;
        timeout--;
    }
    return -1;
}

static int wait_uart_tx_empty(uint32_t timeout) {
    while (timeout > 0u) {
        if ((read_reg(WRAP0_UART_BASE + UART_LSR_OFF) & 0x40u) != 0u) return 0;
        timeout--;
    }
    return -1;
}

static int read_uart_byte(uint8_t *value, uint32_t timeout) {
    while (timeout > 0u) {
        if ((read_reg(WRAP0_UART_BASE + UART_LSR_OFF) & 0x1u) != 0u) {
            *value = (uint8_t)(read_reg(WRAP0_UART_BASE + UART_RBR_OFF) & 0xFFu);
            return 0;
        }
        timeout--;
    }
    return -1;
}

static int reset_uart_fifos(void) {
    if (wait_uart_tx_empty(2000000u) != 0) return -1;

    // Reset both FIFOs, then drain any received byte still visible and fail if data remains.
    write_reg(WRAP0_UART_BASE + UART_IIR_OFF, 0x07u);
    for (uint32_t count = 0; count < 32u; count++) {
        if ((read_reg(WRAP0_UART_BASE + UART_LSR_OFF) & 0x1u) == 0u) return 0;
        (void)read_reg(WRAP0_UART_BASE + UART_RBR_OFF);
    }
    return (read_reg(WRAP0_UART_BASE + UART_LSR_OFF) & 0x1u) == 0u ? 0 : -1;
}

static int verify_uart_transfer(uint8_t first_value, uint32_t byte_count) {
    for (uint32_t index = 0; index < byte_count; index++) {
        uint8_t actual = 0u;
        if (read_uart_byte(&actual, 2000000u) != 0) return -1;
        if (actual != (uint8_t)(first_value + index)) return -2;
    }

    // The log entry completes when its last byte enters the UART, not when it leaves the
    // transmitter. Once the transmitter is idle every byte has looped back, so no further received
    // data may remain.
    if (wait_uart_tx_empty(2000000u) != 0) return -3;
    if ((read_reg(WRAP0_UART_BASE + UART_LSR_OFF) & 0x1u) != 0u) {
        (void)read_reg(WRAP0_UART_BASE + UART_RBR_OFF);
        return -4;
    }
    return 0;
}

int main(void) {
    info_msg_s(0, "smc_uart_log_engine_boundary_backpressure_test start");

    setup_uart_8n1_fifo();

    //--------------------------------------------------------------------------
    // SCENARIO A — the requested length ends the transfer before the slot
    // capacity. An 8-byte request comes from a 16-byte slot. The whole slot
    // carries a pattern, so a transfer that ignored the requested length shows
    // up as a ninth byte.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario A: requested length terminates before slot capacity");
    {
        volatile uint8_t *buf = (volatile uint8_t *)(uintptr_t)LOG_BUFFER_BASE;
        for (int i = 0; i < 16; i++) buf[i] = (uint8_t)(0xA0u + i);

        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
        write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, 0x11u);
        write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, 0x100u);
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF, LOG_BUFFER_BASE);
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
        write_reg(WRAP0_LE_BASE + LE_WRITE_ADDR_OFF, WRAP0_UART_BASE + UART_RBR_OFF);
        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
        write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, 8u);

        if (wait_log_done(LE_LOG_CTRL0_OFF, 200000u) != 0) {
            info_msg_s(0, "FAIL: scenario A: log not done (LOG_CTRL hwclr timeout)");
            test_fail(0);
        }
        if (verify_uart_transfer(0xA0u, 8u) != 0) {
            info_msg_s(0, "FAIL: scenario A: expected exactly bytes 0xA0 through 0xA7");
            test_fail(0);
        }
        if ((read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & 0x11u) != 0u) {
            info_msg_s(0, "FAIL: scenario A: unexpected INTR_STATUS");
            test_fail(0);
        }
        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    }

    //--------------------------------------------------------------------------
    // SCENARIO B — log write under UART transmit backpressure. A 64-byte log
    // from a 64-byte slot is twice the transmit FIFO depth. The engine writes
    // bytes faster than the UART sends them, so the transmit FIFO fills and the
    // engine has to wait while it still holds fetched data.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario B: log-write under TX backpressure");
    {
        volatile uint8_t *buf = (volatile uint8_t *)(uintptr_t)LOG_BUFFER_BASE;
        for (int i = 0; i < 64; i++) buf[i] = (uint8_t)(0x40u + i);

        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
        write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, 0x11u);
        write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, 0x400u);
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF, LOG_BUFFER_BASE);
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
        write_reg(WRAP0_LE_BASE + LE_WRITE_ADDR_OFF, WRAP0_UART_BASE + UART_RBR_OFF);
        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
        write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, 64u);

        // Read the 64 bytes back as they arrive. The receive FIFO is 32 deep,
        // so draining has to overlap the transfer; the transmit FIFO still
        // fills, because the engine refills it faster than the UART sends.
        // Every byte is compared, so a byte dropped under backpressure fails
        // here. Each per-byte wait is bounded; expiry is a failure, never a pass.
        for (uint32_t index = 0; index < 64u; index++) {
            uint8_t actual = 0u;
            if (read_uart_byte(&actual, 2000000u) != 0) {
                info_msg_s(0, "FAIL: scenario B: a looped-back byte never arrived");
                test_fail(0);
            }
            if (actual != (uint8_t)(0x40u + index)) {
                info_msg_s(0, "FAIL: scenario B: looped-back byte out of sequence");
                test_fail(0);
            }
        }
        if (wait_log_done(LE_LOG_CTRL0_OFF, 2000000u) != 0) {
            info_msg_s(0, "FAIL: scenario B: log not done under backpressure");
            test_fail(0);
        }
        // Nothing beyond the 64 requested bytes may arrive.
        if (wait_uart_tx_empty(2000000u) != 0) {
            info_msg_s(0, "FAIL: scenario B: transmitter never drained");
            test_fail(0);
        }
        if ((read_reg(WRAP0_UART_BASE + UART_LSR_OFF) & 0x1u) != 0u) {
            info_msg_s(0, "FAIL: scenario B: a 65th byte reached the receiver");
            test_fail(0);
        }
        if ((read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & 0x11u) != 0u) {
            info_msg_s(0, "FAIL: scenario B: unexpected INTR_STATUS");
            test_fail(0);
        }
        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    }

    //--------------------------------------------------------------------------
    // SCENARIO D — a requested length above the slot capacity is clamped. A
    // 24-byte request from a 16-byte slot must transmit exactly 16 bytes and
    // complete the log entry.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario D: log length clamps to slot capacity");
    {
        volatile uint8_t *buf = (volatile uint8_t *)(uintptr_t)LOG_BUFFER_BASE;
        for (int i = 0; i < 16; i++) buf[i] = (uint8_t)(0x80u + i);

        if (reset_uart_fifos() != 0) {
            info_msg_s(0, "FAIL: scenario D: UART FIFOs did not reset and drain");
            test_fail(0);
        }
        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
        write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, 0x11u);
        write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, 0x100u);
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF, LOG_BUFFER_BASE);
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
        write_reg(WRAP0_LE_BASE + LE_WRITE_ADDR_OFF, WRAP0_UART_BASE + UART_RBR_OFF);
        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
        write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, 24u);

        if (wait_log_done(LE_LOG_CTRL0_OFF, 200000u) != 0) {
            info_msg_s(0, "FAIL: scenario D: clamped log did not complete");
            test_fail(0);
        }
        if (verify_uart_transfer(0x80u, 16u) != 0) {
            info_msg_s(0, "FAIL: scenario D: expected exactly bytes 0x80 through 0x8F");
            test_fail(0);
        }
        if ((read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & 0x11u) != 0u) {
            info_msg_s(0, "FAIL: scenario D: unexpected INTR_STATUS");
            test_fail(0);
        }
        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    }

    //--------------------------------------------------------------------------
    // SCENARIO E — a slot that is not word aligned rounds down to whole 8-byte
    // words. A 15-byte request from a 15-byte slot must transmit exactly
    // 8 bytes, so no fetch crosses the slot boundary and the writer does not
    // wait for bytes that are never fetched.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario E: non-word-aligned slot rounds down to one beat");
    {
        volatile uint8_t *buf = (volatile uint8_t *)(uintptr_t)LOG_BUFFER_BASE;
        for (int i = 0; i < 16; i++) buf[i] = (uint8_t)(0xE0u + i);

        if (reset_uart_fifos() != 0) {
            info_msg_s(0, "FAIL: scenario E: UART FIFOs did not reset and drain");
            test_fail(0);
        }
        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
        write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, 0x11u);
        write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, 0xF0u);
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF, LOG_BUFFER_BASE);
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
        write_reg(WRAP0_LE_BASE + LE_WRITE_ADDR_OFF, WRAP0_UART_BASE + UART_RBR_OFF);
        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
        write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, 15u);

        if (wait_log_done(LE_LOG_CTRL0_OFF, 200000u) != 0) {
            info_msg_s(0, "FAIL: scenario E: rounded log did not complete");
            test_fail(0);
        }
        if (verify_uart_transfer(0xE0u, 8u) != 0) {
            info_msg_s(0, "FAIL: scenario E: expected exactly bytes 0xE0 through 0xE7");
            test_fail(0);
        }
        if ((read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & 0x11u) != 0u) {
            info_msg_s(0, "FAIL: scenario E: unexpected INTR_STATUS");
            test_fail(0);
        }
        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    }

    // Leave the UART out of loopback and disabled.
    write_reg(WRAP0_UART_BASE + UART_MCR_OFF, 0u);
    write_reg(WRAP0_CTRL_REG, 0u);

    info_msg_s(0, "smc_uart_log_engine_boundary_backpressure_test done");
    test_pass(0);
}
