/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/**
 * @brief UART Log Engine Disable During Transfer
 *
 * Verifies that disabling the log engine in the middle of a transfer halts it
 * and leaves the engine usable. The engine writes into the UART in internal
 * loopback, so the firmware counts the bytes it moved. Each abort must move at
 * least one byte and fewer than the entry holds, all from the slot, and none
 * once the UART is idle; a following 16-byte entry must then deliver exactly
 * its bytes in order without an error. The first abort lands one register
 * access after the trigger and must not raise an error; the second lands after
 * a short spin, and its error status is only logged. The entry length read
 * while the engine is disabled is not specified, so it is only logged.
 */

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
#define UART_LSR_OFF \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR(0) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR(0))
#define UART_LSR_DR 0x1u
#define UART_LSR_TEMT 0x40u

#define LOG_BUFFER_BASE (SMC_TOP_SPM_MEMORY_BASE_ADDR + 0x40000u)
#define LOG_REGION_SIZE 0x100u // 16-byte slots
// The abort scenarios use a 32-byte slot: as deep as the UART TX FIFO, so the
// writer cannot finish before the disable one register access later lands.
#define ABORT_REGION_SIZE 0x200u // 32-byte slots
#define ABORT_ENTRY_BYTES 32u
#define RETRIGGER_ENTRY_BYTES 16u

// Consecutive RBR-empty polls after which the loopback is taken as idle. One
// byte at the fastest divisor is 160 clocks; a poll is a handful of register
// reads, so this covers many byte times.
#define UART_IDLE_POLLS 2000u

// Drain RBR as bytes arrive until the UART has been idle (TEMT set, DR clear)
// for UART_IDLE_POLLS polls. Reading as they land keeps the count independent
// of the RX FIFO depth. Returns the byte count; *pattern_ok clears on the first
// byte that differs from expect(index).
static uint32_t drain_uart_rx(uint8_t (*expect)(uint32_t), int *pattern_ok) {
    uint32_t count = 0u;
    uint32_t idle = 0u;
    *pattern_ok = 1;
    while (idle < UART_IDLE_POLLS) {
        uint32_t lsr = read_reg(WRAP0_UART_BASE + UART_LSR_OFF);
        if ((lsr & UART_LSR_DR) != 0u) {
            uint8_t got = (uint8_t)(read_reg(WRAP0_UART_BASE + UART_RBR_OFF) & 0xFFu);
            if (got != expect(count)) *pattern_ok = 0;
            count++;
            idle = 0u;
        } else if ((lsr & UART_LSR_TEMT) != 0u) {
            idle++;
        }
    }
    return count;
}

static uint8_t abort_pattern_a(uint32_t index) {
    return (uint8_t)(0xA0u + index);
}
static uint8_t abort_pattern_c(uint32_t index) {
    return (uint8_t)(0xC0u + (index & 0x3Fu));
}

// Abort check shared by scenarios A and C: the entry had started (at least one
// byte reached the UART) and moved fewer bytes than it holds, the bytes it did
// move are the slot's, and nothing follows once the UART is idle. A disable
// that landed before the first byte would prove nothing about halting, so
// zero fails too.
static void check_aborted_transfer(const char *tag, uint8_t (*expect)(uint32_t)) {
    int pattern_ok = 0;
    uint32_t moved = drain_uart_rx(expect, &pattern_ok);
    info_msg_hex32_s(0, "bytes moved before the disable took effect=", moved);
    if (moved == 0u) {
        info_msg_s(0, tag);
        info_msg_s(0,
                   "FAIL: no byte reached the UART before the disable, so no transfer was halted");
        test_fail(0);
    }
    if (moved >= ABORT_ENTRY_BYTES) {
        info_msg_s(0, tag);
        info_msg_s(0, "FAIL: the whole entry arrived, so nothing halted");
        test_fail(0);
    }
    if (!pattern_ok) {
        info_msg_s(0, tag);
        info_msg_s(0, "FAIL: a moved byte was not the slot's");
        test_fail(0);
    }
    int late_ok = 0;
    if (drain_uart_rx(expect, &late_ok) != 0u) {
        info_msg_s(0, tag);
        info_msg_s(0, "FAIL: bytes kept arriving after the UART had gone idle");
        test_fail(0);
    }
}

