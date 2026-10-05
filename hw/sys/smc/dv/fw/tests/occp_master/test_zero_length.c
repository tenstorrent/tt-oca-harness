/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Sends a zero-length OCCP WRITE and reports whether it is accepted; never fails.
 */

#include "occp_test_common.h"

bool run_zero_length_tests(test_context_t *ctx) {
    int test_status;

    simputs("=== Zero Length Transfer Tests ===\n");

    uint8_t dummy_data = 0;
    test_status =
        occp_send_write_command(ctx, ctx->slave_addr, ctx->test_base_addr + 0x500, &dummy_data, 0);
    if (test_status == OCCP_SUCCESS) {
        simputs("Zero length write: Handled gracefully\n");
    } else {
        simputs("Zero length write: Rejected (expected behavior)\n");
    }

    return true;
}
