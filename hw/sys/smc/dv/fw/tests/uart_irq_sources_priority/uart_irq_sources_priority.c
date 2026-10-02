/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"

// UART interrupt identifiers, highest priority first.
#define UART_INTR_ID_FIFO_ERROR (0x7u)
#define UART_INTR_ID_RECEIVER_LINE_STATUS (0x3u)
#define UART_INTR_ID_RECEPTION_TIMEOUT (0x6u)
#define UART_INTR_ID_RECEIVED_DATA_READY (0x2u)
#define UART_INTR_ID_TRANSMITTER_HOLDING_REGISTER_EMPTY (0x1u)
#define UART_INTR_ID_MODEM_STATUS (0x0u)

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

// Disable and stop forcing every source, then clear status left by a previous subtest.
static void uart_clear_all_status(uint32_t uart_base) {
    uart_16550_main__IER_t ier;
    uart_16550_main__ITR_t itr;
    uart_16550_main__IIR_t iir;

    ier.w = 0;
    itr.w = 0;

    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              ier.w);
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);

    // Reading the line and modem status clears them.
    (void)read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                                SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    (void)read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MSR_BASE_ADDR(0) -
                                SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));

    // Read the identification register until no interrupt is pending, with a bounded loop.
    for (int i = 0; i < 8; i++) {
        iir.w =
            read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        if (iir.f.INTERRUPT_PENDING != 0u) {
            break;
        }
    }
}

// Poll until an interrupt is pending; return the last identification read, pending or not.
static uart_16550_main__IIR_t uart_poll_iir(uint32_t uart_base, int max_iters) {
    uart_16550_main__IIR_t iir;

    for (int i = 0; i < max_iters; i++) {
        iir.w =
            read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        if (iir.f.INTERRUPT_PENDING == 0u) {
            return iir;
        }
    }

    return iir;
}

