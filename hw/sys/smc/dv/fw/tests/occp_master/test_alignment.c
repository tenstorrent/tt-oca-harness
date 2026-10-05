/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Checks that OCCP WRITE and READ at a misaligned address both return success.
 */

#include "occp_test_common.h"

bool run_alignment_tests(test_context_t *ctx) {
    bool result = true;
    int test_status;

    simputs("=== Address Alignment Tests ===\n");

    const uint64_t misaligned_addr = ctx->test_base_addr + 0x305;
    uint16_t data16 = 0x5678;
    uint16_t recv_data16 = 0;
    simputs("Test 6a: Misaligned address auto-alignment\n");
    test_status = occp_send_write_command(ctx, ctx->slave_addr, misaligned_addr, (uint8_t *)&data16,
                                          sizeof(data16));
    result &= (test_status == OCCP_SUCCESS);
    test_status = occp_send_read_command(ctx, ctx->slave_addr, misaligned_addr,
                                         (uint8_t *)&recv_data16, sizeof(recv_data16));
    result &= (test_status == OCCP_SUCCESS);
    if (test_status == OCCP_SUCCESS) {
        simputs("Misaligned address handling: PASS\n");
    } else {
        simputs("Misaligned address handling: FAIL\n");
    }

    return result;
}
