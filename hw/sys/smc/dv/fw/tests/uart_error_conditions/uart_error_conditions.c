/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Verifies that the UART receiver flags a parity error, an RX overrun and a
// break in its line status, and raises the line status interrupt for each.
// Framing error is not injected, and a break need only raise the break flag.
// To limit simulation time, overrun and break run on one UART in loopback.

#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"

// IIR interrupt IDs, as in the 16550 specification.
#define UART_INTR_ID_RECEIVED_DATA_READY 0x2u
#define UART_INTR_ID_RECEIVER_LINE_STATUS 0x3u

// FCR shares its address with IIR and is write-only.
#define UART_FCR_FIFO_ENABLE (1u << 0)

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

static void uart_enable_pair(uint32_t idx_a, uint32_t idx_b) {
    uart_enable_single(idx_a);
    if (idx_b != idx_a) {
        uart_enable_single(idx_b);
    }
}

// Configure a single UART as 8N1 with loopback, basic interrupts enabled, and FIFO enabled.
static void uart_init_8n1_loopback(uint32_t uart_base) {
    // Any non-zero divisor starts TX/RX; the smallest keeps simulation time short.
    const uint32_t divisor = 1u;
    uart_16550_main__LCR_t lcr;
    uart_16550_main__MCR_t mcr;
    uart_16550_main__IER_t ier;

    lcr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    mcr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    ier.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));

    // Program the divisor first to start the baud generator.
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

    // 8N1: 8 data bits, no parity, 1 stop bit.
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

// Clear status left over from earlier cases.
static void uart_clear_status(uint32_t uart_base) {
    (void)read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                                SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    (void)read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                                SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    (void)read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                                SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
}

// Case 2: RX overrun.
static int uart_test_overrun(uint32_t uart_idx) {
    const uint32_t fifo_depth = 32u; // RX FIFO depth of the default configuration.
    const uint32_t extra_bytes = 4u; // A few bytes beyond the FIFO depth force the overrun.

    const uint32_t uart_base = get_uart_reg_base(uart_idx);
    uart_16550_main__LSR_t lsr;
    uart_16550_main__IIR_t iir;

    simputs("\n[UART_ERROR] Case 2: RX Overrun start\n");
    simputshex32("  uart_idx   = ", uart_idx);
    simputshex32("  uart_base  = ", uart_base);

    uart_init_8n1_loopback(uart_base);
    uart_clear_status(uart_base);

    // Send one byte at a time and wait until RX has it, without reading it, so
    // the RX FIFO overflows.
    uint32_t total_bytes = fifo_depth + extra_bytes;
    for (uint32_t i = 0; i < total_bytes; i++) {
        uint32_t tx_val = 0x20u + (i & 0x3Fu);
        write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                               SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  tx_val);
        if ((i < 4u) || (i >= total_bytes - 4u)) {
            simputshex32("    Wrote byte, index=", i);
        }

        // A received-data interrupt confirms RX has seen this byte.
        int saw_rdr = 0;
        for (int wait = 0; wait < 512; wait++) {
            iir.w = read_reg(uart_base +
                             (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                              SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
            if ((iir.f.INTERRUPT_PENDING == 0u) &&
                (iir.f.INTERRUPT_ID == UART_INTR_ID_RECEIVED_DATA_READY)) {
                saw_rdr = 1;
                break;
            }
        }
        if (!saw_rdr) {
            simputs("  [ERROR] Did not see RDR interrupt after TX write\n");
            simputshex32("    IIR = 0x", iir.w);
            return 0x10;
        }
    }

    lsr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    iir.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    simputshex32("  LSR after (depth+extra) writes = 0x", lsr.w);
    simputshex32("  IIR after (depth+extra) writes = 0x", iir.w);

    // Poll for the overrun flag.
    int saw_oe = 0;
    for (int iter = 0; iter < 1024; iter++) {
        lsr.w =
            read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        if (lsr.f.OE) {
            saw_oe = 1;
            simputshex32("  Detected OE=1 while polling, iter=", (uint32_t)iter);
            break;
        }
    }
    if (!saw_oe) {
        iir.w =
            read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        simputs("  [ERROR] Expected RX overrun, but LSR.OE never set\n");
        simputshex32("    Final LSR = 0x", lsr.w);
        simputshex32("    Final IIR = 0x", iir.w);
        return 1;
    }

    int saw_line_status_intr = 0;
    for (int iter = 0; iter < 32; iter++) {
        iir.w =
            read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        if ((iir.f.INTERRUPT_PENDING == 0u) &&
            (iir.f.INTERRUPT_ID == UART_INTR_ID_RECEIVER_LINE_STATUS)) {
            saw_line_status_intr = 1;
            break;
        }
    }
    if (!saw_line_status_intr) {
        return 2;
    }

    // Drain the RX FIFO.
    for (int drain = 0; drain < 64; drain++) {
        lsr.w =
            read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        if (!lsr.f.DR) {
            break;
        }
        (void)read_reg(uart_base +
                       (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                        SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    }

    lsr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    if (lsr.f.OE) {
        // Reading LSR clears OE, so the drain loop already cleared it. This
        // only checks that OE does not re-assert once the overrun is gone.
        return 3;
    }

    return 0;
}

typedef struct {
    uint8_t wls;
    uint8_t stb;
    uint8_t pen;
    uint8_t eps;
    uint8_t stick_parity;
} uart_frame_cfg_t;

// Program the divisor and frame format of one UART, with interrupts and FIFOs enabled.
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

    mcr.f.RTS = 0x1u;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              mcr.w);

    // Divisor latch access is open only while programming the divisor.
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

    lcr.f.DLAB = 0x0u;
    lcr.f.WLS = cfg->wls;
    lcr.f.STB = cfg->stb;
    lcr.f.PEN = cfg->pen;
    lcr.f.EPS = cfg->eps;
    lcr.f.STICK_PARITY = cfg->stick_parity;
    lcr.f.SET_BREAK = 0u;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              lcr.w);

    // Enable interrupts (including line status).
    ier.f.ERBFI = 0x1u;
    ier.f.ETBEI = 0x1u;
    ier.f.ELSI = 0x1u;
    ier.f.EDSSI = 0x1u;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              ier.w);

    // Enable FIFO.
    uint32_t fcr = UART_FCR_FIFO_ENABLE;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              fcr);
}

