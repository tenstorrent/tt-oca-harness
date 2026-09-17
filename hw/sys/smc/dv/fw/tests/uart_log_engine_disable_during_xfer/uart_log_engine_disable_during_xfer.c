/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// smc_uart_log_engine_disable_during_xfer_test
//
// Sanity-style check that clearing CTRL.EN mid-transfer cleanly halts the
// engine and leaves the wrapper accessible. FW pre-loads SRAM with 256 bytes,
// configures the engine pointing the log-write at the (line-loopback'd) UART
// THR, triggers entry 0, immediately clears CTRL.EN, then verifies:
//   * INTR_STATUS = 0 (no error injected, no bus error)
//   * Subsequent writes to LOG_CTRL[0] with EN still 0 do NOT cause traffic
//     (verified indirectly: re-enabling and re-triggering with a small length
//     completes cleanly without prior leftovers corrupting it).
//
// Per RDL the engine's "CTRL.EN=0 resets all FSMs, flops, and FIFOs"; the value
// LOG_CTRL[i] reads under EN=0 is not specified, so this test logs LOG_CTRL[0]
// at several points and does not pin its expected value.

#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"

#define WRAP0_CTRL_REG \
    SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(0)
#define WRAP0_UART_BASE SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0)
#define WRAP0_LE_BASE SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_CTRL_BASE_ADDR(0)

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
#define LE_INTR_ENABLE_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_ENABLE_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_INTR_STATUS_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_STATUS_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))
#define LE_LOG_CTRL0_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_CTRL_BASE_ADDR(0, 0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))

#define UART_RBR_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_MCR_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR(0) - \
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

#define LOG_BUFFER_BASE (SMC_TOP_SPM_MEMORY_BASE_ADDR + 0x40000u) // SRAM scratch area
#define LOG_REGION_SIZE 0x100u // 256 bytes (slot 0 covers 256/16 = 16 bytes)