// Recovery shared by scenarios A and C: with EN still 0 put the slot geometry
// back, re-enable, trigger a 16-byte entry and require exactly those 16 bytes.
static void check_retrigger_delivers(const char *tag, uint8_t (*expect)(uint32_t)) {
    write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, LOG_REGION_SIZE);
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, 0x11u); // clear stale error status
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
    write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, RETRIGGER_ENTRY_BYTES);
    {
        /* Poll bound: a 16-byte entry takes ~2600 peripheral clocks at the
         * fastest divisor, about 650 register reads at the 1.25 ns core clock;
         * the bound must expire before the harness timeout. */
        uint32_t timeout = 4000u;
        while (timeout > 0u && (read_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF) & 0xFFFFu) != 0u) {
            timeout--;
        }
        if (timeout == 0u) {
            info_msg_s(0, tag);
            info_msg_s(0, "FAIL: re-trigger: LOG_CTRL[0] did not hwclr");
            test_fail(0);
        }
    }
    int pattern_ok = 0;
    uint32_t moved = drain_uart_rx(expect, &pattern_ok);
    if (moved != RETRIGGER_ENTRY_BYTES || !pattern_ok) {
        info_msg_s(0, tag);
        info_msg_hex32_s(0, "FAIL: re-trigger delivered a wrong byte set, count=", moved);
        test_fail(0);
    }
    {
        uint32_t st = read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & 0x11u;
        if (st != 0u) {
            info_msg_s(0, tag);
            info_msg_hex32_s(0, "FAIL: INTR_STATUS set after clean re-run=", st);
            test_fail(0);
        }
    }
}

int main(void) {
    info_msg_s(0, "smc_uart_log_engine_disable_during_xfer_test start");

    // Entry 0's slot starts at the region base
    volatile uint8_t *buf = (volatile uint8_t *)(uintptr_t)LOG_BUFFER_BASE;
    for (uint32_t i = 0; i < ABORT_ENTRY_BYTES; i++) {
        buf[i] = abort_pattern_a(i);
    }

    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    write_reg(WRAP0_CTRL_REG, 1u);

    /* UART at the fastest rate with 8-bit words, FIFOs and internal loopback,
     * so every byte the engine writes comes back on the receive side. The
     * engine writes to UART offset 0, which is the transmit register only
     * while divisor latch access is off, so the UART is set up first. */
    write_reg(WRAP0_UART_BASE + UART_LCR_OFF, 0x80u);
    write_reg(WRAP0_UART_BASE + UART_RBR_OFF, 0x01u);
    write_reg(WRAP0_UART_BASE + UART_IER_OFF, 0x00u);
    write_reg(WRAP0_UART_BASE + UART_LCR_OFF, 0x03u);
    write_reg(WRAP0_UART_BASE + UART_IIR_OFF, 0x01u);
    write_reg(WRAP0_UART_BASE + UART_MCR_OFF, 0x10u);
    write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, ABORT_REGION_SIZE);
    write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF, LOG_BUFFER_BASE);
    write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
    write_reg(WRAP0_LE_BASE + LE_WRITE_ADDR_OFF, WRAP0_UART_BASE + UART_RBR_OFF);
    /* Error status latches whether or not its interrupt is enabled; enabling
     * also drives the interrupt line on an error. */
    write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, 0x11u);
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);

    //--------------------------------------------------------------------------
    // SCENARIO A: trigger entry 0 with the 32-byte slot and disable one register
    // access later, while the writer is still moving bytes.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario A: disable mid-transfer");
    write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, ABORT_ENTRY_BYTES);

    uint32_t snap1 = read_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF);
    info_msg_hex32_s(0, "LOG_CTRL[0] post-trigger=", snap1);

    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);

    uint32_t snap2 = read_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF);
    info_msg_hex32_s(0, "LOG_CTRL[0] post-disable=", snap2);

    // Disabling must not raise an error
    {
        uint32_t s = read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & 0x11u;
        if (s != 0u) {
            info_msg_hex32_s(0, "FAIL: INTR_STATUS unexpectedly set after disable=", s);
            test_fail(0);
        }
    }

    // The bytes that reached the UART before the disable took effect come back
    // through the loopback; count them as they land.
    check_aborted_transfer("scenario A", abort_pattern_a);

    //--------------------------------------------------------------------------
    // Re-enable and trigger a 16-byte entry: exactly those bytes must arrive.
    //--------------------------------------------------------------------------
    check_retrigger_delivers("scenario A re-trigger", abort_pattern_a);

    //--------------------------------------------------------------------------
    // SCENARIO B: four entries triggered together must all complete. The
    // looped-back bytes are discarded unchecked.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario B: multi-entry simultaneous trigger");

