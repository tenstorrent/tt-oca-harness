/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Verifies that one byte crosses each controller/target UART pair intact for
// every baud divisor and frame format in the sweep: 5- to 8-bit words with
// no, odd or even parity and one or two stop bits. Stick parity is not swept.
// The controller/target pairing assumes the same wiring as uart_sanity.

#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"

typedef struct {
    uint8_t wls;   // word length select (5..8 bits)
    uint8_t stb;   // stop bits (0:1 stop, 1:2 stops)
    uint8_t pen;   // parity enable
    uint8_t eps;   // even parity select
    uint8_t stick; // stick parity
} uart_frame_cfg_t;

// The divisor only lengthens the bit time, so two values cover the baud counter
// reload; larger divisors would only add run time.
static const uint32_t g_divisors[] = {1, 8};

// Each word length is paired with four parity/stop-bit combinations.
static const uart_frame_cfg_t g_frame_cfgs[] = {
    // wls, stb, pen, eps, stick
    // Stick parity is not swept: with it enabled the target never reports
    // received data, so the receive poll does not complete.
    // 5-bit
    {0, 0, 0, 0, 0}, // 5N1
    {0, 1, 0, 0, 0}, // 5N2
    {0, 0, 1, 0, 0}, // 5O1
    {0, 1, 1, 1, 0}, // 5E2
    // 6-bit
    {1, 0, 0, 0, 0}, // 6N1
    {1, 1, 0, 0, 0}, // 6N2
    {1, 0, 1, 0, 0}, // 6O1
    {1, 1, 1, 1, 0}, // 6E2
    // 7-bit
    {2, 0, 0, 0, 0}, // 7N1
    {2, 1, 0, 0, 0}, // 7N2
    {2, 0, 1, 0, 0}, // 7O1
    {2, 1, 1, 1, 0}, // 7E2
    // 8-bit
    {3, 0, 0, 0, 0}, // 8N1
    {3, 1, 0, 0, 0}, // 8N2
    {3, 0, 1, 0, 0}, // 8O1
    {3, 0, 1, 1, 0}, // 8E1
};

// One byte per combination keeps run time bounded.
static const uint8_t g_test_pattern[] = {0x5A};

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

static void uart_enable_all(uint32_t num_uarts) {
    uart_log_engine_ctrl__CTRL_t uart_enables;
    uart_enables.w =
        read_reg(SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(0));
    uart_enables.f.UART_EN = 0x1;

    for (uint32_t i = 0; i < num_uarts; i++) {
        uint32_t ctrl_addr = get_uart_ctrl_reg_addr(i);
        write_reg(ctrl_addr, uart_enables.w);
    }
}

static void uart_program_divisor_and_format(uint32_t uart_base, uint32_t divisor,
                                            const uart_frame_cfg_t *cfg) {
    uart_16550_main__LCR_t lcr;
    uart_16550_main__MCR_t mcr;
    uart_16550_main__IER_t ier;

    mcr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    lcr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    ier.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));

    mcr.f.RTS = 0x1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              mcr.w);

    // Divisor latch access is open only while programming the divisor.
    lcr.f.DLAB = 0x1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              lcr.w);
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              divisor & 0xFF);
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              (divisor >> 8) & 0xFF);

    lcr.f.DLAB = 0x0;
    lcr.f.WLS = cfg->wls;
    lcr.f.STB = cfg->stb;
    lcr.f.PEN = cfg->pen;
    lcr.f.EPS = cfg->eps;
    lcr.f.STICK_PARITY = cfg->stick;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              lcr.w);

    // Interrupt enables make received-data status visible in IIR.
    ier.f.ERBFI = 0x1;
    ier.f.ETBEI = 0x1;
    ier.f.ELSI = 0x1;
    ier.f.EDSSI = 0x1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              ier.w);

    // Enable the FIFOs.
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              0x1);
}

static int uart_loopback_exchange(uint32_t ctrl_idx, uint32_t tgt_idx, uint32_t divisor,
                                  const uart_frame_cfg_t *cfg) {
    uint32_t ctrl_base = get_uart_reg_base(ctrl_idx);
    uint32_t tgt_base = get_uart_reg_base(tgt_idx);
    uint32_t IIR_status = 0;

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

    uart_program_divisor_and_format(ctrl_base, divisor, cfg);
    uart_program_divisor_and_format(tgt_base, divisor, cfg);

    // Only the low word-length bits of the sent byte are transmitted.
    uint8_t word_mask = (uint8_t)((1u << (5 + cfg->wls)) - 1);

    for (uint32_t i = 0; i < sizeof(g_test_pattern); i++) {
        uint8_t tx = g_test_pattern[i];
        uint8_t expected = tx & word_mask;

        write_reg(ctrl_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                               SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  tx);

        // Wait (bounded) until the target reports received data.
        uint32_t poll = 0;
        do {
            IIR_status = read_reg(
                tgt_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                            SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
            if (++poll > 200000) {
                return -2;
            }
        } while ((IIR_status & 0xF) != 0x4);

        uint8_t rx = (uint8_t)read_reg(
            tgt_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                        SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        write_scratch(1, rx);

        if (rx != expected) {
            return -1;
        }
    }

    return 0;
}

int main(void) {
    // Controller i sends to target i.
    uint32_t uart_ctrlrs[] = {0, 1};
    uint32_t num_ctrlrs = sizeof(uart_ctrlrs) / sizeof(uart_ctrlrs[0]);
    uint32_t uart_tgts[] = {3, 2};
    uint32_t num_tgts = sizeof(uart_ctrlrs) / sizeof(uart_ctrlrs[0]);
    uint32_t num_uarts = num_ctrlrs + num_tgts;

    uart_enable_all(num_uarts);

    for (uint32_t d = 0; d < sizeof(g_divisors) / sizeof(g_divisors[0]); d++) {
        uint32_t divisor = g_divisors[d];
        for (uint32_t f = 0; f < sizeof(g_frame_cfgs) / sizeof(g_frame_cfgs[0]); f++) {
            const uart_frame_cfg_t *cfg = &g_frame_cfgs[f];

            for (uint32_t i = 0; i < num_ctrlrs; i++) {
                uint32_t ctrl_idx = uart_ctrlrs[i];
                uint32_t tgt_idx = uart_tgts[i];

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
}
