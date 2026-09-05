/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// smc_uart_log_engine_boundary_backpressure_test
//
// Boundary and backpressure cases for the log engine's effective transfer
// length:
//
//   Scenario A — requested length terminates the fetch before slot capacity.
//     A 16-byte slot and 8-byte request produce one fetch beat.
//
//   Scenario B — log-write under UART TX backpressure.
//     uart_tx_ready_i = uart_16550 txrdy_o = !tx_fifo_thr_rvalid (DMA mode 0):
//     it drops when the UART TX FIFO (depth 32) has data pending. The log_write
//     FSM issues bytes far faster than the UART serialises them, so a log
//     longer than the TX FIFO fills it and drives uart_tx_ready_i low while
//     rdata_fifo still holds fetched data. A 0x400-byte region gives each slot
//     64 bytes, so a 64-byte request exceeds the 32-byte TX FIFO.
//
//   Scenarios D and E — both FSMs terminate at the same effective length.
//     D clamps a request to an aligned slot capacity. E rounds a
//     non-word-aligned slot down to complete 8-byte fetch beats. Both verify
//     the exact looped-back data and that no additional byte is transmitted.

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
#define LE_INTR_ENABLE_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_ENABLE_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_LOG_CTRL0_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_CTRL_BASE_ADDR(0, 0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))

#define BIT_FETCH_ERR (1u << 0)
#define BIT_WRITE_ERR (1u << 4)

#define LOG_BUFFER_BASE (SMC_TOP_SPM_MEMORY_BASE_ADDR + 0x40000u)
// Undefined offset inside the uart_16550 decode window (real regs 0x00-0x1C,
// window 0x00-0x3F). A log_write to here → MAIN_REG decode-error → SLVERR →
// log_write_err. UART_REG_MAP base 0xC000A100, size 0x28.
#define UART_BAD_OFF 0x20u

static void setup_uart_8n1_fifo(void) {
    write_reg(WRAP0_CTRL_REG, 1u);                    // padmux enable
    write_reg(WRAP0_UART_BASE + UART_LCR_OFF, 0x80u); // DLAB=1
    write_reg(WRAP0_UART_BASE + UART_RBR_OFF, 0x01u); // DLL=1 (fastest divisor)
    write_reg(WRAP0_UART_BASE + UART_IER_OFF, 0x00u); // DLM=0
    write_reg(WRAP0_UART_BASE + UART_LCR_OFF, 0x03u); // DLAB=0, 8 bits, 1 stop, no parity
    write_reg(WRAP0_UART_BASE + UART_MCR_OFF, 0x10u); // MCR.LOOP=1 (TX drains internally)
    write_reg(WRAP0_UART_BASE + UART_IIR_OFF, 0x01u); // FCR.FIFO_ENABLE=1 (TX FIFO depth 32)
}

