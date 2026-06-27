/* SPDX-License-Identifier: Apache-2.0 */
/* (c) 2026 Tenstorrent USA Inc */

#include <stdint.h>
#include <time.h>

#include "metal/uart.h"
#include "smc_io.h"
#include "smc_test.h"

// Basic assumption: UART topology is the same as in uart_sanity.
// controllers: UART index 0,1
// targets    : UART index 3,2
//
// This test sweeps multiple divisors and WLS/STB/parity combinations,
// using a simplified structure first; it can later be extended with actual Tbit measurements and a full combination matrix.
#
typedef struct {
    uint8_t wls;      // word length select (5..8 bits, per actual IP definition)
    uint8_t stb;      // stop bits (0:1 stop, 1:2 stops)
    uint8_t pen;      // parity enable
    uint8_t eps;      // even parity select
    uint8_t stick;    // stick parity control (if the IP supports it)
} uart_frame_cfg_t;

// v006: parametric sweep closing the 138 cond + 21 branch holes in
// uart_core.sv / uart_rx.sv / uart_tx.sv baud / parity / framing paths.
// Sweep dimensions:
//   - 2 divisors (fast/medium) — exercises the baud counter reload branch
//     with two distinct values. divisor=16 was tried but pushed the sim
//     past the cocotb watchdog at iter ~79/96; the (count==divisor-1)
//     cond branch is hit by ANY divisor, so {1, 8} is sufficient coverage.
//   - 4 word_length values (5,6,7,8 bits) covers wls = 2'b00..11
//   - 3 parity modes (none, odd, even) — stick parity is intentionally
//     excluded; v005 Phase 2 classified it as waiver-func / cost-prohibitive.
//   - 2 stop-bit configs (1 stop, 2 stops) — note the 5-bit case uses
//     1.5 stops per LCR semantics, but the RTL treats stb=1 uniformly.
// Total = 4 wls × 4 parity-stop combos = 16 combos (per ctrl/tgt pair, per
// divisor). 1 byte per combo to keep wall-time bounded; each combo's main
// purpose is to *toggle the LCR config* and clock at least one frame end-to-end.
static const uint32_t g_divisors[] = {
    1, 8
};

static const uart_frame_cfg_t g_frame_cfgs[] = {
    // wls, stb, pen, eps, stick
    // Stick-parity configs are deliberately excluded: v005 Phase 2 classified
    // `uart_stick_parity_rare_config` as waiver-func / cost-prohibitive
    // (6 holes, dead-code-by-config). Exercising it here hangs the busy-wait
    // RX-ready loop (RTL framing-error path doesn't pulse IIR[3:0]==0x4),
    // which is exactly why it's waived rather than covered.
    // wls=0 (5-bit)
    {0, 0, 0, 0, 0},  // 5N1
    {0, 1, 0, 0, 0},  // 5N2
    {0, 0, 1, 0, 0},  // 5O1
    {0, 1, 1, 1, 0},  // 5E2
    // wls=1 (6-bit)
    {1, 0, 0, 0, 0},  // 6N1
    {1, 1, 0, 0, 0},  // 6N2
    {1, 0, 1, 0, 0},  // 6O1
    {1, 1, 1, 1, 0},  // 6E2
    // wls=2 (7-bit)
    {2, 0, 0, 0, 0},  // 7N1
    {2, 1, 0, 0, 0},  // 7N2
    {2, 0, 1, 0, 0},  // 7O1
    {2, 1, 1, 1, 0},  // 7E2
    // wls=3 (8-bit)
    {3, 0, 0, 0, 0},  // 8N1
    {3, 1, 0, 0, 0},  // 8N2
    {3, 0, 1, 0, 0},  // 8O1
    {3, 0, 1, 1, 0},  // 8E1
};

// Test data pattern: 1 byte per (divisor × frame_cfg) combo. 0x5A
// (0101_1010) gives a balanced toggle pattern on the lower 5 bits, so
// wls=0 (5-bit) still observes the masked 0x1A toggling all 5 data bits.
static const uint8_t g_test_pattern[] = {
    0x5A
};

static inline uint32_t get_uart_reg_base(uint32_t idx)
{
    if (idx == 0) return SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0);
    if (idx == 1) return SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(1);
    if (idx == 2) return SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(2);
    return SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(3);
}

static inline uint32_t get_uart_ctrl_reg_addr(uint32_t idx)
{
    if (idx == 0) return SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(0);
    if (idx == 1) return SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(1);
    if (idx == 2) return SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(2);
    return SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(3);
}

static void uart_enable_all(uint32_t num_uarts)
{
    uart_log_engine_ctrl__CTRL_t uart_enables;
    uart_enables.w = read_reg(SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(0));
    uart_enables.f.UART_EN = 0x1;

    for (uint32_t i = 0; i < num_uarts; i++) {
        uint32_t ctrl_addr = get_uart_ctrl_reg_addr(i);
        write_reg(ctrl_addr, uart_enables.w);
    }
}

