/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "metal/uart.h"
#include "smc_io.h"
#include "smc_test.h"

// Test focus:
//  - RX overrun error -> LSR.OE + IIR line status interrupt
//  - parity error      -> LSR.PE + IIR line status interrupt (parity mismatch)
//  - break             -> LSR.BI (and opportunistically LSR.FE) + IIR line status interrupt
//                         (via set_break + loopback). Framing error is NOT injected.
//  loopback)
//
// To control simulation time, this test:
//  - primarily uses UART0 as a single-ended loopback (overrun / break)
//  - uses UART0 (controller) and UART3 (target) to test parity mismatch
//
// IIR interrupt ID definitions (aligned with the UART 16550 specification)
#define UART_INTR_ID_RECEIVED_DATA_READY 0x2u
#define UART_INTR_ID_RECEIVER_LINE_STATUS 0x3u

// FCR bit definitions (write-only, sharing an address with IIR)
#define UART_FCR_FIFO_ENABLE (1u << 0)
#define UART_FCR_RCVR_FIFO_RESET (1u << 1)
#define UART_FCR_XMIT_FIFO_RESET (1u << 2)

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

    // 8N1 (word length 8 bits, 1 stop, no parity)
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

    // 8N1 (word length 8 bits, 1 stop, no parity)
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

// Case 1: RX Overrun (LSR.OE)
static int uart_test_overrun(uint32_t uart_idx) {
    const uint32_t fifo_depth = 32u; // Same as the RTL default RX FIFO depth.
    const uint32_t extra_bytes =
        4u; // Send a few more bytes than the FIFO depth to increase overflow probability.

    const uint32_t uart_base = get_uart_reg_base(uart_idx);
    uart_16550_main__LSR_t lsr;
    uart_16550_main__IIR_t iir;

    simputs("\n[UART_ERROR] Case 2: RX Overrun start\n");
    simputshex32("  uart_idx   = ", uart_idx);
    simputshex32("  uart_base  = ", uart_base);

    uart_init_8n1_loopback(uart_base);
    uart_clear_status(uart_base);

    // Send data one byte at a time and wait for RX Ready after each send;
    // do not read RBR, so RX FIFO accumulates beyond its depth to trigger overflow.
    uint32_t total_bytes = fifo_depth + extra_bytes;
    for (uint32_t i = 0; i < total_bytes; i++) {
        uint32_t tx_val = 0x20u + (i & 0x3Fu);
        write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                               SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  tx_val);
        if ((i < 4u) || (i >= total_bytes - 4u)) {
            simputshex32("    Wrote byte, index=", i);
        }

        // Wait for a Received Data Ready (RDR) interrupt to confirm RX has seen this byte.
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
            return 0x10; // RX path itself is not functioning.
        }
    }

    // After sending (FIFO_DEPTH + extra) bytes, observe LSR/IIR again.
    lsr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    iir.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    simputshex32("  LSR after (depth+extra) writes = 0x", lsr.w);
    simputshex32("  IIR after (depth+extra) writes = 0x", iir.w);

    // Poll for a while longer to see whether OE was ever set.
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
        // If OE is still never seen, dump the last LSR/IIR snapshot for further debugging.
        iir.w =
            read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        simputs("  [ERROR] Expected RX overrun, but LSR.OE never set\n");
        simputshex32("    Final LSR = 0x", lsr.w);
        simputshex32("    Final IIR = 0x", iir.w);
        return 1; // Expected an overrun, but OE was never set.
    }

    // Check whether a line status interrupt occurred.
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
        return 2; // Line status interrupt was not seen.
    }

    // Read data out sequentially until the FIFO is empty, to confirm that OE is eventually cleared.
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
        // Not "OE was cleared by emptying the FIFO" -- LSR.OE is rclr
        // (uart_16550_main.rdl:214-219), so the drain loop's own LSR reads are
        // what cleared it, and this read would find 0 whatever the FIFO did.
        // What it does establish is that OE stays clear rather than
        // re-asserting spuriously once the overrun condition is gone.
        return 3;
    }

    return 0;
}