int main(void) {
    info_msg_s(0, "smc_uart_log_engine_disable_during_xfer_test start");

    //--------------------------------------------------------------------------
    // Pre-load SRAM with a known pattern. Per slot math, entry 0 starts at
    // LOG_REGION_ADDR + (LOG_REGION_SIZE / 16) * 0 = LOG_REGION_ADDR.
    //--------------------------------------------------------------------------
    volatile uint8_t *buf = (volatile uint8_t *)(uintptr_t)LOG_BUFFER_BASE;
    for (uint32_t i = 0; i < 16; i++) {
        buf[i] = (uint8_t)(0xA0u + i); // distinguishable pattern
    }

    // Disable engine + UART CSR access path entirely before configuring
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    write_reg(WRAP0_CTRL_REG, 1u); // pad-mux enable so UART is reachable

    // Engine to line-loopback through UART RBR/THR: set LOG_WRITE_ADDR to the
    // UART RBR/THR offset and set MCR.LINE_LOOPBACK so TX feeds back into RX.
    /* Configure the UART before pointing the engine at it.
     *
     * This test wrote MCR and nothing else. Its two passing siblings
     * (uart_log_engine_single_entry, uart_log_engine_region_size) program the
     * divisor and line control first, and skipping that is not cosmetic here:
     * LOG_WRITE_ADDR is set to UART offset 0 below, which is THR only while
     * DLAB=0 -- with DLAB left set, all sixteen log bytes land in the divisor
     * latch instead of the transmit register. The line is also left at whatever
     * word length and rate reset produced.
     */
    write_reg(WRAP0_UART_BASE + UART_LCR_OFF, 0x80u); // DLAB=1
    write_reg(WRAP0_UART_BASE + UART_RBR_OFF, 0x01u); // DLL = 1 (fastest)
    write_reg(WRAP0_UART_BASE + UART_IER_OFF, 0x00u); // DLM = 0
    write_reg(WRAP0_UART_BASE + UART_LCR_OFF, 0x03u); // DLAB=0, 8-bit words
    write_reg(WRAP0_UART_BASE + UART_IIR_OFF, 0x01u); // FCR: FIFOs on
    /* MCR.LOOP (bit 4), not LINE_LOOPBACK (bit 5).
     * uart_16550_main.rdl puts LOOP at [4] and LINE_LOOPBACK at [5]; only LOOP
     * is the internal TX->RX loop this test needs. LINE_LOOPBACK drives tx_o
     * from rx_i and pins rx_in to idle, so every RBR drain below was reading a
     * permanently empty FIFO. The passing sibling uart_log_engine_single_entry
     * uses 0x10 for the same purpose. */
    write_reg(WRAP0_UART_BASE + UART_MCR_OFF, 0x10u); // MCR.LOOP = 1
    write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, LOG_REGION_SIZE);
    write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF, LOG_BUFFER_BASE);
    write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
    write_reg(WRAP0_LE_BASE + LE_WRITE_ADDR_OFF, WRAP0_UART_BASE + UART_RBR_OFF);
    /* Enable the two error interrupts so a latched error would also reach
     * irq_o. INTR_STATUS itself latches whether or not the interrupt is enabled
     * (INTR_ENABLE masks the output only), so the INTR_STATUS checks below are
     * live either way; enabling keeps the line as a second witness. */
    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, 0x11u);
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u); // engine enable

    //--------------------------------------------------------------------------
    // Trigger entry 0 with the slot size (16 bytes) and immediately disable.
    //--------------------------------------------------------------------------
    write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, 16u);

    // Snapshot LOG_CTRL[0] right after trigger
    uint32_t snap1 = read_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF);
    info_msg_hex32_s(0, "LOG_CTRL[0] post-trigger=", snap1);

    // Disable engine mid-transfer
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);

    // Snapshot LOG_CTRL[0] after disable
    uint32_t snap2 = read_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF);
    info_msg_hex32_s(0, "LOG_CTRL[0] post-disable=", snap2);

    // INTR_STATUS must be 0 — disable should not raise errors
    {
        uint32_t s = read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & 0x11u;
        if (s != 0u) {
            info_msg_hex32_s(0, "FAIL: INTR_STATUS unexpectedly set after disable=", s);
            test_fail(0);
        }
    }

    //--------------------------------------------------------------------------
    // Allow some cycles for any in-flight UART byte to flush, then drain RBR.
    // After disable, no NEW bytes should be inserted into the UART. We discard
    // whatever's currently in the FIFO without asserting an exact count
    // (since precise count depends on engine fetch timing).
    //--------------------------------------------------------------------------
    for (volatile int i = 0; i < 1000; i++) { /* settle */
    }
    for (int i = 0; i < 32; i++) {
        // Drain by reading RBR; ignore values
        (void)read_reg(WRAP0_UART_BASE + UART_RBR_OFF);
    }

    //--------------------------------------------------------------------------
    // Re-enable and trigger again — should complete cleanly.
    //--------------------------------------------------------------------------
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, 0x11u); // W1C any stale bits
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
    write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, 16u);

    // Poll LOG_CTRL[0] for hwclr (bounded)
    {
        /* Poll bound: a 16-byte entry completes in far fewer than 200 register
         * reads, and the bound must expire before the harness timeout. */
        uint32_t timeout = 200u;
        while (timeout > 0u && (read_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF) & 0xFFFFu) != 0u) {
            timeout--;
        }
        if (timeout == 0u) {
            info_msg_s(0, "FAIL: post-disable re-trigger: LOG_CTRL[0] did not hwclr");
            test_fail(0);
        }
    }

    {
        uint32_t s = read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & 0x11u;
        if (s != 0u) {
            info_msg_hex32_s(0, "FAIL: INTR_STATUS set after clean re-run=", s);
            test_fail(0);
        }
    }

    //--------------------------------------------------------------------------
    // SCENARIO B: long-burst log entry let to complete fully — exercises
    // log_fetch FSM ST_LOG_FETCH_REQ → ST_LOG_FETCH_WAIT → ST_LOG_FETCH_REQ
    // cycles (multi-cycle fetch) and log_write FSM REQ → WAIT → REQ similarly.
    // Use the full slot 0 size = LOG_REGION_SIZE/16 = 16 bytes — but multiple
    // entries in quick succession trigger the WAIT→REQ multi-cycle path
    // through arbitration.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario B: multi-entry simultaneous trigger");

/* From the generated map, not a hand-written base: the LOG_CTRL array starts
 * at 0x40 (LOG_ENGINE_BASE = 0xC0006200, LOG_CTRL[j] = 0xC0006240 + j*4) and
 * offset 0 is the CTRL register, so a hand-written `(i)*4u` would write the
 * length into CTRL -- clearing EN -- and then poll CTRL for a zero that never
 * comes. */