// Case 1: parity error from a controller/target parity mismatch.
static int uart_test_parity_error(uint32_t ctrl_idx, uint32_t tgt_idx) {
    const uint32_t ctrl_base = get_uart_reg_base(ctrl_idx);
    const uint32_t tgt_base = get_uart_reg_base(tgt_idx);
    const uint32_t divisor = 1u;

    uart_16550_main__LSR_t lsr;
    uart_16550_main__IIR_t iir;

    simputs("\n[UART_ERROR] Case 1: Parity Error start\n");
    simputshex32("  ctrl_idx  = ", ctrl_idx);
    simputshex32("  ctrl_base = ", ctrl_base);
    simputshex32("  tgt_idx   = ", tgt_idx);
    simputshex32("  tgt_base  = ", tgt_base);

    // Controller sends 8O1 and target expects 8E1.
    const uart_frame_cfg_t cfg_ctrl = {
        .wls = 3u, .stb = 0u, .pen = 1u, .eps = 0u, .stick_parity = 0u};
    const uart_frame_cfg_t cfg_tgt = {
        .wls = 3u, .stb = 0u, .pen = 1u, .eps = 1u, .stick_parity = 0u};

    uart_program_divisor_and_format(ctrl_base, divisor, &cfg_ctrl);
    uart_program_divisor_and_format(tgt_base, divisor, &cfg_tgt);

    uart_clear_status(ctrl_base);
    uart_clear_status(tgt_base);

    static const uint8_t test_pattern[] = {0x00u, 0xFFu, 0x55u, 0xAAu};

    for (uint32_t i = 0; i < sizeof(test_pattern); i++) {
        uint8_t tx = test_pattern[i];

        simputshex32("  [Case1] TX byte index=", i);
        simputshex32("    TX data = 0x", tx);

        write_reg(ctrl_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                               SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  tx);

        // Poll the target for both the parity error flag and the line status interrupt.
        int local_saw_pe = 0;
        int local_saw_line_status_intr = 0;

        for (int iter = 0; iter < 512; iter++) {
            lsr.w = read_reg(tgt_base +
                             (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                              SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
            if (lsr.f.PE) {
                local_saw_pe = 1;
                simputshex32("    LSR.PE set at iter=", (uint32_t)iter);
                simputshex32("      LSR = 0x", lsr.w);
            }

            // Line status has priority over received data in IIR.
            iir.w = read_reg(tgt_base +
                             (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                              SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
            if ((iir.f.INTERRUPT_PENDING == 0u) &&
                (iir.f.INTERRUPT_ID == UART_INTR_ID_RECEIVER_LINE_STATUS)) {
                local_saw_line_status_intr = 1;
                simputshex32("    IIR Line Status ID seen at iter=", (uint32_t)iter);
                simputshex32("      IIR = 0x", iir.w);
            }

            if (local_saw_pe && local_saw_line_status_intr) {
                break;
            }
        }

        if (!local_saw_pe) {
            simputs("  [ERROR] Case1: Expected LSR.PE=1 but never observed\n");
            return 10;
        }
        if (!local_saw_line_status_intr) {
            simputs("  [ERROR] Case1: Parity error occurred but no Line Status interrupt seen\n");
            return 11;
        }

        // Clear RX.
        (void)read_reg(tgt_base +
                       (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                        SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    }

    // With matching parity on both ends, bytes arrive with no error flag.
    const uart_frame_cfg_t cfg_even = {
        .wls = 3u, .stb = 0u, .pen = 1u, .eps = 1u, .stick_parity = 0u};
    uart_program_divisor_and_format(ctrl_base, divisor, &cfg_even);
    uart_program_divisor_and_format(tgt_base, divisor, &cfg_even);

    uart_clear_status(ctrl_base);
    uart_clear_status(tgt_base);

    for (uint32_t i = 0; i < sizeof(test_pattern); i++) {
        uint8_t tx = test_pattern[i];
        write_reg(ctrl_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                               SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  tx);

        int data_ready = 0;
        for (int iter = 0; iter < 64; iter++) {
            iir.w = read_reg(tgt_base +
                             (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                              SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
            if ((iir.f.INTERRUPT_PENDING == 0u) &&
                (iir.f.INTERRUPT_ID == UART_INTR_ID_RECEIVED_DATA_READY)) {
                data_ready = 1;
                break;
            }
        }
        if (!data_ready) {
            return 14;
        }

        lsr.w =
            read_reg(tgt_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                                 SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        if (lsr.f.PE || lsr.f.FE || lsr.f.BI) {
            simputshex32(
                "  [ERROR] Case1: Unexpected error flags in LSR after parity-fixed TX, LSR=0x",
                lsr.w);
            return 15;
        }
        (void)read_reg(tgt_base +
                       (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                        SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    }

    return 0;
}

// Case 3: break condition, driven by the transmitter in loopback. This produces
// a break, not a missing stop bit, so no framing error is injected.
static int uart_test_break(uint32_t uart_idx) {
    const uint32_t uart_base = get_uart_reg_base(uart_idx);
    uart_16550_main__LCR_t lcr;
    uart_16550_main__LSR_t lsr;
    uart_16550_main__IIR_t iir;

    simputs("\n[UART_ERROR] Case 3: Break start\n");
    simputshex32("  uart_idx   = ", uart_idx);
    simputshex32("  uart_base  = ", uart_base);

    uart_init_8n1_loopback(uart_base);
    uart_clear_status(uart_base);

    // No framing or break flag before the break.
    lsr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    if (lsr.f.FE || lsr.f.BI) {
        simputshex32("  [ERROR] Case3: Initial LSR has FE/BI set, LSR=0x", lsr.w);
        return 20;
    }

    // TX drives a continuous break, which loops back to RX.
    lcr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    lcr.f.SET_BREAK = 1u;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              lcr.w);
    simputs("  Case3: SET_BREAK asserted (TX driving continuous low in loopback)\n");

    // Poll for the break flag; the framing flag is logged if it also sets.
    int saw_bi = 0;
    int saw_fe = 0;
    for (int iter = 0; iter < 128; iter++) {
        lsr.w =
            read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        if (lsr.f.BI) {
            saw_bi = 1;
            simputshex32("    LSR.BI set at iter=", (uint32_t)iter);
            simputshex32("      LSR = 0x", lsr.w);
        }
        if (lsr.f.FE) {
            saw_fe = 1;
            simputshex32("    LSR.FE set at iter=", (uint32_t)iter);
            simputshex32("      LSR = 0x", lsr.w);
        }
        if (saw_bi && saw_fe) {
            break;
        }
    }
    if (!saw_bi) {
        simputs("  [ERROR] Case3: Expected LSR.BI=1 under SET_BREAK but never observed\n");
        return 21;
    }

    int saw_line_status_intr = 0;
    for (int iter = 0; iter < 32; iter++) {
        iir.w =
            read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        if ((iir.f.INTERRUPT_PENDING == 0u) &&
            (iir.f.INTERRUPT_ID == UART_INTR_ID_RECEIVER_LINE_STATUS)) {
            saw_line_status_intr = 1;
            simputshex32("  Case3: Line Status interrupt seen, IIR=0x", iir.w);
            break;
        }
    }
    if (!saw_line_status_intr) {
        simputs("  [ERROR] Case3: Break condition occurred but no Line Status interrupt seen\n");
        return 22;
    }

    // Release the break, then read the status registers to clear the flags.
    lcr.f.SET_BREAK = 0u;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              lcr.w);
    simputs("  Case3: SET_BREAK deasserted\n");

    for (int iter = 0; iter < 32; iter++) {
        lsr.w =
            read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        (void)read_reg(uart_base +
                       (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                        SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        (void)read_reg(uart_base +
                       (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                        SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    }

    lsr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    if (lsr.f.FE || lsr.f.BI) {
        simputshex32("  [ERROR] Case3: FE/BI still set after clearing sequence, LSR=0x", lsr.w);
        // Reading LSR clears FE and BI, so the loop above already cleared them.
        // This only checks that they do not re-assert with no break present.
        return 23;
    }

    // The framing flag is not required: a break need only raise BI.
    return 0;
}

int main(void) {
    // UART0 receives in every case: UART3 sends it bytes with mismatched
    // parity, and overrun and break use UART0 in loopback.
    const uint32_t uart_ctrl_idx = 3u;    // controller (TX) for the parity test
    const uint32_t uart_tgt_idx = 0u;     // target (RX, PE detected here)
    const uint32_t uart_overrun_idx = 0u; // loopback overrun test
    const uint32_t uart_break_idx = 0u;   // break test

    simputs("\n");
    simputs("========================================\n");
    simputs(" UART Error Conditions Test\n");
    simputs("  - Case 1: Parity Error\n");
    simputs("  - Case 2: RX Overrun\n");
    simputs("  - Case 3: Break Condition\n");
    simputs("========================================\n");
    simputs("\n");

    uart_enable_pair(uart_ctrl_idx, uart_tgt_idx);
    uart_enable_single(uart_overrun_idx);
    uart_enable_single(uart_break_idx);

    int rc = uart_test_parity_error(uart_ctrl_idx, uart_tgt_idx);
    if (rc != 0) {
        simputs("ERROR: UART Error Conditions - Case 1 (Parity Error) FAILED\n");
        simputshex32("  rc = ", (uint32_t)rc);
        write_scratch(0, 0xBAD00010u | ((uint32_t)rc & 0xFFu));
        test_fail(0);
    }
    simputs("INFO: UART Error Conditions - Case 1 (Parity Error) PASSED\n");

    rc = uart_test_overrun(uart_overrun_idx);
    if (rc != 0) {
        simputs("ERROR: UART Error Conditions - Case 2 (RX Overrun) FAILED\n");
        simputshex32("  rc = ", (uint32_t)rc);
        write_scratch(0, 0xBAD00020u | ((uint32_t)rc & 0xFFu));
        test_fail(0);
    }
    simputs("INFO: UART Error Conditions - Case 2 (RX Overrun) PASSED\n");

    rc = uart_test_break(uart_break_idx);
    if (rc != 0) {
        simputs("ERROR: UART Error Conditions - Case 3 (Break) FAILED\n");
        simputshex32("  rc = ", (uint32_t)rc);
        write_scratch(0, 0xBAD00030u | ((uint32_t)rc & 0xFFu));
        test_fail(0);
    }
    simputs("INFO: UART Error Conditions - Case 3 (Break) PASSED\n");

    simputs("\nUART Error Conditions Test: ALL CASES PASSED\n");

    test_pass(0);

    while (1) {
        __asm__("wfi");
    }
}
