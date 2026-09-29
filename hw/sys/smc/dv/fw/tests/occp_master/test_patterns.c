/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Writes and reads back six 64-bit data patterns over OCCP and compares each one.
 */

#include "occp_test_common.h"

bool run_pattern_tests(test_context_t *ctx) {
    bool result = true;
    int test_status;

    simputs("=== Pattern Verification Tests ===\n");

    const uint64_t pattern_addr = ctx->test_base_addr + 0x600;
    uint64_t patterns[] = {0x0000000000000000, 0xFFFFFFFFFFFFFFFF, 0x5555555555555555,
                           0xAAAAAAAAAAAAAAAA, 0x0123456789ABCDEF, 0xFEDCBA9876543210};
    bool pattern_test_pass = true;

    for (size_t i = 0; i < sizeof(patterns) / sizeof(patterns[0]); i++) {
        uint64_t recv_pattern = 0;
        uint64_t test_pattern_addr = pattern_addr + (i * 8);

        test_status = occp_send_write_command(ctx, ctx->slave_addr, test_pattern_addr,
                                              (uint8_t *)&patterns[i], sizeof(patterns[i]));
        if (test_status != OCCP_SUCCESS) {
            pattern_test_pass = false;
            break;
        }

        test_status = occp_send_read_command(ctx, ctx->slave_addr, test_pattern_addr,
                                             (uint8_t *)&recv_pattern, sizeof(recv_pattern));
        if (test_status != OCCP_SUCCESS || recv_pattern != patterns[i]) {
            pattern_test_pass = false;
            simputshex64("Pattern mismatch - Expected: ", patterns[i]);
            simputshex64("Received: ", recv_pattern);
            break;
        }
    }

    result &= pattern_test_pass;
    if (pattern_test_pass) {
        simputs("Pattern verification: PASS\n");
    } else {
        simputs("Pattern verification: FAIL\n");
    }

    return result;
}
