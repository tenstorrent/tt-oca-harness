/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Brings up the OCCP transport the BOOT_I2C strap selects, sends one GET_VERSION and checks
 * the ROM's version, then carries the verdict to the DUT's SCRATCH[0] with an OCCP WRITE.
 * It issues no OCCP READ, so a pass says nothing about OCCP memory access.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"
#include <string.h>

#define OCCP_EXPECTED_VERSION 0x00000001u

#define OCCP_VERSION_NOT_RECEIVED 0xDEADBEEFu

/* Poll count, not time: 0 makes the OCCP receive loops wait forever on a silent target. */
#define OCCP_SANITY_TIMEOUT 10000

static const char *occp_result_name(int retval) {
    switch (retval) {
    case OCCP_SUCCESS:
        return "OCCP_SUCCESS";
    case OCCP_INVALID_CMD:
        return "OCCP_INVALID_CMD";
    case OCCP_INVALID_ARG:
        return "OCCP_INVALID_ARG";
    case OCCP_MEM_ACCESS_ERR:
        return "OCCP_MEM_ACCESS_ERR";
    case OCCP_UNALIGNED_ADDR_ERR:
        return "OCCP_UNALIGNED_ADDR_ERR";
    case OCCP_INTERFACE_ERR:
        return "OCCP_INTERFACE_ERR";
    case OCCP_READ_UNDERFLOW:
        return "OCCP_READ_UNDERFLOW";
    case OCCP_ERR:
        return "OCCP_ERR";
    case OCCP_TIMEOUT:
        return "OCCP_TIMEOUT";
    default:
        return "unrecognised occp_result_t";
    }
}

static void report_occp_failure(const char *what, int retval) {
    simputs("FAIL: ");
    simputs(what);
    simputs(" did not complete: ");
    simputs(occp_result_name(retval));
    simputs("\n");
    simputshex32("  occp_result_t: ", (uint32_t)retval);
}

static void run_test_suite(test_context_t *ctx) {
    simputs("=== Starting OCCP bring-up + GET_VERSION sanity test ===\n");

    ctx->overall_result = true;

    uint32_t version = OCCP_VERSION_NOT_RECEIVED;
    int retval = occp_send_get_version_command(ctx, ctx->slave_addr, &version);
    if (retval != OCCP_SUCCESS) {
        report_occp_failure("GET_VERSION", retval);
        ctx->overall_result = false;
        return;
    }

    simputshex32("OCCP Version: ", version);
    if (version != OCCP_EXPECTED_VERSION) {
        simputs("FAIL: OCCP version mismatch\n");
        simputshex32("Expected: ", OCCP_EXPECTED_VERSION);
        simputshex32("Actual: ", version);
        ctx->overall_result = false;
        return;
    }

    simputs("GET_VERSION: PASS\n");
}

static void finalize_test_results(test_context_t *ctx) {
    uint32_t result_code;

    if (ctx->overall_result) {
        simputs("ALL TESTS PASSED!\n");
        result_code = SMC_SCRATCHPAD_SIM_PASS_CODE;
    } else {
        simputs("SOME TESTS FAILED!\n");
        result_code = SMC_SCRATCHPAD_SIM_FAIL_CODE;
    }

    int retval =
        occp_send_write_command(ctx, ctx->slave_addr, SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(0),
                                (uint8_t *)&result_code, sizeof(result_code));
    if (retval != OCCP_SUCCESS) {
        report_occp_failure("verdict OCCP WRITE to DUT SCRATCH[0]", retval);
        ctx->overall_result = false;
    }

    if (!ctx->overall_result) {
        /* No matching test_pass(): PASS must come from the DUT's SCRATCH[0] via OCCP. */
        test_fail(0);
    }
}

int main(void) {
    static test_context_t test_ctx = {0};

    init_test(0);

    test_ctx.timeout = OCCP_SANITY_TIMEOUT;
    test_ctx.exp_timeout = false;

    if (!initialize_interface(&test_ctx)) {
        simputs("FAIL: Interface initialization failed\n");
        test_fail(0);
    }

    run_test_suite(&test_ctx);

    finalize_test_results(&test_ctx);

    simputs("Done\n");
    while (true) {
        __asm__("wfi");
    }

    return 0;
}

int other_main(int hartid) {
    (void)hartid;
    while (1) {
        __asm__("wfi");
    }
}

int secondary_main(void) {
    int hartid = metal_cpu_get_current_hartid();
    if (hartid == 0) {
        return main();
    } else {
        return other_main(hartid);
    }
}