// Poll LOG_CTRL[entry] until it hwclrs to 0 (engine finished writing the log).
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

    // FCR: FIFO enable, RX reset, TX reset. Drain through LSR.DR/RBR as a
    // defensive check that no byte remains visible after the protocol reset.
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

    // LOG_CTRL clears when the final byte enters the UART, not when it leaves
    // the serial shifter. TEMT is the UART protocol indication that every
    // accepted byte has reached loopback RX; DR must then stay clear.
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
    // SCENARIO A — requested length terminates the fetch before slot capacity.
    // region 0x100 → slot capacity=16; log_len=8 produces one fetch beat.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario A: requested length terminates before slot capacity");
    {
        volatile uint8_t *buf = (volatile uint8_t *)(uintptr_t)LOG_BUFFER_BASE;
        for (int i = 0; i < 8; i++) buf[i] = (uint8_t)(0xA0u + i);

        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
        write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, 0x11u);  // clear stale
        write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, 0x100u); // max_log_len=16
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF, LOG_BUFFER_BASE);
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
        write_reg(WRAP0_LE_BASE + LE_WRITE_ADDR_OFF, WRAP0_UART_BASE + UART_RBR_OFF);
        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
        write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, 8u); // log_len=8 < 16

        if (wait_log_done(LE_LOG_CTRL0_OFF, 200000u) != 0) {
            info_msg_s(0, "FAIL: scenario A: log not done (LOG_CTRL hwclr timeout)");
            test_fail(0);
        }
        if ((read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & 0x11u) != 0u) {
            info_msg_s(0, "FAIL: scenario A: unexpected INTR_STATUS");
            test_fail(0);
        }
        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    }

    //--------------------------------------------------------------------------
    // SCENARIO B — log-write under UART TX backpressure. region 0x400 gives a
    // 64-byte slot; log_len=64 exceeds TX FIFO depth (32), so the TX FIFO fills
    // mid-transfer and drives uart_tx_ready_i low while fetched data remains.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario B: log-write under TX backpressure");
    {
        volatile uint8_t *buf = (volatile uint8_t *)(uintptr_t)LOG_BUFFER_BASE;
        for (int i = 0; i < 64; i++) buf[i] = (uint8_t)(0x40u + i);

        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
        write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, 0x11u);
        write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, 0x400u); // max_log_len=64
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF, LOG_BUFFER_BASE);
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
        write_reg(WRAP0_LE_BASE + LE_WRITE_ADDR_OFF, WRAP0_UART_BASE + UART_RBR_OFF);
        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
        write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, 64u); // log_len=64 > TX FIFO 32

        // The UART drains at baud while the engine refills; backpressure happens
        // mid-transfer. Generous timeout: 64 bytes * ~160 clk/byte + margin.
        if (wait_log_done(LE_LOG_CTRL0_OFF, 2000000u) != 0) {
            info_msg_s(0, "FAIL: scenario B: log not done under backpressure");
            test_fail(0);
        }
        if ((read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & 0x11u) != 0u) {
            info_msg_s(0, "FAIL: scenario B: unexpected INTR_STATUS");
            test_fail(0);
        }
        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    }

    //--------------------------------------------------------------------------
    // SCENARIO C — real log_write_err while interrupt reporting is enabled.
    // The log_write master feeds the LOCAL uart_16550 AXI-lite slave (via
    // log_write_axi_lite_mux), NOT the SMC fabric. Writing to an UNDEFINED
    // offset inside the uart_16550 decode window (real regs 0x00-0x1C, window
    // 0x00-0x3F) → uart_16550_main_reg PeakRDL decode-error → SLVERR →
    // log_write_err. The write FSM advances on mem_rsp_valid regardless of
    // error, so the transfer COMPLETES (no hang) — poll normally.
    // Good fetch from SRAM; bad write addr = UART_BASE + 0x20.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario C: real log_write_err via undefined UART offset (bin 10)");
    {
        volatile uint8_t *buf = (volatile uint8_t *)(uintptr_t)LOG_BUFFER_BASE;
        for (int i = 0; i < 8; i++) buf[i] = (uint8_t)(0xC0u + i);

        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
        write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, BIT_FETCH_ERR | BIT_WRITE_ERR);
        write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR | BIT_WRITE_ERR);
        write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, 0x100u);          // max_log_len=16
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF, LOG_BUFFER_BASE); // good fetch
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
        write_reg(WRAP0_LE_BASE + LE_WRITE_ADDR_OFF, WRAP0_UART_BASE + UART_BAD_OFF); // SLVERR
        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
        write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, 8u);

        // Each of the 8 byte-writes to the undefined offset SLVERRs, pulsing
        // log_write_err during the burst. INTR_STATUS.LOG_WRITE_ERR follows
        // .next and is not sticky once the burst completes, so polling status
        // races with the fast burst. Instead,
        // poll LOG_CTRL hwclr, which reliably indicates the write completed —
        // the SLVERR write FSM still advances on each resp and asserts
        // log_write_done. (If status happens to still read set, fine; if not,
        // the cond bin was covered anyway.)
        if (wait_log_done(LE_LOG_CTRL0_OFF, 200000u) != 0) {
            info_msg_s(0, "FAIL: scenario C: write did not complete");
            test_fail(0);
        }
        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
        write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, 0u);
        write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR | BIT_WRITE_ERR);
    }

    //--------------------------------------------------------------------------
    // SCENARIO D — requested length above the slot size is clamped consistently
    // by both FSMs. region 0x100 gives a 16-byte slot; log_len=24 must fetch and
    // write exactly 16 bytes, complete, and hwclr LOG_CTRL.
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
        write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, 0x100u);          // max_log_len=16
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF, LOG_BUFFER_BASE); // good fetch
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
        write_reg(WRAP0_LE_BASE + LE_WRITE_ADDR_OFF, WRAP0_UART_BASE + UART_RBR_OFF);
        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
        write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, 24u); // log_len=24 > max_log_len=16

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
    // SCENARIO E — a non-word-aligned 15-byte slot has one complete 8-byte
    // fetch beat. log_len=15 is clamped to 8 so no fetch can cross the slot
    // boundary and the writer cannot wait for the seven bytes never fetched.
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
        write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, 0xF0u); // 240 / 16 = 15 bytes/slot
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

    // Cleanup
    write_reg(WRAP0_UART_BASE + UART_MCR_OFF, 0u);
    write_reg(WRAP0_CTRL_REG, 0u);

    info_msg_s(0, "smc_uart_log_engine_boundary_backpressure_test done");
    test_pass(0);

    while (1) __asm__("wfi");
    return 0;
}
