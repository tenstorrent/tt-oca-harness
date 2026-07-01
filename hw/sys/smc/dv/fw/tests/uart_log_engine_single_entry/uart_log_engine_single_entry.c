/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// smc_uart_log_engine_single_entry_test
//
// Engine golden path: pre-load SRAM, configure engine to feed the UART via
// system loopback (MCR.LOOP=1 internally connects TX → RX), trigger
// LOG_CTRL[0], read every transmitted byte from RBR, and verify byte order
// matches the SRAM pattern.  Also asserts:
//   * LOG_CTRL[0] hwclr to 0 after transfer completes
//   * INTR_STATUS = 0 throughout (no error injected)

#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"

#define WRAP0_CTRL_REG      SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(0)
#define WRAP0_UART_BASE     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)
#define WRAP0_LE_BASE       SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_CTRL_BASE_ADDR(0)

#define UART_RBR_OFF        (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_IER_OFF        (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_IIR_OFF        (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_LCR_OFF        (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_MCR_OFF        (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_LSR_OFF        (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))

#define LE_CTRL_OFF         (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_CTRL_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_REGION_SIZE_OFF  (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_REGION_SIZE_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_REGION_ADDR_OFF  (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_REGION_ADDR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_WRITE_ADDR_OFF   (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_WRITE_ADDR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_INTR_STATUS_OFF  (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_STATUS_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_LOG_CTRL0_OFF    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_CTRL_BASE_ADDR(0, 0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))

#define LOG_BUFFER_BASE     (SMC_TOP_SPM_MEMORY_BASE_ADDR + 0x40000u)
#define LOG_REGION_SIZE     0x100u   // 256 B → slot 0 spans 16 B
#define XFER_LEN            16u

static void setup_uart_loopback(void) {
    // Pad-mux enable so UART CSR access is granted by the wrapper
    write_reg(WRAP0_CTRL_REG, 1u);

    // LCR: set DLAB=1, program divisor=1 (fastest), DLAB=0 with WLS=3 (8 bits)
    write_reg(WRAP0_UART_BASE + UART_LCR_OFF, 0x80u);
    write_reg(WRAP0_UART_BASE + UART_RBR_OFF, 0x01u);   // DLL
    write_reg(WRAP0_UART_BASE + UART_IER_OFF, 0x00u);   // DLM
    write_reg(WRAP0_UART_BASE + UART_LCR_OFF, 0x03u);   // DLAB=0, WLS=8 bits

    // MCR.LOOP = 1 (system loopback: TX → RX inside the core, tx_o = 1)
    write_reg(WRAP0_UART_BASE + UART_MCR_OFF, 0x10u);

    // FCR: enable FIFOs (write to IIR offset; bit 0 = FIFO enable)
    write_reg(WRAP0_UART_BASE + UART_IIR_OFF, 0x01u);

    // IER: enable Received Data Ready interrupt so IIR reports it
    write_reg(WRAP0_UART_BASE + UART_IER_OFF, 0x01u);
}

static int read_byte_with_timeout(uint8_t *out) {
    // Poll IIR for Received Data Ready (ID = 0x2 → IIR[3:0] = 0x4)
    for (uint32_t t = 0; t < 1000000u; t++) {
        uint32_t iir = read_reg(WRAP0_UART_BASE + UART_IIR_OFF) & 0xFu;
        if (iir == 0x4u) {
            *out = (uint8_t)(read_reg(WRAP0_UART_BASE + UART_RBR_OFF) & 0xFFu);
            return 0;
        }
        // Or check LSR.DR directly
        if (read_reg(WRAP0_UART_BASE + UART_LSR_OFF) & 0x1u) {
            *out = (uint8_t)(read_reg(WRAP0_UART_BASE + UART_RBR_OFF) & 0xFFu);
            return 0;
        }
    }
    return -1;
}

int main(void) {
    info_msg_s(0, "smc_uart_log_engine_single_entry_test start");

    //--------------------------------------------------------------------------
    // Pre-load SRAM at slot 0 (LOG_BUFFER_BASE + 0..15)
    //--------------------------------------------------------------------------
    volatile uint8_t *buf = (volatile uint8_t *)(uintptr_t)LOG_BUFFER_BASE;
    const uint8_t expected[XFER_LEN] = {
        0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0xA6, 0xA7,
        0xA8, 0xA9, 0xAA, 0xAB, 0xAC, 0xAD, 0xAE, 0xAF
    };
    for (uint32_t i = 0; i < XFER_LEN; i++) buf[i] = expected[i];

    //--------------------------------------------------------------------------
    // UART loopback + engine setup
    //--------------------------------------------------------------------------
    setup_uart_loopback();

    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, LOG_REGION_SIZE);
    write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF, LOG_BUFFER_BASE);
    write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
    write_reg(WRAP0_LE_BASE + LE_WRITE_ADDR_OFF,
              WRAP0_UART_BASE + UART_RBR_OFF);
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, 0x11u);  // W1C any stale
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);

    //--------------------------------------------------------------------------
    // Trigger 16-byte transfer on entry 0
    //--------------------------------------------------------------------------
    write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, XFER_LEN);

    //--------------------------------------------------------------------------
    // Read XFER_LEN bytes via loopback and verify against expected pattern
    //--------------------------------------------------------------------------
    for (uint32_t i = 0; i < XFER_LEN; i++) {
        uint8_t b;
        if (read_byte_with_timeout(&b) != 0) {
            info_msg_s(0, "FAIL: timed out waiting for RX byte");
            info_msg_hex32_s(0, "  byte_idx=", i);
            test_fail(0);
        }
        if (b != expected[i]) {
            info_msg_s(0, "FAIL: RX byte mismatch");
            info_msg_hex32_s(0, "  idx     =", i);
            info_msg_hex32_s(0, "  expected=", (uint32_t)expected[i]);
            info_msg_hex32_s(0, "  got     =", (uint32_t)b);
            test_fail(0);
        }
    }

    //--------------------------------------------------------------------------
    // Verify LOG_CTRL[0] hwclr to 0
    //--------------------------------------------------------------------------
    {
        uint32_t t = 200000u;
        while (t > 0u && (read_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF) & 0xFFFFu) != 0u) {
            t--;
        }
        if (t == 0u) {
            info_msg_s(0, "FAIL: LOG_CTRL[0] did not hwclr after transfer");
            test_fail(0);
        }
    }

    //--------------------------------------------------------------------------
    // INTR_STATUS = 0 (no error injected)
    //--------------------------------------------------------------------------
    {
        uint32_t s = read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & 0x11u;
        if (s != 0u) {
            info_msg_hex32_s(0, "FAIL: INTR_STATUS unexpectedly set=", s);
            test_fail(0);
        }
    }

    // Cleanup
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    write_reg(WRAP0_UART_BASE + UART_MCR_OFF, 0u);
    write_reg(WRAP0_CTRL_REG, 0u);

    info_msg_s(0, "smc_uart_log_engine_single_entry_test done");
    test_pass(0);

    while (1) __asm__("wfi");
    return 0;
}
