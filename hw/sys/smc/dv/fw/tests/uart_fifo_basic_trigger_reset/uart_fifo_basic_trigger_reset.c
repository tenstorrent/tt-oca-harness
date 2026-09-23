/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "metal/uart.h"
#include "smc_io.h"
#include "smc_test.h"
#include "virt_console.h"

// Test focus: UART FIFO enable / trigger level / reset behavior.
// To control simulation time, this test only targets a single UART (index 0, loopback mode)
// and validates two representative trigger levels (for example, 1 byte and 4 bytes).

// FCR bit definitions (write-only, sharing the address with IIR)
#define UART_FCR_FIFO_ENABLE (1u << 0)
#define UART_FCR_RCVR_FIFO_RESET (1u << 1)
#define UART_FCR_XMIT_FIFO_RESET (1u << 2)
#define UART_FCR_DMA_MODE_SELECT (1u << 3)
#define UART_FCR_RCVR_TRIGGER_SHIFT 6
#define UART_FCR_RCVR_TRIGGER_MASK (3u << UART_FCR_RCVR_TRIGGER_SHIFT)

// IIR interrupt IDs (corresponding to the IntrID enum)
#define UART_INTR_ID_RECEIVED_DATA_READY 0x2u
#define UART_INTR_ID_RECEPTION_TIMEOUT 0x6u

// Trigger-level mapping (1 byte / 4 bytes)
#define UART_RX_TRIGGER_CFG_1BYTE 0u // rcvr_trigger = 0b00
#define UART_RX_TRIGGER_CFG_4BYTE 1u // rcvr_trigger = 0b01

static inline uint32_t get_uart_reg_base(uint32_t idx) {
    if (idx == 0) return SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0);
    if (idx == 1) return SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(1);
    if (idx == 2) return SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(2);
    return SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(3);
}

static inline uint32_t get_uart_ctrl_reg_addr(uint32_t idx) {
    if (idx == 0)
        return SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(0);
    if (idx == 1)
        return SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(1);
    if (idx == 2)
        return SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(2);
    return SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(3);
}

static void uart_enable_single(uint32_t idx) {
    uart_log_engine_ctrl__CTRL_t uart_enables;
    uart_enables.w =
        read_reg(SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(0));
    uart_enables.f.UART_EN = 0x1;

    uint32_t ctrl_addr = get_uart_ctrl_reg_addr(idx);
    write_reg(ctrl_addr, uart_enables.w);
}

static void uart_init_loopback(uint32_t uart_base) {
    uart_16550_main__LCR_t lcr;
    uart_16550_main__MCR_t mcr;
    uart_16550_main__IER_t ier;
    uint32_t divisor = 1u; // Simple choice of a valid divisor (divide-by-1).

    // Read default values.
    mcr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    lcr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    ier.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));

    // First program the divisor (DLL/DLH accessed via DLAB=1).
    lcr.f.DLAB = 0x1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              lcr.w);
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              divisor & 0xFFu); // DLL
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              (divisor >> 8) & 0xFFu); // DLH

    // 8N1 configuration (word length = 8 bits, 1 stop, no parity).
    lcr.f.DLAB = 0x0;
    lcr.f.WLS = 0x3; // 8 bits
    lcr.f.STB = 0x0;
    lcr.f.PEN = 0x0;
    lcr.f.EPS = 0x0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              lcr.w);

    // Enable loopback mode so TX is internally looped back to RX.
    mcr.f.LOOP = 0x1;
    mcr.f.RTS = 0x1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              mcr.w);

    // Enable RX interrupt (keep the rest unchanged).
    ier.f.ERBFI = 0x1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              ier.w);
}

