/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Writes and reads back 8- to 32-byte transfers over OCCP; reports results but never fails.
 */

#include "occp_test_common.h"

bool run_size_limit_tests(test_context_t *ctx) {
    int test_status;

    simputs("=== I3C Transfer Size Limit Tests ===\n");

    const uint64_t limit_addr = ctx->test_base_addr + 0x700;

    uint8_t sizes_to_test[] = {8, 16, 24, 32};
    for (size_t size_idx = 0; size_idx < sizeof(sizes_to_test) / sizeof(sizes_to_test[0]);
         size_idx++) {
        uint8_t test_size = sizes_to_test[size_idx];
        uint8_t test_data[32];
        uint8_t recv_data[32] = {0};

        for (int i = 0; i < test_size; i++) {
            test_data[i] = (uint8_t)(0x80 + i);
        }

        uint64_t test_size_addr = limit_addr + (size_idx * 64);

        simputshex16("Testing size: ", test_size);
        test_status =
            occp_send_write_command(ctx, ctx->slave_addr, test_size_addr, test_data, test_size);
        if (test_status != OCCP_SUCCESS) {
            simputshex16("Write failed for size: ", test_size);
            continue;
        }

        test_status =
            occp_send_read_command(ctx, ctx->slave_addr, test_size_addr, recv_data, test_size);
        if (test_status != OCCP_SUCCESS) {
            simputshex16("Read failed for size: ", test_size);
            continue;
        }

        bool data_match = true;
        for (int i = 0; i < test_size; i++) {
            if (test_data[i] != recv_data[i]) {
                data_match = false;
                break;
            }
        }

        if (data_match) {
            simputshex16("Size test PASS: ", test_size);
        } else {
            simputshex16("Size test FAIL: ", test_size);
        }
    }

    simputs("I3C Transfer limits: Tested various sizes\n");

    return true;
}