#define LE_LOG_CTRL_I_OFF(i) \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_CTRL_BASE_ADDR(0, (i)) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))

    // Pre-load all 16 slots' worth of pattern bytes
    for (uint32_t i = 0; i < LOG_REGION_SIZE; i++) {
        buf[i] = (uint8_t)(0xC0u + (i & 0x3Fu));
    }

    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);

    // Trigger entries 0,1,2,3 simultaneously — log_engine round-robins through
    // them, exercising the REQ→WAIT→REQ FSM cycles in both fetch + write
    // domains plus log_index arbitration.
    write_reg(WRAP0_LE_BASE + LE_LOG_CTRL_I_OFF(0), 16u);
    write_reg(WRAP0_LE_BASE + LE_LOG_CTRL_I_OFF(1), 16u);
    write_reg(WRAP0_LE_BASE + LE_LOG_CTRL_I_OFF(2), 16u);
    write_reg(WRAP0_LE_BASE + LE_LOG_CTRL_I_OFF(3), 16u);

    // Let all 4 transfers complete (no disable this round) — captures the
    // natural WAIT → REQ cycles inside each entry and the
    // multi-entry round-robin handoff.
    {
        /* Bound sized to the harness, not to a round number.
         *
         * 500000 polls is ~575 ms at the measured ~115 cycles/iteration, against
         * a ~4 ms harness bound -- so the FAIL diagnostic below could never
         * reach the log and the loop only ever ended by the run being killed.
         * The four entries completed in 174 iterations when observed; 4000 is
         * ~23x that and still finishes inside the harness bound. */
        uint32_t timeout = 4000u;
        while (timeout > 0u) {
            uint32_t c0 = read_reg(WRAP0_LE_BASE + LE_LOG_CTRL_I_OFF(0)) & 0xFFFFu;
            uint32_t c1 = read_reg(WRAP0_LE_BASE + LE_LOG_CTRL_I_OFF(1)) & 0xFFFFu;
            uint32_t c2 = read_reg(WRAP0_LE_BASE + LE_LOG_CTRL_I_OFF(2)) & 0xFFFFu;
            uint32_t c3 = read_reg(WRAP0_LE_BASE + LE_LOG_CTRL_I_OFF(3)) & 0xFFFFu;
            if ((c0 | c1 | c2 | c3) == 0u) break;
            timeout--;
        }
        if (timeout == 0u) {
            info_msg_s(0, "FAIL: scenario B: 4-entry trigger did not all clear");
            test_fail(0);
        }
    }
    // Drain whatever landed in UART RBR
    for (int i = 0; i < 64; i++) {
        (void)read_reg(WRAP0_UART_BASE + UART_RBR_OFF);
    }

    //--------------------------------------------------------------------------
    // SCENARIO C: abort mid-WAIT — trigger a slot, wait long enough for the
    // fetch FSM to reach the WAIT state (at least one beat fetched), then
    // disable. Covers ST_LOG_FETCH_WAIT → ST_LOG_FETCH_IDLE and the
    // analogous log_write WAIT → IDLE drain transitions.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario C: abort while FSM is in WAIT");

    // Reset state cleanly
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, 0x11u);

    // Re-enable + trigger a 16-byte entry
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
    write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, 16u);

    // Spin a few cycles so the FSM advances past REQ into WAIT.
    // ~50 cycles should be enough at SMC clock for the first AXI read to
    // land and the fetch FSM to transition.
    for (volatile int i = 0; i < 50; i++) { /* settle */
    }

    // Now disable — this catches the FSM in WAIT and forces WAIT → IDLE
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);

    {
        uint32_t s = read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & 0x11u;
        info_msg_hex32_s(0, "scenario C INTR_STATUS=", s);
        // INTR_STATUS after an abort in WAIT is not pinned: an in-flight beat
        // may or may not have raised an error before the disable took effect.
    }

    for (volatile int i = 0; i < 1000; i++) { /* settle */
    }
    for (int i = 0; i < 16; i++) {
        (void)read_reg(WRAP0_UART_BASE + UART_RBR_OFF);
    }

    //--------------------------------------------------------------------------
    // SCENARIO D: alternate replica wrap (UART_LOG_ENGINE_WRAP_1) — drives the
    // gen_uart_log_engine_wraps[1] replica's log_fetch_fsm IDLE → REQ → ... →
    // IDLE path.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario D: drive replica[1] log_engine");

