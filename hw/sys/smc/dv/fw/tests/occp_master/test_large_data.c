/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Writes and reads back a 16-byte buffer in one OCCP command and compares the data.
 */

#include "occp_test_common.h"

bool run_large_data_tests(test_context_t *ctx) {
    bool result = true;
    int test_status;

    simputs("=== Large Data Transfer Tests ===\n");

    uint8_t large_data[16] = {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
                              0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x10};
    uint8_t recv_large_data[16] = {0};
    const uint64_t large_addr = ctx->test_base_addr + 0x400;

    test_status =
        occp_send_write_command(ctx, ctx->slave_addr, large_addr, large_data, sizeof(large_data));
    result &= (test_status == OCCP_SUCCESS);
    test_status = occp_send_read_command(ctx, ctx->slave_addr, large_addr, recv_large_data,
                                         sizeof(recv_large_data));
    result &= (test_status == OCCP_SUCCESS);

    bool large_data_match = true;
    for (size_t i = 0; i < sizeof(large_data); i++) {
        if (large_data[i] != recv_large_data[i]) {
            large_data_match = false;
            break;
        }
    }
    result &= large_data_match;
    if (large_data_match) {
        simputs("Large data transfer: PASS\n");
    } else {
        simputs("Large data transfer: FAIL\n");
    }

    return result;
}
