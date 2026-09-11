/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "metal/uart.h"
#include "smc_io.h"
#include "smc_test.h"

// Simple UART loopback basic-functionality test:
// - Single UART instance (index 0)
// - 8N1 frame format
// - Fixed divisor (same value as other UART tests, using 1)
// - Internal loopback: TX data should be received back on RX with no LSR error flags.

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

// Configure a single UART as 8N1 with a fixed divisor and enable internal loopback.
static void uart_init_loopback_basic(uint32_t uart_base, uint32_t divisor) {
    uart_16550_main__LCR_t lcr;
    uart_16550_main__MCR_t mcr;
    uart_16550_main__IER_t ier;

    // Read default values.
    mcr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    lcr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    ier.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));

    // Program the divisor (DLL/DLM).
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

    // Configure 8N1 (DLAB=0).
    lcr.f.DLAB = 0x0u;
    lcr.f.WLS = 0x3u; // 8 bits
    lcr.f.STB = 0x0u; // 1 stop
    lcr.f.PEN = 0x0u; // parity disable
    lcr.f.EPS = 0x0u;
    lcr.f.STICK_PARITY = 0x0u;
    lcr.f.SET_BREAK = 0x0u;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              lcr.w);

    // Enable loopback mode so TX is internally looped back to RX.
    mcr.f.LOOP = 0x1u;
    mcr.f.RTS = 0x1u;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              mcr.w);

    // Enable basic interrupts (for status observation only; the test itself uses polling).
    ier.f.ERBFI = 0x1u;
    ier.f.ETBEI = 0x1u;
    ier.f.ELSI = 0x1u;
    ier.f.EDSSI = 0x1u;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              ier.w);

    // Enable FIFO mode (FCR shares the same address as IIR).
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              0x1u);
}