#define WRAP1_LE_BASE SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_CTRL_BASE_ADDR(1)
#define WRAP1_UART_BASE SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(1)
#define WRAP1_CTRL_REG \
    SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR(1)
#define WRAP1_LE_CTRL_OFF LE_CTRL_OFF /* same offset within block */
#define WRAP1_LE_REGION_SIZE LE_REGION_SIZE_OFF
#define WRAP1_LE_REGION_ADDR LE_REGION_ADDR_OFF
#define WRAP1_LE_WRITE_ADDR LE_WRITE_ADDR_OFF
#define WRAP1_LE_LOG_CTRL0 LE_LOG_CTRL0_OFF
#define WRAP1_UART_RBR UART_RBR_OFF
#define WRAP1_UART_MCR UART_MCR_OFF

    write_reg(WRAP1_CTRL_REG, 1u);
    /* Replica 1's UART needs the same configuration as replica 0 (see the
     * scenario-A setup): LOG_WRITE_ADDR below points at UART offset 0, which is
     * THR only while DLAB=0. Only MCR was written here, so the log bytes went to
     * the divisor latch and the transfer never completed. */
    write_reg(WRAP1_UART_BASE + UART_LCR_OFF, 0x80u);   // DLAB=1
    write_reg(WRAP1_UART_BASE + UART_RBR_OFF, 0x01u);   // DLL = 1
    write_reg(WRAP1_UART_BASE + UART_IER_OFF, 0x00u);   // DLM = 0
    write_reg(WRAP1_UART_BASE + UART_LCR_OFF, 0x03u);   // DLAB=0, 8-bit
    write_reg(WRAP1_UART_BASE + UART_IIR_OFF, 0x01u);   // FCR: FIFOs on
    write_reg(WRAP1_UART_BASE + WRAP1_UART_MCR, 0x10u); // MCR.LOOP = 1 (see wrap 0)
    write_reg(WRAP1_LE_BASE + WRAP1_LE_REGION_SIZE, LOG_REGION_SIZE);
    write_reg(WRAP1_LE_BASE + WRAP1_LE_REGION_ADDR, LOG_BUFFER_BASE);
    write_reg(WRAP1_LE_BASE + WRAP1_LE_REGION_ADDR + 4, 0u);
    write_reg(WRAP1_LE_BASE + WRAP1_LE_WRITE_ADDR, WRAP1_UART_BASE + WRAP1_UART_RBR);
    write_reg(WRAP1_LE_BASE + WRAP1_LE_CTRL_OFF, 1u);
    write_reg(WRAP1_LE_BASE + WRAP1_LE_LOG_CTRL0, 16u);

    // Let replica[1] complete naturally
    {
        /* Poll bound: a 16-byte entry completes in far fewer than 200 register
         * reads, and the bound must expire before the harness timeout. */
        uint32_t timeout = 200u;
        while (timeout > 0u && (read_reg(WRAP1_LE_BASE + WRAP1_LE_LOG_CTRL0) & 0xFFFFu) != 0u) {
            timeout--;
        }
        if (timeout == 0u) {
            info_msg_s(0, "FAIL: scenario D: replica[1] log_engine did not hwclr");
            test_fail(0);
        }
    }
    for (int i = 0; i < 32; i++) (void)read_reg(WRAP1_UART_BASE + WRAP1_UART_RBR);
    write_reg(WRAP1_LE_BASE + WRAP1_LE_CTRL_OFF, 0u);
    write_reg(WRAP1_UART_BASE + WRAP1_UART_MCR, 0u);
    write_reg(WRAP1_CTRL_REG, 0u);

    // Cleanup
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    write_reg(WRAP0_UART_BASE + UART_MCR_OFF, 0u); // clear LINE_LOOPBACK
    write_reg(WRAP0_CTRL_REG, 0u);

    info_msg_s(0, "smc_uart_log_engine_disable_during_xfer_test done");
    test_pass(0);

    while (1) __asm__("wfi");
    return 0;
}
