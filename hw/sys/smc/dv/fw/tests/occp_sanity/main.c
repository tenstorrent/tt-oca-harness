/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OCCP Master Sanity Test - transport bring-up and GET_VERSION
 *
 * What this test proves, and nothing beyond it:
 *
 *   1. The master BFM brings up the OCCP transport that the BOOT_I2C strap
 *      selects (I2C, or I3C with ENTDAA assigning the target its dynamic
 *      address) and the DUT raises the target-ready GPIO.
 *   2. The DUT ROM answers one OCCP GET_VERSION with the version its
 *      specification fixes for it (see OCCP_EXPECTED_VERSION below).
 *   3. The verdict reaches the DUT over that same transport: it is carried by
 *      a real OCCP WRITE to the DUT's SCRATCH[0], and the write's return value
 *      is checked rather than discarded.
 *
 * It issues no OCCP READ and writes no address other than the verdict
 * scratch, so a PASS here says nothing about OCCP memory access. That is the
 * job of smc_occp_register_access_test (OCCP write/readback against external
 * registers) and the smc_occp_random_command_test family (SRAM write/read
 * against a scoreboard).
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"
#include <string.h> // For memcpy

/*
 * Expected OCCP protocol version.
 *
 * Authoritative source: hw/sys/smc/bootrom/prod/doc/occp-protocol.adoc -- the
 * ROM implements version 1.0.0 of the Base and Boot applications (line 9), and
 * the GetVersion response body carries major at byte 0, minor at byte 1 and
 * patch at bytes 2-3 (response-body table, lines 136-142). Little-endian
 * 1.0.0 is therefore 0x00000001.
 *
 * occp_commands.c:1775-1779 assembles the same value from
 * exp_occp_version_{major,minor,patch} = 1/0/0; it is named and sourced here so
 * a ROM version bump has one place to look in this test.
 */
#define OCCP_EXPECTED_VERSION 0x00000001u

/*
 * Left in `version` when GET_VERSION never delivers one, so no diagnostic can
 * print an indeterminate stack word as the "Actual" version received.
 */
#define OCCP_VERSION_NOT_RECEIVED 0xDEADBEEFu

/*
 * Bound for every OCCP wait in this test.
 *
 * ctx->timeout is a retry / poll *count*, not a time. Each receive loop in
 * occp_commands.c (241-261, and the same shape at 159-170 and 191-202) gates
 * on it:
 *
 *     bool timeout_enabled = ctx->timeout != 0;
 *     int  count = timeout_enabled ? ctx->timeout : 1;
 *     do { status = read(...); if (timeout_enabled) count--; }
 *     while ((count > 0) && (status != I3C_OK));
 *     if (count == 0) { return OCCP_TIMEOUT; }
 *
 * With ctx->timeout left at 0 -- which is all `static test_context_t
 * test_ctx = {0}` ever gave this test -- timeout_enabled is false, `count`
 * stays 1 and is never decremented, so a target that NACKs or never answers
 * spins in that do/while forever and the OCCP_TIMEOUT return underneath it is
 * unreachable. The run then ended only on the cocotb ROM_TEST_TIMEOUT (200 ms,
 * testlist_smc_chiplet.yaml smc_rom_test_template), a wall-clock expiry that
 * records nothing about which OCCP command stalled.
 *
 * Why 10000:
 *   - It equals I2C_DEFAULT_TIMEOUT (i2c_controller_driver.c:13), which is the
 *     bound the I2C *send* path was already applying while ctx->timeout was 0
 *     -- that path maps 0 to the default (line 545). Only the receive path
 *     reads 0 as "infinite poll" (line 626). So the send side keeps exactly
 *     the bound it had, and only the unbounded side gains one.
 *   - The I2C count is spent per byte-wait, not per transfer, and the I3C
 *     count is spent per read attempt, so a healthy exchange is nowhere near
 *     it: occp_interface_latch_test already treats 2000 as conclusive
 *     "the target is not answering" on this same bus, and this is 5x that.
 *
 * ctx->exp_timeout stays false: this test expects every command to be
 * answered, so a timeout must fail it, not satisfy it.
 */
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

/* Name the command that failed and how, so the kept log attributes the stall
 * instead of leaving the outer cocotb timeout as the only evidence. */
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
        /* `version` holds no received value on this path, so it is never
         * compared and never logged as "Actual". */
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
        /* The verdict write is the only thing that puts a result in front of
         * the testbench; a discarded return value makes a verdict that never
         * landed indistinguishable from a hang. */
        report_occp_failure("verdict OCCP WRITE to DUT SCRATCH[0]", retval);
        ctx->overall_result = false;
    }

    if (!ctx->overall_result) {
        /* Report the failure on the master BFM's own SCRATCH[0] as well.
         * monitor_test (smc_utils.py:339-401) polls bfm_scratch_0 next to the
         * DUT's scratch_0 and returns False as soon as either reads TEST_FAIL,
         * so this turns "the OCCP verdict never reached the DUT" from a 200 ms
         * ROM_TEST_TIMEOUT hang into an immediate, attributable FAIL.
         *
         * Deliberately one-sided: there is no matching test_pass(0). PASS must
         * keep travelling the real path -- the DUT's SCRATCH[0], written by an
         * OCCP WRITE the target actually executed and acknowledged. A local
         * test_pass() here would let the master declare success with the
         * target having answered nothing. */
        test_fail(0);
    }
}

int main(void) {
    static test_context_t test_ctx = {0};

    init_test(0);

    /* Arm the OCCP wait bound before any OCCP traffic. initialize_interface()
     * itself does not consume ctx->timeout -- the I2C/I3C bring-up carries its
     * own bounds -- but every occp_send_*_command() below does. */
    test_ctx.timeout = OCCP_SANITY_TIMEOUT;
    test_ctx.exp_timeout = false;

    if (!initialize_interface(&test_ctx)) {
        /* Was `return -1`, which left the testbench with nothing to observe
         * but the outer timeout. */
        simputs("FAIL: Interface initialization failed\n");
        test_fail(0);
    }

    // Run the test suite
    run_test_suite(&test_ctx);

    // Finalize and report results
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
