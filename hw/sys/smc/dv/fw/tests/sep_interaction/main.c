/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SEP Interaction Test Firmware
 *
 * Tests two-way communication between SMC firmware and the testbench
 * acting as the SEP via the AXI interface.
 *
 * Protocol (all via scratch registers):
 *   scratch[1]: firmware signals ready by writing CMD_READY_TOKEN
 *   scratch[5]: testbench writes a 32-bit command value
 *   scratch[6]: firmware writes bitwise complement of the command as result
 *   scratch[0]: standard pass/fail (TEST_PASS / TEST_FAIL)
 */

#include <stdint.h>

#include "smc_defines.h"
#include "smc_test.h"

#define CMD_READY_TOKEN    0xBEEFCAFEU
#define CMD_SCRATCH_NUM    5
#define RESULT_SCRATCH_NUM 6
#define HANDSHAKE_SCRATCH  1

int main(void) {
    /* Phase 1: clear working scratches then signal ready to testbench */
    write_scratch(CMD_SCRATCH_NUM, 0U);
    write_scratch(RESULT_SCRATCH_NUM, 0U);
    write_scratch(HANDSHAKE_SCRATCH, CMD_READY_TOKEN);

    /* Phase 2: wait for testbench (SEP) to write a command via AXI */
    uint32_t cmd;
    do {
        cmd = read_scratch(CMD_SCRATCH_NUM);
    } while (cmd == 0U);

    /* Phase 3: compute response (bitwise complement) and write result */
    write_scratch(RESULT_SCRATCH_NUM, ~cmd);

    /* Phase 4: report test pass */
    test_pass(0);

    /* unreachable */
    while (true) {
        __asm__("wfi");
    }
    return 0;
}

int secondary_main(void) {
    return main();
}
