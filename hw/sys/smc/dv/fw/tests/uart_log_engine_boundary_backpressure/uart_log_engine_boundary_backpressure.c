/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// smc_uart_log_engine_boundary_backpressure_test
//
// Four log_engine stimulus scenarios aimed at condition-coverage holes reported
// by the v15 cond-coverage analysis. Every quantity used to size the scenarios is
// taken from the IP documentation below, NOT from log_engine.sv.
//
// EXPECT-SOURCE — repo tt-oca-harness (open tree) @ rev 8dd61188, under hw/ip/uart/:
//   [S1] log_engine/doc/interface.adoc:15
//        NUM_LOG_ENTRIES = 16.
//   [S2] log_engine/doc/architecture.adoc:38-41
//        Fetch address = log_region_addr + (log_region_size/16)*log_index +
//        word_offset. Each entry therefore owns a slot of LOG_REGION_SIZE/16 bytes;
//        "slot size" below always means that quantity.
//   [S3] log_engine/doc/architecture.adoc:50-56 and :90-94
//        The fetch master reads 64-bit words (single-beat AXI4-Lite) and the write
//        FSM emits one UART byte at a time, with "FIFO ... accessed every eight
//        bytes" — i.e. one log word = 8 bytes.
//   [S4] log_engine/doc/architecture.adoc:43-48
//        RDATA FIFO: synchronous, 64-bit, configurable depth, default 4.
//   [S5] log_engine/doc/architecture.adoc:52-53
//        The write FSM "only advances when UART is ready and FIFO data is
//        available" — the UART-ready term is the backpressure input scenario B
//        targets.
//   [S6] uart_log_engine_wrap/doc/uart_log_engine_wrap.adoc:32-33
//        UART_TX_FIFO_DEPTH default 32 (the depth SMC integrates).
//
// SPEC GAPS — raised to the spec owner, deliberately NOT resolved by reading RTL.
// Tracked as DS-011..DS-013 in the SMC DV testplan UART_LOG_ENGINE_GAP_ANALYSIS.md.
//   [G1] No document states the behaviour when LOG_CTRL[i].LOG_LEN exceeds the
//        entry slot size of [S2]. Scenario D programs exactly that case, so it has
//        no spec-defined expected outcome and cannot carry a checker yet (DS-011).
//   [G2] uart_16550/doc/interface.adoc:123-125 defines txrdy_o only as "ready to
//        accept new data ... behavior depends on DMA mode"; the DMA-mode-0
//        condition is unspecified, so the exact stall pattern the write FSM sees is
//        not derivable from the documentation (DS-012).
//   [G3] The log-write master has no documented error responder — see
//        GAP_ANALYSIS TP-002: the UART register block answers OKAY to every write.
//        LOG_WRITE_ERR consequently has no spec-supported firmware stimulus, which
//        blocks scenario C (DS-013).
//
// Scenarios:
//   A — fetch retires on the requested length, short of the slot boundary.
//       region 0x100 → slot = 0x100/16 = 16 bytes [S1][S2]; log_len = 8 bytes =
//       exactly one log word [S3]. The fetch therefore completes on "requested
//       length reached" while the slot boundary is still 8 bytes away.
//   B — log write while the UART holds the engine off.
//       region 0x400 → slot = 64 bytes [S1][S2]; log_len = 64 bytes = 8 log words
//       [S3]. Stall mechanism per [S4][S5]: the fetch side pushes one 8-byte word
//       per read response while the write side consumes one word per eight UART
//       byte-writes, and every byte-write first waits for UART-ready. With the
//       4-entry RDATA FIFO of [S4] the whole transfer therefore runs at the UART's
//       drain rate. This is ONE coupled mechanism — not "the TX FIFO overflows at
//       byte 33"; the depth-32 of [S6] is the UART's own buffer and is not what
//       creates the stall.
//   C — log-write error. Not stimulable in this integration, see [G3]. Retained as
//       stimulus only; it carries no checker and proves nothing today.
//   D — LOG_LEN larger than the entry slot. No spec-defined outcome, see [G1].

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
// Scenario C's log_write target. It was chosen as an "undefined offset" that would
// decode-error; that premise is FALSE and is left in place only so the scenario is
// not silently re-armed with another guessed address:
//   - 0x20 is DEFINED. The generated map places ECR at 0x20 and ITR at 0x24
//     (hw/ip/uart/uart_16550/regs/gen/svh/uart_16550_main_reg.svh:48-51), so the
//     write is decoded and answered normally. The old comment's "real regs end at
//     0x1C" is stale.
//   - Even an out-of-range offset would not error: the generated UART register
//     block ties its write-error output to 0, so every write to this block returns
//     OKAY (GAP_ANALYSIS TP-002 / gap [G3] above).
// TODO(log-engine DV owner): scenario C cannot reach LOG_WRITE_ERR by any address.
// Decide between dropping it and re-arming it with a TB fault hook on the log_write
// B-channel. Do NOT "repair" it by picking a different offset.
#define UART_ECR_OFF 0x20u

