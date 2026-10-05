/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Writes and reads back a word at fixed addresses around a 4 KiB boundary over OCCP.
 */

#include "occp_test_common.h"

bool run_boundary_tests(test_context_t *ctx) {
    bool result = true;
    int test_status;

    simputs("=== Memory Boundary Tests ===\n");

    uint64_t boundary_addrs[] = {0xC00B0000, 0xC00B0FF8, 0xC00B1000};
    bool boundary_test_pass = true;

    for (size_t i = 0; i < sizeof(boundary_addrs) / sizeof(boundary_addrs[0]); i++) {
        uint32_t boundary_data = 0xB000DA17 + i;
        uint32_t recv_boundary_data = 0;

        test_status = occp_send_write_command(ctx, ctx->slave_addr, boundary_addrs[i],
                                              (uint8_t *)&boundary_data, sizeof(boundary_data));
        if (test_status != OCCP_SUCCESS) {
            boundary_test_pass = false;
            simputshex64("Boundary write failed at: ", boundary_addrs[i]);
            break;
        }

        test_status =
            occp_send_read_command(ctx, ctx->slave_addr, boundary_addrs[i],
                                   (uint8_t *)&recv_boundary_data, sizeof(recv_boundary_data));
        if (test_status != OCCP_SUCCESS || recv_boundary_data != boundary_data) {
            boundary_test_pass = false;
            simputshex64("Boundary read failed at: ", boundary_addrs[i]);
            break;
        }
    }

    result &= boundary_test_pass;
    if (boundary_test_pass) {
        simputs("Boundary testing: PASS\n");
    } else {
        simputs("Boundary testing: FAIL\n");
    }

    return result;
}