// Subtest A: each forced source is masked by its enable and reports its own identifier.
static int uart_test_ier_gating_and_mapping(uint32_t uart_base) {
    uart_16550_main__IER_t ier;
    uart_16550_main__ITR_t itr;
    uart_16550_main__IIR_t iir;
    uart_clear_all_status(uart_base);

    // Modem Status
    // 1. Gating: with the source disabled, its identifier is not reported.
    ier.w = 0;
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              ier.w);
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);
    itr.f.TDSSI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);
    iir = uart_poll_iir(uart_base, 8);
    if ((iir.f.INTERRUPT_PENDING == 0u) && (iir.f.INTERRUPT_ID == UART_INTR_ID_MODEM_STATUS)) {
        return -10;
    }
    // 2. Mapping: with the source enabled, its identifier is reported.
    itr.w = 0;
    ier.w = 0;
    ier.f.EDSSI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              ier.w);
    itr.f.TDSSI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if (iir.f.INTERRUPT_PENDING != 0u) {
        return -(10 + 1);
    }
    if (iir.f.INTERRUPT_ID != UART_INTR_ID_MODEM_STATUS) {
        return -(10 + 2);
    }
    // 3. Stop forcing the source so it does not affect the next source.
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);

    // THR Empty
    ier.w = 0;
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              ier.w);
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);
    itr.f.TTBEI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);
    iir = uart_poll_iir(uart_base, 8);
    if ((iir.f.INTERRUPT_PENDING == 0u) &&
        (iir.f.INTERRUPT_ID == UART_INTR_ID_TRANSMITTER_HOLDING_REGISTER_EMPTY)) {
        return -20;
    }
    itr.w = 0;
    ier.w = 0;
    ier.f.ETBEI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              ier.w);
    itr.f.TTBEI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if (iir.f.INTERRUPT_PENDING != 0u) {
        return -(20 + 1);
    }
    if (iir.f.INTERRUPT_ID != UART_INTR_ID_TRANSMITTER_HOLDING_REGISTER_EMPTY) {
        return -(20 + 2);
    }
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);

    // RX Data Ready
    ier.w = 0;
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              ier.w);
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);
    itr.f.TRBFI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);
    iir = uart_poll_iir(uart_base, 8);
    if ((iir.f.INTERRUPT_PENDING == 0u) &&
        (iir.f.INTERRUPT_ID == UART_INTR_ID_RECEIVED_DATA_READY)) {
        return -30;
    }
    itr.w = 0;
    ier.w = 0;
    ier.f.ERBFI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              ier.w);
    itr.f.TRBFI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if (iir.f.INTERRUPT_PENDING != 0u) {
        return -(30 + 1);
    }
    if (iir.f.INTERRUPT_ID != UART_INTR_ID_RECEIVED_DATA_READY) {
        return -(30 + 2);
    }
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);

    // RX Timeout: only the identifier is checked, because this source is not masked by an enable.
    itr.w = 0;
    ier.w = 0;
    ier.f.ERBFI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              ier.w);
    itr.f.TRTI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if (iir.f.INTERRUPT_PENDING != 0u) {
        simputs("  [A][RX Timeout][mapping] no pending interrupt seen\n");
        simputshex32("    IER = 0x", ier.w);
        simputshex32("    ITR = 0x", itr.w);
        simputshex32("    IIR = 0x", iir.w);
        simputs("\n");
        return -(40 + 1);
    }
    if (iir.f.INTERRUPT_ID != UART_INTR_ID_RECEPTION_TIMEOUT) {
        simputs("  [A][RX Timeout][mapping] interrupt ID mismatched\n");
        simputshex32("    IER = 0x", ier.w);
        simputshex32("    ITR = 0x", itr.w);
        simputshex32("    IIR = 0x", iir.w);
        simputshex32("    expected ID = 0x", UART_INTR_ID_RECEPTION_TIMEOUT);
        simputshex32("    got ID      = 0x", iir.f.INTERRUPT_ID);
        simputs("\n");
        return -(40 + 2);
    }
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);

    // Line Status
    ier.w = 0;
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              ier.w);
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);
    itr.f.TLSI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);
    iir = uart_poll_iir(uart_base, 8);
    if ((iir.f.INTERRUPT_PENDING == 0u) &&
        (iir.f.INTERRUPT_ID == UART_INTR_ID_RECEIVER_LINE_STATUS)) {
        return -50;
    }
    itr.w = 0;
    ier.w = 0;
    ier.f.ELSI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              ier.w);
    itr.f.TLSI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if (iir.f.INTERRUPT_PENDING != 0u) {
        return -(50 + 1);
    }
    if (iir.f.INTERRUPT_ID != UART_INTR_ID_RECEIVER_LINE_STATUS) {
        return -(50 + 2);
    }
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);

    // FIFO Error
    ier.w = 0;
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              ier.w);
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);
    itr.f.TFEI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);
    iir = uart_poll_iir(uart_base, 8);
    if ((iir.f.INTERRUPT_PENDING == 0u) && (iir.f.INTERRUPT_ID == UART_INTR_ID_FIFO_ERROR)) {
        return -60;
    }
    itr.w = 0;
    ier.w = 0;
    ier.f.EFEI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              ier.w);
    itr.f.TFEI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if (iir.f.INTERRUPT_PENDING != 0u) {
        return -(60 + 1);
    }
    if (iir.f.INTERRUPT_ID != UART_INTR_ID_FIFO_ERROR) {
        return -(60 + 2);
    }
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);

    return 0;
}

// Fail if the given identifier is still reported as pending.
static int uart_fail_if_id_still_pending(uint32_t uart_base, uint32_t expect_id, int err) {
    uart_16550_main__IIR_t iir;
    iir.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    if ((iir.f.INTERRUPT_PENDING == 0u) && (iir.f.INTERRUPT_ID == expect_id)) {
        return err;
    }
    return 0;
}

// Configure 8N1 internal loopback with FIFOs enabled and no forced sources.
static void uart_init_loopback_for_clear(uint32_t uart_base) {
    uart_16550_main__LCR_t lcr;
    uart_16550_main__MCR_t mcr;
    uart_16550_main__ITR_t itr;

    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);

    lcr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    lcr.f.DLAB = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              lcr.w);
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              0x01u);
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              0x00u);
    lcr.f.DLAB = 0;
    lcr.f.WLS = 0x3u;
    lcr.f.STB = 0;
    lcr.f.PEN = 0;
    lcr.f.SET_BREAK = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              lcr.w);

    mcr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    mcr.f.LOOP = 1;
    mcr.f.RTS = 1;
    mcr.f.DTR = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              mcr.w);

    // Enable the FIFOs; the FIFO control register shares the identification register's address.
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              0x01u);
}

