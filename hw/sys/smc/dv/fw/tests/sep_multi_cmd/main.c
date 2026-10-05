/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SEP Multi-Command Interaction Test
 *
 * Verifies repeated command/response exchanges between SMC firmware and a testbench acting
 * as the SEP, with scratch registers as the transport. Each round applies a different
 * transform to the command (NOT, XOR mask, byte reverse, rotate left by 8), and the testbench
 * acknowledges each result by clearing the command.
 *
 * The testbench reads the handshake scratch directly, so the result goes to that scratch as
 * well as to the result scratch.
 */

#include <stdint.h>

#include "smc_defines.h"
#include "smc_test.h"

#define NUM_ROUNDS 4
#define CMD_READY_BASE 0xBEEF0000U /* ORed with the round number */
#define CMD_SCRATCH_NUM 5
#define RESULT_SCRATCH_NUM 6
#define HANDSHAKE_SCRATCH 1

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
        /* Clear the working scratch and signal ready for round r */
        write_scratch(CMD_SCRATCH_NUM, 0U);
        write_scratch(RESULT_SCRATCH_NUM, 0U);
        write_scratch(HANDSHAKE_SCRATCH, CMD_READY_BASE | r);

        /* Wait for the testbench to write a command */
        uint32_t cmd;
        do {
            cmd = read_scratch(CMD_SCRATCH_NUM);
        } while (cmd == 0U);

        /* Publish the result in both the result and the handshake scratch */
        uint32_t result = apply_operation(r, cmd);
        write_scratch(RESULT_SCRATCH_NUM, result);
        write_scratch(HANDSHAKE_SCRATCH, result);

        /* Wait for the testbench to acknowledge by clearing the command scratch */
        do {
            /* wait */
        } while (read_scratch(CMD_SCRATCH_NUM) != 0U);
    }

    test_pass(0);
}

/* No secondary_main: the crt0.S default runs main() on the boot hart only, so no other hart
 * writes the scratch registers the protocol uses. */
