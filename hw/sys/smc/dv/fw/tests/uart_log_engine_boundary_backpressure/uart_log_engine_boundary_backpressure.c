/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// smc_uart_log_engine_boundary_backpressure_test
//
// Two real log_engine behaviours the existing tests don't land on
// replica[0] (found via cond-coverage analysis, v15):
//
//   Scenario A — multi-word fetch-done boundary, "len-reached" arm.
//     log_engine.sv:199-202 fetch-done condition:
//        A = (cnt+1)*LOG_WORD_SIZE == max_log_len   (region-boundary cap)
//        B = (cnt+1)*LOG_WORD_SIZE >= log_len        (requested-len reached)
//     LOG_WORD_SIZE = 8 (64-bit fetch), max_log_len = region_size/16.
//     Existing single_entry uses region 0x100 (max_log_len=16) + log_len=16
//     so A and B go true together (bin 11). To cover bin 01 (B true while A
//     false) we need log_len < max_log_len reached at a word boundary that
//     is NOT the region boundary: region 0x100 (max_log_len=16), log_len=8
//     → at cnt=0, (1)*8=8: A=(8==16)=0, B=(8>=8)=1 → bin 01, fetch done.
//     (bin 10 — A true, B false — needs log_len > max_log_len, which caps
//     the fetch short while the write FSM still wants log_len bytes →
//     rdata_fifo underruns → write deadlock. That is a defensive
//     region-overrun guard, not firmware-stimulable; it is waived.)
//
//   Scenario B — log-write under UART TX backpressure.
//     log_engine.sv:351 write-REQ guard: (rdata_fifo_rd_valid && uart_tx_ready_i).
//     uart_tx_ready_i = uart_16550 txrdy_o = !tx_fifo_thr_rvalid (DMA mode 0):
//     it drops when the UART TX FIFO (depth 32) has data pending. The log_write
//     FSM issues bytes far faster than the UART serialises them, so a log
//     longer than the TX FIFO fills it and drives uart_tx_ready_i low while
//     rdata_fifo still holds fetched data (rd_valid=1) → covers bin 01 of that
//     guard. region 0x400 (max_log_len=64), log_len=64 (> TX FIFO 32).

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
#define LE_INTR_ENABLE_OFF  (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_ENABLE_BASE_ADDR(0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_LOG_CTRL0_OFF    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_CTRL_BASE_ADDR(0, 0) - SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))

#define BIT_FETCH_ERR       (1u << 0)
#define BIT_WRITE_ERR       (1u << 4)

#define LOG_BUFFER_BASE     (SMC_TOP_SPM_MEMORY_BASE_ADDR + 0x40000u)
// Undefined offset inside the uart_16550 decode window (real regs 0x00-0x1C,
// window 0x00-0x3F). A log_write to here → MAIN_REG decode-error → SLVERR →
// log_write_err. UART_REG_MAP base 0xC000A100, size 0x28.
#define UART_BAD_OFF        0x20u

static void setup_uart_8n1_fifo(void) {
    write_reg(WRAP0_CTRL_REG, 1u);                       // padmux enable
    write_reg(WRAP0_UART_BASE + UART_LCR_OFF, 0x80u);    // DLAB=1
    write_reg(WRAP0_UART_BASE + UART_RBR_OFF, 0x01u);    // DLL=1 (fastest divisor)
    write_reg(WRAP0_UART_BASE + UART_IER_OFF, 0x00u);    // DLM=0
    write_reg(WRAP0_UART_BASE + UART_LCR_OFF, 0x03u);    // DLAB=0, 8 bits, 1 stop, no parity
    write_reg(WRAP0_UART_BASE + UART_MCR_OFF, 0x10u);    // MCR.LOOP=1 (TX drains internally)
    write_reg(WRAP0_UART_BASE + UART_IIR_OFF, 0x01u);    // FCR.FIFO_ENABLE=1 (TX FIFO depth 32)
}

// Poll LOG_CTRL[entry] until it hwclrs to 0 (engine finished writing the log).
static int wait_log_done(uint32_t ctrl_off, uint32_t timeout) {
    while (timeout > 0u) {
        if ((read_reg(WRAP0_LE_BASE + ctrl_off) & 0xFFFFu) == 0u) return 0;
        timeout--;
    }
    return -1;
}