// Subtest B: each source clears through its architectural service action. A forced source would
// stay pending regardless of the clear, so the sources are produced naturally through loopback.
// The clear of line status, timeout and FIFO error is not checked; subtests A and C cover their
// identifiers.
static int uart_test_clear_behaviour(uint32_t uart_base) {
    uart_16550_main__IER_t ier;
    uart_16550_main__ITR_t itr;
    uart_16550_main__IIR_t iir;
    uart_16550_main__LSR_t lsr;
    uart_16550_main__MCR_t mcr;
    int rc;
    int wait;

    uart_clear_all_status(uart_base);
    uart_init_loopback_for_clear(uart_base);

    // No source is forced during this subtest.
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);

    // Received data: a looped-back byte raises it; reading the byte clears it.
    ier.w = 0;
    ier.f.ERBFI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              ier.w);
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              0xA5u);
    iir = uart_poll_iir(uart_base, 4096);
    if ((iir.f.INTERRUPT_PENDING != 0u) ||
        (iir.f.INTERRUPT_ID != UART_INTR_ID_RECEIVED_DATA_READY)) {
        return -100;
    }
    (void)read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                                SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    rc = uart_fail_if_id_still_pending(uart_base, UART_INTR_ID_RECEIVED_DATA_READY, -101);
    if (rc != 0) {
        return rc;
    }

    // Drain any remaining received data before the transmitter-empty check.
    for (wait = 0; wait < 8; wait++) {
        lsr.w =
            read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
        if (lsr.f.DR == 0u) {
            break;
        }
        (void)read_reg(uart_base +
                       (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) -
                        SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    }

    // Transmitter empty: the idle transmitter raises it; the identification read that reports it
    // clears it. The source stays enabled for the post-clear check, which would otherwise pass
    // trivially.
    ier.w = 0;
    ier.f.ETBEI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              ier.w);
    iir = uart_poll_iir(uart_base, 4096);
    if ((iir.f.INTERRUPT_PENDING != 0u) ||
        (iir.f.INTERRUPT_ID != UART_INTR_ID_TRANSMITTER_HOLDING_REGISTER_EMPTY)) {
        return -120;
    }
    // The source is still enabled, so it must not remain pending after the clear.
    rc = uart_fail_if_id_still_pending(uart_base, UART_INTR_ID_TRANSMITTER_HOLDING_REGISTER_EMPTY,
                                       -121);
    if (rc != 0) {
        return rc;
    }
    // Disable transmitter empty so it cannot hide the lower-priority modem status.
    ier.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              ier.w);

    // Modem status: toggling the loopback modem outputs raises it; reading modem status clears it.
    ier.w = 0;
    ier.f.EDSSI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              ier.w);
    (void)read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MSR_BASE_ADDR(0) -
                                SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    mcr.w = read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                                  SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    mcr.f.RTS = (uint32_t)(mcr.f.RTS ? 0u : 1u);
    mcr.f.DTR = (uint32_t)(mcr.f.DTR ? 0u : 1u);
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              mcr.w);
    iir = uart_poll_iir(uart_base, 4096);
    if ((iir.f.INTERRUPT_PENDING != 0u) || (iir.f.INTERRUPT_ID != UART_INTR_ID_MODEM_STATUS)) {
        return -140;
    }
    (void)read_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MSR_BASE_ADDR(0) -
                                SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)));
    rc = uart_fail_if_id_still_pending(uart_base, UART_INTR_ID_MODEM_STATUS, -141);
    if (rc != 0) {
        return rc;
    }

    uart_clear_all_status(uart_base);
    return 0;
}