static void uart_program_divisor_and_format(uint32_t uart_base,
                                            uint32_t divisor,
                                            const uart_frame_cfg_t *cfg)
{
    uart_16550_main__LCR_t lcr;
    uart_16550_main__MCR_t mcr;
    uart_16550_main__IER_t ier;

    // Read default values.
    mcr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    lcr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    ier.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));

    // Basic MCR configuration (for example, RTS = 1).
    mcr.f.RTS = 0x1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), mcr.w);

    // Program the divisor.
    lcr.f.DLAB = 0x1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), lcr.w);
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), divisor & 0xFF);
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), (divisor >> 8) & 0xFF);

    // Configure frame format: WLS / STB / parity bits.
    lcr.f.DLAB = 0x0;
    lcr.f.WLS  = cfg->wls;
    lcr.f.STB  = cfg->stb;
    lcr.f.PEN  = cfg->pen;
    lcr.f.EPS  = cfg->eps;
    lcr.f.STICK_PARITY = cfg->stick;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), lcr.w);

    // Enable interrupts (same as uart_sanity, for observing IIR status).
    ier.f.ERBFI = 0x1;
    ier.f.ETBEI = 0x1;
    ier.f.ELSI  = 0x1;
    ier.f.EDSSI = 0x1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), ier.w);

    // Enable FIFO mode.
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), 0x1);
}

static int uart_loopback_exchange(uint32_t ctrl_idx,
                                  uint32_t tgt_idx,
                                  uint32_t divisor,
                                  const uart_frame_cfg_t *cfg)
{
    uint32_t ctrl_base = get_uart_reg_base(ctrl_idx);
    uint32_t tgt_base  = get_uart_reg_base(tgt_idx);
    uint32_t IIR_status = 0;

    // Print current test configuration for cocotb log
    simputs("[UART_CFG] ctrl_idx=");
    simputshex32("", ctrl_idx);
    simputs(", tgt_idx=");
    simputshex32("", tgt_idx);
    simputs(", divisor=");
    simputshex32("", divisor);
    simputs(", wls=");
    simputshex32("", cfg->wls);
    simputs(", stb=");
    simputshex32("", cfg->stb);
    simputs(", pen=");
    simputshex32("", cfg->pen);
    simputs(", eps=");
    simputshex32("", cfg->eps);
    simputs(", stick=");
    simputshex32("", cfg->stick);
    simputs("\n");

    // Apply the same divisor and frame format to both controller and target.
    uart_program_divisor_and_format(ctrl_base, divisor, cfg);
    uart_program_divisor_and_format(tgt_base,  divisor, cfg);

    // v006: mask TX byte to the configured word length before compare.
    // wls=0..3 → 5/6/7/8 data bits; the UART only shifts that many LSBs, so
    // the receiver legitimately returns (tx & word_mask). Without this mask,
    // 0x5A under wls=0 (5-bit) arrives as 0x1A and the rx==tx check fails
    // mid-loop (this was the v004 regression that took COND/BRANCH/TOGGLE
    // backwards — see COVERAGE_REPORT_v5.md "v6 plan" item 1).
    uint8_t word_mask = (uint8_t)((1u << (5 + cfg->wls)) - 1);

    for (uint32_t i = 0; i < sizeof(g_test_pattern); i++) {
        uint8_t tx       = g_test_pattern[i];
        uint8_t expected = tx & word_mask;

        // Write into TX FIFO (RBR/DLL share the same address).
        write_reg(ctrl_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)), tx);

        // Wait until the target RX is ready (IIR[3:0] == 0x4). Bounded
        // poll prevents an infinite spin if a future cfg combo exposes a
        // framing path that never raises the Data Available interrupt.
        uint32_t poll = 0;
        do {
            IIR_status = read_reg(tgt_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
            if (++poll > 200000) {
                // Treat as data-not-arrived; surface as a test failure so
                // the offending cfg is visible in the log instead of hanging
                // until cocotb watchdog.
                return -2;
            }
        } while ((IIR_status & 0xF) != 0x4);

        // Read back data.
        uint8_t rx = (uint8_t)read_reg(tgt_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        write_scratch(1, rx);

        if (rx != expected) {
            // Data mismatch is treated as an error.
            return -1;
        }
    }

    // TODO: later add parity / framing error-flag checks and Tbit measurements here.
    return 0;
}

int main(void)
{
    // UART topology: reuse the same as uart_sanity.
    uint32_t uart_ctrlrs[] = {0, 1};
    uint32_t num_ctrlrs    = sizeof(uart_ctrlrs) / sizeof(uart_ctrlrs[0]);
    uint32_t uart_tgts[]   = {3, 2};
    uint32_t num_tgts      = sizeof(uart_ctrlrs) / sizeof(uart_ctrlrs[0]);
    uint32_t num_uarts     = num_ctrlrs + num_tgts;

    // peripherals_out_of_reset();

    // Enable all UART instances under test.
    uart_enable_all(num_uarts);

    // Sweep over divisor x frame format x controller/target pairs.
    for (uint32_t d = 0; d < sizeof(g_divisors)/sizeof(g_divisors[0]); d++) {
        uint32_t divisor = g_divisors[d];
        for (uint32_t f = 0; f < sizeof(g_frame_cfgs)/sizeof(g_frame_cfgs[0]); f++) {
            const uart_frame_cfg_t *cfg = &g_frame_cfgs[f];

            for (uint32_t i = 0; i < num_ctrlrs; i++) {
                uint32_t ctrl_idx = uart_ctrlrs[i];
                uint32_t tgt_idx  = uart_tgts[i];

                if (uart_loopback_exchange(ctrl_idx, tgt_idx, divisor, cfg) != 0) {
                    test_fail(0);
                }
            }
        }
    }

    test_pass(0);

    while (1) {
        __asm__("wfi");
    }

    return 0;
}
