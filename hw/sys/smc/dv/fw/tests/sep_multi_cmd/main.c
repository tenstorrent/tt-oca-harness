/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SEP Multi-Command Interaction Test Firmware
 *
 * Tests multiple sequential command/response exchanges between SMC firmware
 * and the testbench acting as SEP via the AXI interface.
 *
 * Spec basis: OCAH Specification §Cryptographic Subsystem — SEP provides
 * security services to the rest of the system with repeated service calls.
 *
 * Protocol (NUM_ROUNDS rounds via scratch registers):
 *
 *   Per round r (0..NUM_ROUNDS-1):
 *     scratch[HANDSHAKE_SCRATCH] = CMD_READY_BASE | r    (FW signals ready)
 *     scratch[CMD_SCRATCH_NUM]   = <command from TB>      (TB writes command via AXI)
 *     scratch[RESULT_SCRATCH_NUM]= <operation(r, cmd)>   (FW writes result — backup)
 *     scratch[HANDSHAKE_SCRATCH] = <operation(r, cmd)>   (FW writes result into
 *                                                          the same wire TB polls directly;
 *                                                          TB reads this — no AXI read needed)
 *     scratch[CMD_SCRATCH_NUM]   = 0                      (TB acknowledges via AXI)
 *
 *   Operations applied per round:
 *     r=0: bitwise NOT of command
 *     r=1: XOR command with 0xDEADBEEF
 *     r=2: byte-reverse command
 *     r=3: rotate command left by 8 bits
 *
 *   scratch[0]: standard TEST_PASS / TEST_FAIL sentinel at end
 *
 * NOTE: Because scratch[HANDSHAKE_SCRATCH] is directly readable by the testbench
 * as a wire (dut.scratch_1), the TB can detect both the CMD_READY token AND the
 * result value without any AXI read.  AXI is used only for CMD writes and the ack.
 */

#include <stdint.h>
#include <stdbool.h>

#include "smc_defines.h"
#include "smc_test.h"

#define NUM_ROUNDS 4
#define CMD_READY_BASE 0xBEEF0000U /* OR with round number — TB waits for this */
#define CMD_SCRATCH_NUM 5
#define RESULT_SCRATCH_NUM 6
#define HANDSHAKE_SCRATCH 1

/* XOR mask used in round 1 */
#define XOR_MAGIC 0xDEADBEEFU

static uint32_t byte_reverse(uint32_t x) {
    return ((x & 0xFFU) << 24) | (((x >> 8) & 0xFFU) << 16) | (((x >> 16) & 0xFFU) << 8) |
           ((x >> 24) & 0xFFU);
}

static uint32_t rotate_left_8(uint32_t x) {
    return (x << 8) | (x >> 24);
}

static uint32_t apply_operation(uint32_t round, uint32_t cmd) {
    switch (round) {
    case 0:
        return ~cmd;
    case 1:
        return cmd ^ XOR_MAGIC;
    case 2:
        return byte_reverse(cmd);
    case 3:
        return rotate_left_8(cmd);
    default:
        return ~cmd;
    }
}

int main(void) {
    for (uint32_t r = 0; r < NUM_ROUNDS; r++) {
        /* Phase 1: clear working scratches, signal ready for round r */
        write_scratch(CMD_SCRATCH_NUM, 0U);
        write_scratch(RESULT_SCRATCH_NUM, 0U);
        write_scratch(HANDSHAKE_SCRATCH, CMD_READY_BASE | r);

        /* Phase 2: wait for testbench (SEP) to write a command */
        uint32_t cmd;
        do {
            cmd = read_scratch(CMD_SCRATCH_NUM);
        } while (cmd == 0U);

        /* Phase 3: compute result.
         * Write result to RESULT_SCRATCH_NUM (scratch[6]) as backup,
         * then overwrite HANDSHAKE_SCRATCH (scratch[1]) with the result so
         * the testbench can read it directly via the RTL wire without AXI. */
        uint32_t result = apply_operation(r, cmd);
        write_scratch(RESULT_SCRATCH_NUM, result);
        write_scratch(HANDSHAKE_SCRATCH, result);

        /* Phase 4: wait for testbench to acknowledge by clearing CMD scratch */
        do {
            /* wait */
        } while (read_scratch(CMD_SCRATCH_NUM) != 0U);
    }

    /* All rounds complete */
    test_pass(0);

    while (true) {
        __asm__("wfi");
    }
    return 0;
}

/* secondary_main is not defined here: the weak default in crt0.S routes the
 * boot hart to main() and spins non-boot harts, so no second core can write
 * the shared scratch registers used by the test protocol. */