#define LE_LOG_CTRL_I_OFF(i) \
    (SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_LOG_CTRL_BASE_ADDR(0, (i)) - \
     SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_BASE_ADDR(0))

    // Scenario C's abort reads this pattern too
    for (uint32_t i = 0; i < LOG_REGION_SIZE; i++) {
        buf[i] = (uint8_t)(0xC0u + (i & 0x3Fu));
    }

    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);

    write_reg(WRAP0_LE_BASE + LE_LOG_CTRL_I_OFF(0), 16u);
    write_reg(WRAP0_LE_BASE + LE_LOG_CTRL_I_OFF(1), 16u);
    write_reg(WRAP0_LE_BASE + LE_LOG_CTRL_I_OFF(2), 16u);
    write_reg(WRAP0_LE_BASE + LE_LOG_CTRL_I_OFF(3), 16u);

    {
        /* Poll bound: far longer than the four entries take to complete, and
         * it must expire before the harness timeout. */
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
    // Discard the looped-back bytes
    for (int i = 0; i < 64; i++) {
        (void)read_reg(WRAP0_UART_BASE + UART_RBR_OFF);
    }

    //--------------------------------------------------------------------------
    // SCENARIO C: disable a 32-byte entry a short time after it starts, then
    // require the same halt and recovery as scenario A.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario C: abort while FSM is in WAIT");

    // Give the abort the 32-byte slot again; it now holds scenario B's pattern
    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
    write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, 0x11u);
    write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, ABORT_REGION_SIZE);

    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
    write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, ABORT_ENTRY_BYTES);

    // Short spin intended to let the first fetch go out before the disable
    for (volatile int i = 0; i < 50; i++) {
    }

    write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);

    {
        uint32_t s = read_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF) & 0x11u;
        info_msg_hex32_s(0, "scenario C INTR_STATUS=", s);
        // INTR_STATUS after an abort in WAIT is not pinned: an in-flight beat
        // may or may not have raised an error before the disable took effect.
    }

    // The halt itself is pinned: fewer than the entry's 32 bytes arrive, and
    // none after the UART goes idle. Then the engine must run a clean entry.
    check_aborted_transfer("scenario C", abort_pattern_c);
    check_retrigger_delivers("scenario C re-trigger", abort_pattern_c);

    //--------------------------------------------------------------------------
    // SCENARIO D: UART log engine wrapper 1 runs one entry to completion
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
    // Same UART setup as wrapper 0, for the same reason
    write_reg(WRAP1_UART_BASE + UART_LCR_OFF, 0x80u);
    write_reg(WRAP1_UART_BASE + UART_RBR_OFF, 0x01u);
    write_reg(WRAP1_UART_BASE + UART_IER_OFF, 0x00u);
    write_reg(WRAP1_UART_BASE + UART_LCR_OFF, 0x03u);
    write_reg(WRAP1_UART_BASE + UART_IIR_OFF, 0x01u);
    write_reg(WRAP1_UART_BASE + WRAP1_UART_MCR, 0x10u);
    write_reg(WRAP1_LE_BASE + WRAP1_LE_REGION_SIZE, LOG_REGION_SIZE);
    write_reg(WRAP1_LE_BASE + WRAP1_LE_REGION_ADDR, LOG_BUFFER_BASE);
    write_reg(WRAP1_LE_BASE + WRAP1_LE_REGION_ADDR + 4, 0u);
    write_reg(WRAP1_LE_BASE + WRAP1_LE_WRITE_ADDR, WRAP1_UART_BASE + WRAP1_UART_RBR);
    write_reg(WRAP1_LE_BASE + WRAP1_LE_CTRL_OFF, 1u);
    write_reg(WRAP1_LE_BASE + WRAP1_LE_LOG_CTRL0, 16u);

    {
        /* Poll bound: a 16-byte entry takes ~2600 peripheral clocks at the
         * fastest divisor, about 650 register reads at the 1.25 ns core clock;
         * the bound must expire before the harness timeout. */
        uint32_t timeout = 4000u;
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
    write_reg(WRAP0_UART_BASE + UART_MCR_OFF, 0u);
    write_reg(WRAP0_CTRL_REG, 0u);

    info_msg_s(0, "smc_uart_log_engine_disable_during_xfer_test done");
    test_pass(0);
}
