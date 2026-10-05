/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Writes and reads back 8-, 4- and 1-byte values over OCCP and compares the data.
 */

#include "occp_test_common.h"

bool run_basic_rw_tests(test_context_t *ctx) {
    bool result = true;
    int test_status;

    simputs("=== Basic READ/WRITE Tests ===\n");

    uint64_t data64 = 0xdeadbeefcafeb0ba;
    uint64_t recv_data64 = 0;
    simputs("Test 5a: 8-byte aligned write/read\n");
    test_status = occp_send_write_command(ctx, ctx->slave_addr, ctx->test_base_addr,
                                          (uint8_t *)&data64, sizeof(data64));
    result &= (test_status == OCCP_SUCCESS);
    test_status = occp_send_read_command(ctx, ctx->slave_addr, ctx->test_base_addr,
                                         (uint8_t *)&recv_data64, sizeof(recv_data64));
    result &= (test_status == OCCP_SUCCESS);
    result &= (recv_data64 == data64);
    if (recv_data64 == data64) {
        simputs("8-byte aligned R/W: PASS\n");
    } else {
        simputs("8-byte aligned R/W: FAIL\n");
        simputshex64("Expected: ", data64);
        simputshex64("Received: ", recv_data64);
    }

    uint32_t data32 = 0x12345678;
    uint32_t recv_data32 = 0;
    const uint64_t test_addr32 = ctx->test_base_addr + 0x100;
    simputs("Test 5b: 4-byte write/read\n");
    test_status = occp_send_write_command(ctx, ctx->slave_addr, test_addr32, (uint8_t *)&data32,
                                          sizeof(data32));
    result &= (test_status == OCCP_SUCCESS);
    test_status = occp_send_read_command(ctx, ctx->slave_addr, test_addr32, (uint8_t *)&recv_data32,
                                         sizeof(recv_data32));
    result &= (test_status == OCCP_SUCCESS);
    result &= (recv_data32 == data32);
    if (recv_data32 == data32) {
        simputs("4-byte R/W: PASS\n");
    } else {
        simputs("4-byte R/W: FAIL\n");
        simputshex32("Expected: ", data32);
        simputshex32("Received: ", recv_data32);
    }

    uint8_t data8 = 0xAB;
    uint8_t recv_data8 = 0;
    const uint64_t test_addr8 = ctx->test_base_addr + 0x200;
    simputs("Test 5c: Single byte write/read\n");
    test_status = occp_send_write_command(ctx, ctx->slave_addr, test_addr8, &data8, sizeof(data8));
    result &= (test_status == OCCP_SUCCESS);
    test_status =
        occp_send_read_command(ctx, ctx->slave_addr, test_addr8, &recv_data8, sizeof(recv_data8));
    result &= (test_status == OCCP_SUCCESS);
    result &= (recv_data8 == data8);
    if (recv_data8 == data8) {
        simputs("Single byte R/W: PASS\n");
    } else {
        simputs("Single byte R/W: FAIL\n");
        simputhex16(data8);
        simputs(" != ");
        simputhex16(recv_data8);
        simputs("\n");
    }

    return result;
}