static void setup_uart_8n1_fifo(void) {
    write_reg(WRAP0_CTRL_REG, 1u);                    // padmux enable
    write_reg(WRAP0_UART_BASE + UART_LCR_OFF, 0x80u); // DLAB=1
    write_reg(WRAP0_UART_BASE + UART_RBR_OFF, 0x01u); // DLL=1 (fastest divisor)
    write_reg(WRAP0_UART_BASE + UART_IER_OFF, 0x00u); // DLM=0
    write_reg(WRAP0_UART_BASE + UART_LCR_OFF, 0x03u); // DLAB=0, 8 bits, 1 stop, no parity
    write_reg(WRAP0_UART_BASE + UART_MCR_OFF, 0x10u); // MCR.LOOP=1 (TX drains internally)
    write_reg(WRAP0_UART_BASE + UART_IIR_OFF, 0x01u); // FCR.FIFO_ENABLE=1 (TX FIFO depth [S6])
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
    // SCENARIO A — fetch retires on the requested length, short of the slot
    // boundary. region 0x100 → slot = 16 bytes [S1][S2]; log_len = 8 bytes = one
    // 8-byte log word [S3].
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario A: fetch-done on requested length, inside the entry slot");
    {
        volatile uint8_t *buf = (volatile uint8_t *)(uintptr_t)LOG_BUFFER_BASE;
        for (int i = 0; i < 8; i++) buf[i] = (uint8_t)(0xA0u + i);

        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
        write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, 0x11u);  // clear stale
        write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, 0x100u); // slot = 0x100/16 = 16 B
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF, LOG_BUFFER_BASE);
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
        write_reg(WRAP0_LE_BASE + LE_WRITE_ADDR_OFF, WRAP0_UART_BASE + UART_RBR_OFF);
        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
        write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, 8u); // 1 log word, < 16 B slot

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
    // SCENARIO B — log write while the UART holds the engine off.
    // region 0x400 → slot = 64 bytes [S1][S2]; log_len = 64 bytes = 8 log words [S3].
    // The write FSM waits for UART-ready before every byte [S5] and drains the
    // 4-entry RDATA FIFO one word per eight bytes [S3][S4], so the engine runs at
    // the UART's serialisation rate for the whole transfer. Note this is NOT a
    // "TX FIFO overflows past 32 bytes" effect — see [G2] for what the spec does
    // and does not say about txrdy_o.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario B: log-write under TX backpressure");
    {
        volatile uint8_t *buf = (volatile uint8_t *)(uintptr_t)LOG_BUFFER_BASE;
        for (int i = 0; i < 64; i++) buf[i] = (uint8_t)(0x40u + i);

        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
        write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, 0x11u);
        write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, 0x400u); // slot = 0x400/16 = 64 B
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF, LOG_BUFFER_BASE);
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
        write_reg(WRAP0_LE_BASE + LE_WRITE_ADDR_OFF, WRAP0_UART_BASE + UART_RBR_OFF);
        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
        write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, 64u); // 8 log words, == 64 B slot

        // The UART drains at baud while the engine refills; the engine is held off
        // for most of the transfer. Generous timeout: 64 bytes * ~160 clk/byte +
        // margin. Expiry is a failure, never a pass.
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
    // SCENARIO C — BLOCKED, retained as stimulus only. It was written to produce a
    // real LOG_WRITE_ERR by aiming the log_write master at a supposedly undefined
    // UART offset. Both halves of that premise are false (see UART_ECR_OFF above
    // and gap [G3]): 0x20 is the defined ECR register, and the UART register block
    // returns OKAY for every write regardless of address, so no firmware-reachable
    // stimulus for LOG_WRITE_ERR exists in this integration.
    // The scenario therefore carries NO checker on purpose — adding one here would
    // fail for a reason the log engine is not responsible for. It is an owner
    // decision (drop it, or re-arm it with a TB fault hook); until then it must not
    // be counted as coverage of the log-write error path.
    // Side effect to be aware of: the 8 log bytes land in ECR, so this scenario
    // rewrites the UART extended-control register with data bytes.
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario C: log_write_err stimulus (BLOCKED, no error path - see [G3])");
    {
        volatile uint8_t *buf = (volatile uint8_t *)(uintptr_t)LOG_BUFFER_BASE;
        for (int i = 0; i < 8; i++) buf[i] = (uint8_t)(0xC0u + i);

        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
        write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, BIT_FETCH_ERR | BIT_WRITE_ERR);
        write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR | BIT_WRITE_ERR);
        write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, 0x100u);          // slot = 16 B
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF, LOG_BUFFER_BASE); // good fetch
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
        write_reg(WRAP0_LE_BASE + LE_WRITE_ADDR_OFF, WRAP0_UART_BASE + UART_ECR_OFF);
        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
        write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, 8u);

        // The only property this scenario can still assert is that the transfer
        // completes; the error it was written to create cannot occur here ([G3]).
        // No INTR_STATUS check is made, and none may be added while [G3] stands —
        // it would fail against a UART that has no error responder, not against a
        // log-engine defect.
        if (wait_log_done(LE_LOG_CTRL0_OFF, 200000u) != 0) {
            info_msg_s(0, "FAIL: scenario C: write did not complete");
            test_fail(0);
        }
        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
        write_reg(WRAP0_LE_BASE + LE_INTR_ENABLE_OFF, 0u);
        write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, BIT_FETCH_ERR | BIT_WRITE_ERR);
    }

    //--------------------------------------------------------------------------
    // SCENARIO D — LOG_LEN programmed larger than the entry slot: region 0x100 →
    // slot = 16 bytes [S1][S2], log_len = 24 bytes. No document defines what the
    // engine must do with an over-long entry (gap [G1]), so this scenario has no
    // spec-defined outcome and deliberately carries NO checker: any expectation
    // written today would be a transcription of the RTL it is meant to check.
    // The transfer is not expected to complete, so completion is not polled; the
    // scenario ends by writing CTRL.EN=0, which the spec does define as clearing
    // the FIFO (log_engine/doc/architecture.adoc:84).
    //--------------------------------------------------------------------------
    info_msg_s(0, "scenario D: LOG_LEN beyond the entry slot (no spec-defined outcome - [G1])");
    {
        volatile uint8_t *buf = (volatile uint8_t *)(uintptr_t)LOG_BUFFER_BASE;
        for (int i = 0; i < 16; i++) buf[i] = (uint8_t)(0x80u + i);

        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u);
        write_reg(WRAP0_LE_BASE + LE_INTR_STATUS_OFF, 0x11u);
        write_reg(WRAP0_LE_BASE + LE_REGION_SIZE_OFF, 0x100u);          // slot = 16 B
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF, LOG_BUFFER_BASE); // good fetch
        write_reg(WRAP0_LE_BASE + LE_REGION_ADDR_OFF + 4, 0u);
        write_reg(WRAP0_LE_BASE + LE_WRITE_ADDR_OFF, WRAP0_UART_BASE + UART_RBR_OFF);
        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 1u);
        write_reg(WRAP0_LE_BASE + LE_LOG_CTRL0_OFF, 24u); // 24 B > 16 B slot -> see [G1]

        // Fixed spin, with no spec bound behind the count: how long the fetch needs
        // to reach the slot boundary is not a documented quantity ([G1]/[G2]), so
        // there is nothing to bound this wait against and nothing it can be checked
        // for. It stays a magic number until [G1] is answered and this scenario is
        // rewritten around an observable event.
        for (volatile int i = 0; i < 5000; i++) {
        }

        write_reg(WRAP0_LE_BASE + LE_CTRL_OFF, 0u); // abort cleanly
    }

    // Cleanup
    write_reg(WRAP0_UART_BASE + UART_MCR_OFF, 0u);
    write_reg(WRAP0_CTRL_REG, 0u);

    info_msg_s(0, "smc_uart_log_engine_boundary_backpressure_test done");
    test_pass(0);

    while (1) __asm__("wfi");
    return 0;
}
