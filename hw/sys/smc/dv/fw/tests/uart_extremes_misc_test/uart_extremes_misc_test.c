/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "metal/uart.h"
#include "smc_io.h"
#include "smc_test.h"
#include "virt_console.h"

// Test focus:
// - Verify SCR scratch register read/write correctness without affecting other registers.
// - Confirm no RX data or error flag appears during an idle window.

// FCR bit definitions (write-only, sharing the address with IIR)
#define UART_FCR_FIFO_ENABLE (1u << 0)
#define UART_FCR_RCVR_FIFO_RESET (1u << 1)
#define UART_FCR_XMIT_FIFO_RESET (1u << 2)
#define UART_FCR_DMA_MODE_SELECT (1u << 3)

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

// Configure a single UART as 8N1 with loopback and basic interrupt/FIFO enabled.
static void uart_init_8n1_loopback(uint32_t uart_base) {
    const uint32_t divisor =
        1u; // Any non-zero value can start TX/RX (smaller values shorten simulation time).
    uart_16550_main__LCR_t lcr;
    uart_16550_main__MCR_t mcr;
    uart_16550_main__IER_t ier;

    lcr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    mcr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    ier.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));

    // First program the divisor (DLL/DLM) to start the TX/RX baud generator.
    lcr.f.DLAB = 0x1u;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              lcr.w);
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              divisor & 0xFFu);
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              (divisor >> 8) & 0xFFu);

    // 8N1 (word length 8 bits, 1 stop, no parity).
    lcr.f.DLAB = 0u;
    lcr.f.WLS = 0x3u;
    lcr.f.STB = 0u;
    lcr.f.PEN = 0u;
    lcr.f.EPS = 0u;
    lcr.f.STICK_PARITY = 0u;
    lcr.f.SET_BREAK = 0u;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              lcr.w);

    // Loopback mode: TX is internally looped back to RX.
    mcr.f.LOOP = 0x1u;
    mcr.f.RTS = 0x1u;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              mcr.w);

    // Enable basic interrupts (including line status).
    ier.f.ERBFI = 0x1u;
    ier.f.ETBEI = 0x1u;
    ier.f.ELSI = 0x1u;
    ier.f.EDSSI = 0x1u;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              ier.w);

    // Enable FIFO (write-only FCR, sharing the address with IIR).
    uint32_t fcr = 0u;
    fcr |= UART_FCR_FIFO_ENABLE;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              fcr);
}

// Clear existing LSR/IIR/RBR status to avoid residue from previous tests.
static void uart_clear_status(uint32_t uart_base) {
    (void)read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                                SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    (void)read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                                SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    (void)read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                                SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
}

// SCR read/write and side-effect test.
static int uart_test_scr(uint32_t uart_base) {
    static const uint8_t patterns[] = {0x00u, 0xFFu, 0xA5u, 0x5Au, 0x01u, 0x02u, 0x04u, 0x08u};

    uart_16550_main__SCR_t scr;
    uart_16550_main__LCR_t lcr_before, lcr_after;
    uart_16550_main__MCR_t mcr_before, mcr_after;
    uart_16550_main__ECR_t ecr_before, ecr_after;

    simputs("UART_EXT: Testing SCR read/write...\n");

    lcr_before.w =
        read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                              SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    mcr_before.w =
        read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                              SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    ecr_before.w =
        read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ECR_BASE_ADDR(0) -
                              SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));

    for (uint32_t i = 0; i < (sizeof(patterns) / sizeof(patterns[0])); i++) {
        uint8_t pat = patterns[i];

        scr.w = 0u;
        scr.f.SCR = pat;
        write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_SCR_BASE_ADDR(0) -
                               SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  scr.w);

        uart_16550_main__SCR_t scr_rd;
        scr_rd.w =
            read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_SCR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));

        if (scr_rd.f.SCR != pat) {
            simputs("UART_EXT: [ERROR] SCR readback mismatch.\n");
            return -3;
        }
    }

    // Confirm that writing SCR does not affect LCR/MCR/ECR.
    lcr_after.w =
        read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                              SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    mcr_after.w =
        read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                              SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    ecr_after.w =
        read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ECR_BASE_ADDR(0) -
                              SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));

    if (lcr_after.w != lcr_before.w) {
        simputs("UART_EXT: [ERROR] LCR changed after SCR writes.\n");
        return -4;
    }
    if (mcr_after.w != mcr_before.w) {
        simputs("UART_EXT: [ERROR] MCR changed after SCR writes.\n");
        return -5;
    }
    if (ecr_after.w != ecr_before.w) {
        simputs("UART_EXT: [ERROR] ECR changed after SCR writes.\n");
        return -6;
    }

    simputs("UART_EXT: SCR test passed.\n");
    return 0;
}

// RX idle check: publish a phase marker in SCR for the testbench, then poll LSR over an idle
// window and fail on any data-ready or error flag.
static int uart_test_rx_noise_filter(uint32_t uart_base) {
    uart_16550_main__LSR_t lsr;
    uart_16550_main__SCR_t scr;

    simputs("UART_EXT: Entering RX noise filter idle phase...\n");

    // SCR phase marker for the testbench: 0xA1 marks entry into the idle-noise check.
    scr.w = 0u;
    scr.f.SCR = 0xA1u;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_SCR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              scr.w);

    // Simply poll for a period of time to confirm that there is no unexpected RX data or error
    // flags.
    for (int iter = 0; iter < 1024; iter++) {
        lsr.w =
            read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        if (lsr.f.DR || lsr.f.OE || lsr.f.PE || lsr.f.FE || lsr.f.BI) {
            simputs("UART_EXT: [ERROR] Unexpected RX data or error during idle noise phase.\n");
            return -7;
        }
    }

    simputs("UART_EXT: RX noise filter idle phase (basic check) passed.\n");
    return 0;
}

int main(void) {
    simputs("\n=== Starting UART Extremes & Misc Test ===\n");

    const uint32_t uart_idx = 0u; // Use a single representative UART instance.
    const uint32_t uart_base = get_uart_reg_base(uart_idx);

    uart_enable_single(uart_idx);
    uart_init_8n1_loopback(uart_base);

    if (uart_test_scr(uart_base) != 0) {
        test_fail(0);
    }

    if (uart_test_rx_noise_filter(uart_base) != 0) {
        test_fail(0);
    }

    simputs("UART_EXT: All sub-tests passed.\n");
    test_pass(0);

    while (1) {
        __asm__("wfi");
    }

    return 0;
}