// Helper: configure controller/target divisor and frame format (including parity).
typedef struct {
    uint8_t wls;
    uint8_t stb;
    uint8_t pen;
    uint8_t eps;
    uint8_t stick_parity;
} uart_frame_cfg_t;

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

    // Basic MCR configuration (RTS = 1).
    mcr.f.RTS = 0x1u;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              mcr.w);

    // Program the divisor.
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

    // Frame format (including parity).
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

// Case 2: Parity Error (controller / target parity mismatch)
static int uart_test_parity_error(uint32_t ctrl_idx, uint32_t tgt_idx) {
    const uint32_t ctrl_base = get_uart_reg_base(ctrl_idx);
    const uint32_t tgt_base = get_uart_reg_base(tgt_idx);
    const uint32_t divisor = 1u; // Any valid divisor value works.

    uart_16550_main__LSR_t lsr;
    uart_16550_main__IIR_t iir;

    simputs("\n[UART_ERROR] Case 1: Parity Error start\n");
    simputshex32("  ctrl_idx  = ", ctrl_idx);
    simputshex32("  ctrl_base = ", ctrl_base);
    simputshex32("  tgt_idx   = ", tgt_idx);
    simputshex32("  tgt_base  = ", tgt_base);

    // Parity mismatch:
    //   controller: 8O1 (odd parity)
    //   target    : 8E1 (even parity)
    const uart_frame_cfg_t cfg_ctrl = {
        .wls = 3u, .stb = 0u, .pen = 1u, .eps = 0u, .stick_parity = 0u};
    const uart_frame_cfg_t cfg_tgt = {
        .wls = 3u, .stb = 0u, .pen = 1u, .eps = 1u, .stick_parity = 0u};

    uart_program_divisor_and_format(ctrl_base, divisor, &cfg_ctrl);
    uart_program_divisor_and_format(tgt_base, divisor, &cfg_tgt);

    uart_clear_status(ctrl_base);
    uart_clear_status(tgt_base);

    static const uint8_t test_pattern[] = {0x00u, 0xFFu, 0x55u, 0xAAu};

    int saw_pe = 0;
    int saw_line_status_intr = 0;

    for (uint32_t i = 0; i < sizeof(test_pattern); i++) {
        uint8_t tx = test_pattern[i];

        simputshex32("  [Case1] TX byte index=", i);
        simputshex32("    TX data = 0x", tx);

        // Controller sends one byte.
        write_reg(ctrl_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                               SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
                  tx);

        // Wait some time for the receiver to sample and then observe parity error / line status.
        int local_saw_pe = 0;
        int local_saw_line_status_intr = 0;

        for (int iter = 0; iter < 512; iter++) {
            // First, check whether LSR has already flagged a parity error.
            lsr.w = read_reg(tgt_base +
                             (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                              SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
            if (lsr.f.PE) {
                local_saw_pe = 1;
                simputshex32("    LSR.PE set at iter=", (uint32_t)iter);
                simputshex32("      LSR = 0x", lsr.w);
            }

            // Then check whether IIR shows a line status interrupt (higher priority than RDR).
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
            return 10; // Parity mismatch occurred but LSR.PE was never seen.
        }
        if (!local_saw_line_status_intr) {
            // There will be another global check later, but mark an early error code here.
            simputs("  [ERROR] Case1: Parity error occurred but no Line Status interrupt seen\n");
            return 11; // Parity error occurred but the corresponding line status interrupt was not
                       // seen.
        }

        saw_pe = 1;
        saw_line_status_intr = 1;

        // Read out data to clear RX.
        (void)read_reg(tgt_base +
                       (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                        SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    }

    if (!saw_pe) {
        simputs("  [ERROR] Case1: Global check - never saw any parity error across pattern\n");
        return 12;
    }
    if (!saw_line_status_intr) {
        simputs("  [ERROR] Case1: Global check - never saw any Line Status interrupt\n");
        return 13; // Parity error occurred but no line status interrupt was seen.
    }

    // Set controller/target parity to be consistent again (for example, both 8E1) and confirm that
    // PE no longer occurs.
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
            return 15; // A normal frame should not set any error flags.
        }
        (void)read_reg(tgt_base +
                       (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                        SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    }

    return 0;
}

// Case 3: Break condition (via set_break + loopback). Framing error is NOT
// injected here: SET_BREAK produces a break, not a missing stop bit.
static int uart_test_break_and_framing(uint32_t uart_idx) {
    const uint32_t uart_base = get_uart_reg_base(uart_idx);
    uart_16550_main__LCR_t lcr;
    uart_16550_main__LSR_t lsr;
    uart_16550_main__IIR_t iir;

    simputs("\n[UART_ERROR] Case 3: Break start\n");
    simputshex32("  uart_idx   = ", uart_idx);
    simputshex32("  uart_base  = ", uart_base);

    uart_init_8n1_loopback(uart_base);
    uart_clear_status(uart_base);

    // Confirm that FE/BI are 0 at the start.
    lsr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    if (lsr.f.FE || lsr.f.BI) {
        simputshex32("  [ERROR] Case3: Initial LSR has FE/BI set, LSR=0x", lsr.w);
        return 20; // There should be no framing/break error at the initial state.
    }

    // Enable set_break: TX continuously sends break, which is looped back to RX.
    lcr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    lcr.f.SET_BREAK = 1u;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              lcr.w);
    simputs("  Case3: SET_BREAK asserted (TX driving continuous low in loopback)\n");

    // Poll LSR, expecting BI to be set; most implementations also set FE.
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
        return 21; // Break interrupt was not detected.
    }

    // Check whether a line status interrupt was generated.
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
        return 22; // A break event should generate a line status interrupt.
    }

    // Deassert break and read LSR to clear error status.
    lcr.f.SET_BREAK = 0u;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              lcr.w);
    simputs("  Case3: SET_BREAK deasserted\n");

    // Read LSR/RBR/IIR a few times, expecting FE/BI to be cleared eventually.
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
        // Same caveat as the OE check above: FE and BI are rclr
        // (uart_16550_main.rdl:235-252), so the 32 LSR reads in the loop are
        // what cleared them and this read cannot find them set on account of
        // the break being deasserted. It establishes only that they stay clear
        // instead of re-asserting with no break present.
        return 23;
    }

    // saw_fe is observed opportunistically and deliberately not required: some
    // implementations only raise BI for a break. Note this case therefore does
    // NOT cover framing error -- SET_BREAK produces a break condition, not a
    // missing stop bit, so nothing here injects a real framing error. The
    // case name and banners say "Break" only, for that reason.
    (void)saw_fe;
    return 0;
}

