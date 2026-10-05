/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SEP Interaction Test
 *
 * Verifies a single command exchange between SMC firmware and the testbench
 * acting as SEP over the scratch registers. The firmware answers with the
 * bitwise complement of the command and always reports pass; the testbench
 * checks the answer.
 */

#include <stdint.h>

#include "smc_defines.h"
#include "smc_test.h"

#define CMD_READY_TOKEN 0xBEEFCAFEU
#define CMD_SCRATCH_NUM 5
#define RESULT_SCRATCH_NUM 6
#define HANDSHAKE_SCRATCH 1

int main(void) {
    write_scratch(CMD_SCRATCH_NUM, 0U);
    write_scratch(RESULT_SCRATCH_NUM, 0U);
    write_scratch(HANDSHAKE_SCRATCH, CMD_READY_TOKEN);

    /* Wait for the testbench's command */
    uint32_t cmd;
    do {
        cmd = read_scratch(CMD_SCRATCH_NUM);
    } while (cmd == 0U);

    write_scratch(RESULT_SCRATCH_NUM, ~cmd);

    test_pass(0);
}

int secondary_main(void) {
    return main();
}