int main(void) {
    static const uint8_t k_test_pattern[] = {0x00u, 0xFFu, 0x55u, 0xAAu};

    simputs("\n=== Starting UART Loopback Basic Test ===\n");

    const uint32_t uart_idx = 0u; // Only test UART index 0.
    const uint32_t uart_base = get_uart_reg_base(uart_idx);
    const uint32_t divisor = 1u;

    uart_enable_single(uart_idx);
    uart_init_loopback_basic(uart_base, divisor);

    uart_16550_main__LSR_t lsr;

    for (uint32_t i = 0; i < sizeof(k_test_pattern); i++) {
        uint8_t tx = k_test_pattern[i];

        // Wait until TX is ready (THRE = 1).
        int timeout = 0;
        do {
            lsr.w = read_reg(uart_base +
                             (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                              SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
            if (lsr.f.THRE) {
                break;
            }
        } while (++timeout < 1000);

        if (!lsr.f.THRE) {
            simputs("UART_LOOPBACK: THRE timeout\n");
            test_fail(0);
        }

        // Write one byte to TX (which loops back to RX).
        write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                               SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  tx);

        // Wait for RX data (DR = 1) while also checking error flags.
        int saw_dr = 0;
        for (int iter = 0; iter < 1000; iter++) {
            lsr.w = read_reg(uart_base +
                             (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                              SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));

            if (lsr.f.OE || lsr.f.PE || lsr.f.FE || lsr.f.BI) {
                simputs("UART_LOOPBACK: LSR error flag set\n");
                test_fail(0);
            }

            if (lsr.f.DR) {
                saw_dr = 1;
                break;
            }
        }

        if (!saw_dr) {
            simputs("UART_LOOPBACK: RX data timeout\n");
            test_fail(0);
        }

        // Read back data and compare.
        uint8_t rx = (uint8_t)read_reg(
            uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                         SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        write_scratch(1, rx);

        if (rx != tx) {
            simputs("UART_LOOPBACK: RX != TX\n");
            test_fail(0);
        }
    }

    simputs("UART_LOOPBACK: All bytes matched.\n");

    //--------------------------------------------------------------------------
    // SCENARIO 2 (v003) — LCR.SET_BREAK exercise.
    //
    // Covers uart_core.sv:272 `assign tx_out = set_break ? 1'b0 : uart_tx_out;`
    // and the corresponding branch / line coverage holes. With sys_loopback
    // still enabled (MCR.LOOP=1), set LCR.SET_BREAK=1 then transmit a byte;
    // the RX should observe a 0x00 (break-condition character) and LSR.BI
    // should latch.
    //--------------------------------------------------------------------------
    simputs("UART_LOOPBACK: scenario 2 — LCR.set_break\n");
    {
        uart_16550_main__LCR_t lcr2;
        lcr2.w =
            read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        lcr2.f.SET_BREAK = 0x1u;
        write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                               SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  lcr2.w);

        // Drive a non-zero pattern; with set_break, RX should see 0x00 and LSR.BI.
        write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                               SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  0x5Au);

        // Poll for DR|BI; expiry must fail closed.
        int saw_dr_or_bi = 0;
        uart_16550_main__LSR_t lsr2;
        for (int iter = 0; iter < 2000; iter++) {
            lsr2.w = read_reg(uart_base +
                              (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                               SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
            if (lsr2.f.DR || lsr2.f.BI) {
                saw_dr_or_bi = 1;
                break;
            }
        }

        if (!saw_dr_or_bi) {
            simputs("UART_LOOPBACK: set_break DR|BI timeout\n");
            simputshex32("  LSR = 0x", lsr2.w);
            simputs("\n");
            test_fail(0);
        }

        if (!lsr2.f.BI) {
            simputs("UART_LOOPBACK: set_break expected LSR.BI=1\n");
            simputshex32("  LSR = 0x", lsr2.w);
            simputs("\n");
            test_fail(0);
        }

        uint8_t rx_break = (uint8_t)read_reg(
            uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                         SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        if (rx_break != 0x00u) {
            simputs("UART_LOOPBACK: set_break expected RX=0x00\n");
            simputshex32("  RX = 0x", (uint32_t)rx_break);
            simputs("\n");
            test_fail(0);
        }

        // Clear set_break
        lcr2.f.SET_BREAK = 0x0u;
        write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                               SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  lcr2.w);
    }

    //--------------------------------------------------------------------------
    // SCENARIO 3 (v003) — MCR.LINE_LOOPBACK exercise.
    //
    // Covers uart_core.sv:274 `assign tx_o = line_loopback ? rx_i : tx_out_q;`
    // and :317 `line_loopback ? 1'h1 : rx_in_maj` mux selects. Toggle the bit
    // (MCR bit 5) on, then off — to also flip the path enable so VCS sees the
    // edge.
    //--------------------------------------------------------------------------
    simputs("UART_LOOPBACK: scenario 3 — MCR.LINE_LOOPBACK\n");
    {
        uart_16550_main__MCR_t mcr3;
        mcr3.w =
            read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        // Disable sys_loopback first (line_loopback path only matters when LOOP=0)
        mcr3.f.LOOP = 0x0u;
        write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                               SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  mcr3.w);

        // Enable line_loopback (MCR bit 5). Some struct definitions name this
        // field differently; if not in the bitfield, use bit-encoded write.
        // For SMC's 16550 implementation MCR bit 5 is LINE_LOOPBACK.
        uint32_t mcr_raw =
            read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                               SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  mcr_raw | (1u << 5));

        // Let a few cycles pass — the path enable propagates through tx_out_q.
        for (volatile int i = 0; i < 200; i++) { /* settle */
        }

        // Drive a TX byte; in line_loopback mode rx_in stays high so DR never
        // arrives — that's expected. The point is the branch select fires.
        write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                               SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  0xA5u);
        for (volatile int i = 0; i < 500; i++) { /* settle */
        }

        // Disable line_loopback, restore default state
        write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                               SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  mcr_raw);
    }

    simputs("UART_LOOPBACK: scenarios 2-3 complete\n");
    test_pass(0);

    while (1) {
        __asm__("wfi");
    }

    return 0;
}