// Subtest C: verify priority when multiple interrupt sources are pending.
static int uart_test_priority(uint32_t uart_base) {
    uart_16550_main__IER_t ier;
    uart_16550_main__ITR_t itr;
    uart_16550_main__IIR_t iir;

    uart_clear_all_status(uart_base);

    // Line status outranks received data.
    ier.w = 0;
    itr.w = 0;
    ier.f.ELSI = 1;
    ier.f.ERBFI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              ier.w);
    itr.f.TLSI = 1;
    itr.f.TRBFI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if (iir.f.INTERRUPT_PENDING != 0u) {
        return -200;
    }
    if (iir.f.INTERRUPT_ID != UART_INTR_ID_RECEIVER_LINE_STATUS) {
        return -(200 + 1);
    }
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);
    uart_clear_all_status(uart_base);

    // Received data outranks transmitter empty.
    ier.w = 0;
    itr.w = 0;
    ier.f.ERBFI = 1;
    ier.f.ETBEI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              ier.w);
    itr.f.TRBFI = 1;
    itr.f.TTBEI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if (iir.f.INTERRUPT_PENDING != 0u) {
        return -210;
    }
    if (iir.f.INTERRUPT_ID != UART_INTR_ID_RECEIVED_DATA_READY) {
        return -(210 + 1);
    }
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);
    uart_clear_all_status(uart_base);

    // Transmitter empty outranks modem status.
    ier.w = 0;
    itr.w = 0;
    ier.f.ETBEI = 1;
    ier.f.EDSSI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              ier.w);
    itr.f.TTBEI = 1;
    itr.f.TDSSI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if (iir.f.INTERRUPT_PENDING != 0u) {
        return -220;
    }
    if (iir.f.INTERRUPT_ID != UART_INTR_ID_TRANSMITTER_HOLDING_REGISTER_EMPTY) {
        return -(220 + 1);
    }
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);
    uart_clear_all_status(uart_base);

    // Reception timeout outranks received data.
    ier.w = 0;
    itr.w = 0;
    ier.f.ERBFI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              ier.w);
    itr.f.TRBFI = 1;
    itr.f.TRTI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if (iir.f.INTERRUPT_PENDING != 0u) {
        return -230;
    }
    if (iir.f.INTERRUPT_ID != UART_INTR_ID_RECEPTION_TIMEOUT) {
        return -(230 + 1);
    }
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);
    uart_clear_all_status(uart_base);

    // FIFO error outranks line status.
    ier.w = 0;
    itr.w = 0;
    ier.f.ELSI = 1;
    ier.f.EFEI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              ier.w);
    itr.f.TLSI = 1;
    itr.f.TFEI = 1;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);
    iir = uart_poll_iir(uart_base, 16);
    if (iir.f.INTERRUPT_PENDING != 0u) {
        return -240;
    }
    if (iir.f.INTERRUPT_ID != UART_INTR_ID_FIFO_ERROR) {
        return -(240 + 1);
    }
    itr.w = 0;
    write_reg(uart_base + (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR(0) -
                           SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)),
              itr.w);
    uart_clear_all_status(uart_base);

    return 0;
}

int main(void) {
    uint32_t uart_idx = 0;
    uint32_t uart_base = get_uart_reg_base(uart_idx);
    int ret;

    uart_enable_single(uart_idx);

    simputs("\n");
    simputs("############################################\n");
    simputs("##   UART IRQ Sources & Priority Test    ##\n");
    simputs("############################################\n");
    simputs("\n");

    simputs("UART IRQ test: start\n");
    simputshex32("  uart_idx  = ", uart_idx);
    simputshex32("  uart_base = 0x", uart_base);
    simputs("\n");

    simputs("Subtest A: IER gating & single-source mapping ...\n");
    ret = uart_test_ier_gating_and_mapping(uart_base);
    if (ret != 0) {
        simputs("Subtest A FAILED\n");
        simputshex32("  error code = ", (uint32_t)ret);
        simputs("\n");
        write_scratch(0, 0xBAD0A000);
        test_fail(0);
    }
    simputs("Subtest A PASSED\n");

    simputs("Subtest B: clear behaviour for each source ...\n");
    ret = uart_test_clear_behaviour(uart_base);
    if (ret != 0) {
        simputs("Subtest B FAILED\n");
        simputshex32("  error code = ", (uint32_t)ret);
        simputs("\n");
        write_scratch(0, 0xBAD0B000);
        test_fail(0);
    }
    simputs("Subtest B PASSED\n");

    simputs("Subtest C: multi-source priority ...\n");
    ret = uart_test_priority(uart_base);
    if (ret != 0) {
        simputs("Subtest C FAILED\n");
        simputshex32("  error code = ", (uint32_t)ret);
        simputs("\n");
        write_scratch(0, 0xBAD0C000);
        test_fail(0);
    }
    simputs("Subtest C PASSED\n");

    simputs("\nUART IRQ test: ALL SUBTESTS PASSED\n");

    test_pass(0);
}