static void uart_fifo_set_trigger(uint32_t uart_base, uint32_t trigger_cfg) {
    uint32_t fcr = 0;

    fcr |= UART_FCR_FIFO_ENABLE;
    // Use DMA mode 0.
    fcr &= ~UART_FCR_DMA_MODE_SELECT;
    // Configure RX trigger level (low two bits are in FCR[7:6]).
    fcr &= ~UART_FCR_RCVR_TRIGGER_MASK;
    fcr |= (trigger_cfg << UART_FCR_RCVR_TRIGGER_SHIFT);

    // Write FCR (write-only, shares the address with IIR).
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              fcr);
}

static void uart_fifo_reset(uint32_t uart_base, int reset_rx, int reset_tx) {
    uint32_t fcr = 0;

    fcr |= UART_FCR_FIFO_ENABLE;
    if (reset_rx) fcr |= UART_FCR_RCVR_FIFO_RESET;
    if (reset_tx) fcr |= UART_FCR_XMIT_FIFO_RESET;

    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              fcr);
}

// Under a specified trigger level, verify:
// 1. Write (trigger_level + 1) bytes and check whether RECEPTION_TIMEOUT occurs.
// 2. When RECEPTION_TIMEOUT occurs, read 1 byte to clear the timeout condition.
// 3. Then check whether RECEIVED_DATA_READY is seen (to confirm the FIFO trigger for RDR is still
// effective).
static int uart_test_rx_trigger(uint32_t uart_base, uint32_t trigger_cfg, uint32_t trigger_level) {
    uart_16550_main__IIR_t iir;

    simputshex32("Testing Trigger Level. Config=", trigger_cfg);
    simputs("\n");
    simputshex32("Expected Trigger at depth=", trigger_level);
    simputs("\n");
    // First reset the FIFO and configure the trigger level.
    uart_fifo_reset(uart_base, 1, 1);
    uart_fifo_set_trigger(uart_base, trigger_cfg);

    // Clear any residual status.
    (void)read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                                SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    (void)read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                                SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));

    // Write (trigger_level + 1) bytes in one shot without checking interrupts in between,
    // allowing RX FIFO depth to exceed the threshold before observing timeout and RDR behavior.
    for (uint32_t depth = 1; depth <= (trigger_level + 1u); depth++) {
        write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                               SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  0x30u + depth);
    }

    // Step 1: check whether RECEPTION_TIMEOUT appears first.
    {
        int seen_timeout = 0;
        int max_iters = 128;

        for (int iter = 0; iter < max_iters; iter++) {
            simputs(" -> iir read!\n");
            iir.w = read_reg(uart_base +
                             (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                              SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
            if (iir.f.INTERRUPT_PENDING == 0u) {
                if (iir.f.INTERRUPT_ID == UART_INTR_ID_RECEPTION_TIMEOUT) {
                    seen_timeout = 1;
                    simputs("    -> Interrupt ID = RECEPTION_TIMEOUT detected\n");
                    break;
                }
            }
        }

        if (!seen_timeout) {
            simputs("    [ERROR] RECEPTION_TIMEOUT not seen after (trigger_level + 1) writes!\n");
            return -2;
        }
    }

    // Step 2: read 1 byte to clear the timeout condition; the FIFO is expected to still hold data
    // at the trigger level, so RECEIVED_DATA_READY should be observed.
    {
        int seen_rdr = 0;
        int max_iters = 128;

        // Read 1 byte to emulate an ISR popping one entry while handling the timeout.
        (void)read_reg(uart_base +
                       (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                        SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));

        for (int iter = 0; iter < max_iters; iter++) {
            simputs(" -> iir read (after timeout clear)!\n");
            iir.w = read_reg(uart_base +
                             (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                              SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
            if (iir.f.INTERRUPT_PENDING == 0u) {
                if (iir.f.INTERRUPT_ID == UART_INTR_ID_RECEIVED_DATA_READY) {
                    seen_rdr = 1;
                    simputs(
                        "    -> Interrupt ID = RECEIVED_DATA_READY observed after timeout clear\n");
                    break;
                }
            }
        }

        if (!seen_rdr) {
            simputs("    [ERROR] RECEIVED_DATA_READY not seen after clearing timeout!\n");
            return -3;
        }
    }

    simputs("Trigger Test Passed.\n");
    return 0;
}

// Test whether TX/RX FIFO reset clears data and status.
static int uart_test_fifo_reset(uint32_t uart_base) {
    uart_16550_main__LSR_t lsr;
    uart_16550_main__IIR_t iir;

    simputs("=== FIFO Reset Subtest ===\n");

    // First ensure FIFO is enabled and the trigger level is set to the minimum.
    simputs("  [STEP] Enable FIFO & set trigger to 1 byte\n");
    uart_fifo_reset(uart_base, 1, 1);
    uart_fifo_set_trigger(uart_base, UART_RX_TRIGGER_CFG_1BYTE);

    // Fill several bytes so RX FIFO becomes non-empty.
    simputs("  [STEP] Fill RX FIFO with 4 bytes\n");
    for (int i = 0; i < 4; i++) {
        write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                               SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  0x40u + (uint32_t)i);
    }

    // Wait for TX to fully drain so no in-flight byte lands in the RX FIFO
    // right after the reset below.
    {
        int seen_temt = 0;
        int max_iters = 512;

        for (int iter = 0; iter < max_iters; iter++) {
            lsr.w = read_reg(uart_base +
                             (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                              SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
            if (lsr.f.TEMT == 1u) {
                seen_temt = 1;
                break;
            }
        }

        if (!seen_temt) {
            simputs("    [ERROR] TX did not drain (TEMT=0) before RX reset\n");
            simputshex32("    LSR = 0x", lsr.w);
            simputs("\n");
            return -2;
        }
    }

    // Let the final byte finish shifting through the RX side after TEMT=1.
    for (int iter = 0; iter < 64; iter++) {
        (void)read_reg(uart_base +
                       (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                        SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    }

    // Confirm that LSR.DR (data ready) is 1.
    simputs("  [CHECK] LSR.DR should be 1 before RX reset\n");
    lsr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    if (lsr.f.DR == 0u) {
        simputs("    [ERROR] LSR.DR == 0 before RX reset (expected data ready)\n");
        simputshex32("    LSR = 0x", lsr.w);
        simputs("\n");
        return -3; // Data should already be ready.
    }

    // Perform RX reset.
    simputs("  [STEP] Do RX FIFO reset\n");
    uart_fifo_reset(uart_base, 1, 0);

    // Read LSR and expect DR = 0 (FIFO has been emptied).
    simputs("  [CHECK] LSR.DR should be 0 after RX reset\n");
    lsr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    if (lsr.f.DR != 0u) {
        simputs("    [ERROR] LSR.DR != 0 after RX reset (FIFO not empty?)\n");
        simputshex32("    LSR = 0x", lsr.w);
        simputs("\n");
        return -4; // Data still remains after reset.
    }

    // Read IIR and confirm that RECEIVED_DATA_READY is no longer reported.
    simputs("  [CHECK] IIR should not report RECEIVED_DATA_READY after RX reset\n");
    iir.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    if (iir.f.INTERRUPT_PENDING == 0u && iir.f.INTERRUPT_ID == UART_INTR_ID_RECEIVED_DATA_READY) {
        simputs("    [ERROR] RX ready interrupt still pending after RX reset\n");
        simputshex32("    IIR = 0x", iir.w);
        simputshex32("    IIR.ID = 0x", (uint32_t)iir.f.INTERRUPT_ID);
        simputs("\n");
        return -5; // RX ready interrupt should not be pending after reset.
    }

    // TX side: fill until THRE==0 (TX holding data), then XMIT reset must idle.
    // Slow the divisor so the FIFO cannot drain before the pre-reset sample.
    {
        uart_16550_main__LCR_t lcr;
        const uint32_t slow_div = 32u;

        lcr.w =
            read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        lcr.f.DLAB = 0x1u;
        write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                               SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  lcr.w);
        write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                               SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  slow_div & 0xFFu);
        write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                               SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  (slow_div >> 8) & 0xFFu);
        lcr.f.DLAB = 0x0u;
        write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                               SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  lcr.w);
    }

    simputs("  [STEP] Fill TX FIFO until THRE==0\n");
    {
        int saw_thre0 = 0;
        for (int i = 0; i < 16; i++) {
            write_reg(uart_base +
                          (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                      0x50u + (uint32_t)i);
            lsr.w = read_reg(uart_base +
                             (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                              SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
            if (lsr.f.THRE == 0u) {
                saw_thre0 = 1;
                break;
            }
        }

        if (!saw_thre0) {
            simputs("    [ERROR] THRE never 0 before TX reset (TX not holding data)\n");
            simputshex32("    LSR = 0x", lsr.w);
            simputs("\n");
            return -6;
        }
    }

    // Pre-reset proof: TX must still hold data so post-idle cannot be natural drain alone.
    simputs("  [CHECK] LSR.THRE should be 0 before TX reset\n");
    lsr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    if (lsr.f.THRE != 0u) {
        simputs("    [ERROR] LSR.THRE != 0 before TX reset\n");
        simputshex32("    LSR = 0x", lsr.w);
        simputs("\n");
        return -7;
    }

    // Perform TX reset.
    simputs("  [STEP] Do TX FIFO reset\n");
    uart_fifo_reset(uart_base, 0, 1);

    // XMIT FIFO reset must raise THRE immediately (FIFO empty). TEMT may lag while
    // a character already in the shift register drains at the slow divisor — wait
    // for TEMT separately with a long poll (fail-closed).
    simputs("  [CHECK] LSR.THRE should be 1 after TX reset\n");
    lsr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    if (lsr.f.THRE != 1u) {
        simputs("    [ERROR] LSR.THRE != 1 after TX reset (FIFO not cleared)\n");
        simputshex32("    LSR = 0x", lsr.w);
        simputs("\n");
        return -8;
    }

    {
        int seen_temt = 0;
        const int max_iters = 4096;

        for (int iter = 0; iter < max_iters; iter++) {
            lsr.w = read_reg(uart_base +
                             (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                              SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
            if (lsr.f.TEMT == 1u) {
                seen_temt = 1;
                break;
            }
        }

        if (!seen_temt) {
            simputs("    [ERROR] LSR.TEMT != 1 after TX reset (shifter not idle)\n");
            simputshex32("    LSR = 0x", lsr.w);
            simputs("\n");
            return -9;
        }
    }

    simputs("=== FIFO Reset Subtest Passed ===\n");

    return 0;
}

int main(void) {
    simputs("\n=== Starting UART FIFO Basic Trigger Reset Test ===\n");

    uint32_t uart_idx = 0; // Test a single UART instance.
    uint32_t uart_base = get_uart_reg_base(uart_idx);

    // Enable the target UART and initialize it in loopback mode.
    uart_enable_single(uart_idx);
    uart_init_loopback(uart_base);

    simputs("Checking 1-byte Trigger Level...\n");
    // Test RX trigger level = 1 byte.
    if (uart_test_rx_trigger(uart_base, UART_RX_TRIGGER_CFG_1BYTE, 1u) != 0) {
        simputs("1-byte Trigger Test FAILED!\n");
        test_fail(0);
    }

    simputs("Checking 4-byte Trigger Level...\n");
    // Test RX trigger level = 4 bytes (higher threshold).
    if (uart_test_rx_trigger(uart_base, UART_RX_TRIGGER_CFG_4BYTE, 4u) != 0) {
        simputs("4-byte Trigger Test FAILED!\n");
        test_fail(0);
    }

    simputs("Checking FIFO Reset...\n");
    // Test FIFO reset behavior.
    if (uart_test_fifo_reset(uart_base) != 0) {
        simputs("FIFO Reset Test FAILED!");
        test_fail(0);
    }

    simputs("ALL TESTS PASSED!");
    test_pass(0);

    while (1) {
        __asm__("wfi");
    }

    return 0;
}