int main(void) {
    // The parity error is detected on the receiver, so UART0 (replica[0]) is the
    // target and UART3 transmits with mismatched parity. Overrun and break use
    // the UART0 single-ended loopback.
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

    // First enable the relevant UARTs.
    uart_enable_pair(uart_ctrl_idx, uart_tgt_idx);
    uart_enable_single(uart_overrun_idx);
    uart_enable_single(uart_break_idx);

    // Case 1: Parity Error (PEN=1, controller / target parity mismatch)
    int rc = uart_test_parity_error(uart_ctrl_idx, uart_tgt_idx);
    if (rc != 0) {
        simputs("ERROR: UART Error Conditions - Case 1 (Parity Error) FAILED\n");
        simputshex32("  rc = ", (uint32_t)rc);
        write_scratch(0, 0xBAD00010u | ((uint32_t)rc & 0xFFu));
        test_fail(0);
    }
    simputs("INFO: UART Error Conditions - Case 1 (Parity Error) PASSED\n");

    // Case 2: RX Overrun
    rc = uart_test_overrun(uart_overrun_idx);
    if (rc != 0) {
        simputs("ERROR: UART Error Conditions - Case 2 (RX Overrun) FAILED\n");
        simputshex32("  rc = ", (uint32_t)rc);
        write_scratch(0, 0xBAD00020u | ((uint32_t)rc & 0xFFu));
        test_fail(0);
    }
    simputs("INFO: UART Error Conditions - Case 2 (RX Overrun) PASSED\n");

    // Case 3: Break Condition (framing error is NOT injected -- see case3 notes)
    rc = uart_test_break_and_framing(uart_break_idx);
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

    return 0;
}