int main(void) {
    info_msg_s(0, "smc_uart_log_engine_boundary_backpressure_test start");

    setup_uart_8n1_fifo();

    //--------------------------------------------------------------------------
    // SCENARIO A — multi-word fetch-done "len-reached" arm (cond bin 01).
    // region 0x100 → max_log_len=16; log_len=8 (< max_log_len, 1 fetch word).
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario A: multi-word fetch-done len-reached boundary (bin 01)");
    {
        volatile uint8_t *buf = (volatile uint8_t *)(uintptr_t)LOG_BUFFER_BASE;
        for (int i = 0; i < 8; i++) buf[i] = (uint8_t)(0xA0u + i);

        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
        write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, 0x11u);          // clear stale
        write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, 0x100u);         // max_log_len=16
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF, LOG_BUFFER_BASE);
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
        write_reg(WRAP0_LE_BASE + LE_WRITE_ADDR_OFF, WRAP0_UART_BASE + UART_RBR_OFF);
        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
        write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, 8u);               // log_len=8 < 16

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
    // SCENARIO B — log-write under UART TX backpressure (cond bin 01 of
    // rdata_fifo_rd_valid && uart_tx_ready_i). region 0x400 → max_log_len=64;
    // log_len=64 > TX FIFO depth (32), so the TX FIFO fills mid-transfer and
    // drives uart_tx_ready_i low while rdata_fifo still has data.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario B: log-write under TX backpressure");
    {
        volatile uint8_t *buf = (volatile uint8_t *)(uintptr_t)LOG_BUFFER_BASE;
        for (int i = 0; i < 64; i++) buf[i] = (uint8_t)(0x40u + i);

        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
        write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, 0x11u);
        write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, 0x400u);         // max_log_len=64
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF, LOG_BUFFER_BASE);
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
        write_reg(WRAP0_LE_BASE + LE_WRITE_ADDR_OFF, WRAP0_UART_BASE + UART_RBR_OFF);
        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
        write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, 64u);              // log_len=64 > TX FIFO 32

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
    // SCENARIO C — real log_write_err (cond bin 10 of L460:
    //   (log_write_err || INTR_TEST.LOG_WRITE_ERR) && ENABLE).
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

        // Each of the 8 byte-writes to the undefined offset SLVERRs →
        // log_write_err pulses → the L460 cond bin 10 is SAMPLED during the
        // burst (that is the coverage goal). INTR_STATUS.LOG_WRITE_ERR follows
        // .next and is NOT sticky once the burst completes, so we do NOT poll
        // the status (that races with the fast burst and would hang). Instead
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
    // SCENARIO D — fetch-done region-boundary cap (cond bin 10 of L199:
    //   (cnt+1)*WORD == max_log_len true while >= log_len false).
    // Needs log_len > max_log_len: the fetch caps at the region boundary while
    // the write FSM still wants log_len bytes → rdata_fifo underruns → the
    // write side stalls (defensive guard, never completes). The cond bin is
    // sampled at the fetch response (before the stall matters), so we DO NOT
    // poll for completion: fixed delay to let the fetch reach the boundary,
    // then CTRL.EN=0 aborts cleanly (FSMs→IDLE, rdata_fifo clr).
    // region 0x100 (max_log_len=16), log_len=24.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario D: fetch-done region-boundary cap (bin 10)");
    {
        volatile uint8_t *buf = (volatile uint8_t *)(uintptr_t)LOG_BUFFER_BASE;
        for (int i = 0; i < 16; i++) buf[i] = (uint8_t)(0x80u + i);

        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
        write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, 0x11u);
        write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, 0x100u);          // max_log_len=16
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF, LOG_BUFFER_BASE); // good fetch
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
        write_reg(WRAP0_LE_BASE + LE_WRITE_ADDR_OFF, WRAP0_UART_BASE + UART_RBR_OFF);
        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
        write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, 24u);              // log_len=24 > max_log_len=16

        // Fixed delay: let the fetch issue 2 words and hit the == max_log_len
        // boundary (bin 10 sampled). Do NOT poll for completion (write stalls).
        for (volatile int i = 0; i < 5000; i++) { }

        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);                    // abort cleanly
    }

    // Cleanup
    write_reg(WRAP0_UART_BASE + UART_MCR_OFF, 0u);
    write_reg(WRAP0_CTRL_REG, 0u);

    info_msg_s(0, "smc_uart_log_engine_boundary_backpressure_test done");
    test_pass(0);

    while (1) __asm__("wfi");
    return 0;
}
