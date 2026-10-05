/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Sends GET_VERSION, GET_STATUS, GET_SEP_STATUS and GET_SMC_STATUS; checks the version value.
 */

#include "occp_test_common.h"

bool run_get_commands_tests(test_context_t *ctx) {
    bool result = true;
    uint32_t status_data = 0;
    int test_status;

    simputs("=== GET Commands Tests ===\n");

    simputs("--- Test 1: GET_VERSION ---\n");
    test_status = occp_send_get_version_command(ctx, ctx->slave_addr, &status_data);
    if (test_status == OCCP_SUCCESS) {
        simputshex32("OCCP Version: ", status_data);
        result &= (status_data == 0x00010000);
        simputs("GET_VERSION: PASS\n");
    } else {
        simputs("GET_VERSION: FAIL\n");
        result = false;
    }

    simputs("\n--- Test 2: GET_STATUS ---\n");
    test_status = occp_send_get_status_command(ctx, ctx->slave_addr, &status_data);
    if (test_status == OCCP_SUCCESS) {
        simputshex32("General Status: ", status_data);
        simputs("GET_STATUS: PASS\n");
    } else {
        simputs("GET_STATUS: FAIL\n");
        result = false;
    }

    simputs("\n--- Test 3: GET_SEP_STATUS ---\n");
    test_status = occp_send_get_sep_status_command(ctx, ctx->slave_addr, &status_data);
    if (test_status == OCCP_SUCCESS) {
        simputshex32("SEP Status: ", status_data);
        simputs("GET_SEP_STATUS: PASS\n");
    } else {
        simputs("GET_SEP_STATUS: FAIL\n");
        result = false;
    }

    simputs("\n--- Test 4: GET_SMC_STATUS ---\n");
    test_status = occp_send_get_smc_status_command(ctx, ctx->slave_addr, &status_data);
    if (test_status == OCCP_SUCCESS) {
        simputshex32("SMC Status: ", status_data);
        simputs("GET_SMC_STATUS: PASS\n");
    } else {
        simputs("GET_SMC_STATUS: FAIL\n");
        result = false;
    }

    return result;
}
