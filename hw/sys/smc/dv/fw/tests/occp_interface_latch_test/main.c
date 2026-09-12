/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OCCP Interface Latch Test
 *
 * Verifies that ROM latches to the first interface that issues a valid OCCP command
 * and ignores commands from other interfaces thereafter.
 *
 * The conclusion rests on ifaceB going silent, so the test first has to earn the
 * right to read that silence: Step 0 requires ifaceB to answer a non-latching
 * command while the ROM is still unlatched. Without it, an ifaceB that never came
 * up on the DUT side would be silent for the wrong reason and this test would
 * pass on it.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
/* smc_top_regs.h is not included: the dv_rom build force-includes I3C shims whose
 * types collide with it. */
#include "smc_strap.h"

typedef enum { IFACE_I2C0 = 0, IFACE_I2C1 = 1 } iface_id_t;

/* Response budget for one OCCP round trip on ifaceB, in host polling iterations.
 * ctrlr_receive_data_w_timeout() spends this budget per received byte, so it is
 * the window inside which ifaceB must stay silent for Step 2 to call the latch
 * proven (i2c_controller_driver.c:606-626, wait_for_rx_level at 411-440).
 *
 * The number is not calibrated from the OCCP spec - it is calibrated in-run:
 * Step 0 below completes a real OCCP round trip on ifaceB under this exact
 * budget before anything latches. If the budget were too short to ever see a
 * response, Step 0 fails and the test never reaches the point of drawing a
 * conclusion from ifaceB's silence. */
#define OCCP_IFACE_B_RESP_BUDGET_ITERS 2000

/* Budget for ifaceA. ifaceA is never required to be silent, so this value is
 * not a discriminator of anything - it only has to be finite. timeout == 0
 * selects an infinite receive poll (i2c_controller_driver.c:624 and 411-427),
 * which turns an unresponsive ifaceA into an opaque outer simulation timeout
 * with none of this test's diagnostics. 10x the round trip budget demonstrated
 * on ifaceB in Step 0 is far above any real response latency, and it is also
 * above the driver's own I2C_DEFAULT_TIMEOUT of 10000 that every send in this
 * test already ran with while ctxA.timeout was 0 (i2c_controller_driver.c:545),
 * so it loosens the send path rather than tightening it. */
#define OCCP_IFACE_A_BUDGET_ITERS (10 * OCCP_IFACE_B_RESP_BUDGET_ITERS)

static void set_ctx_addr_bounds(test_context_t *ctx) {
    ctx->test_base_addr = OCCP_TEST_BASE_ADDR;
    ctx->test_upper_addr_bound = OCCP_TEST_BUFFER_SAFE_UPPER_ADDR;
}

static bool init_ctx_for_iface(test_context_t *ctx, iface_id_t iface) {
    simputshex32("init_ctx_for_iface: iface: ", iface);
    uint8_t controller = (iface == IFACE_I2C0) ? 0 : 1;
    I2C_Driver *drv = I2C_GetDriverInstance(controller);
    if (!drv) {
        simputs("FAIL: I2C_GetDriverInstance returned NULL\n");
        return false;
    }
    uint8_t i2c_addr =
        (controller == 0) ? (read_scratch(4) & 0x7F) : ((read_scratch(4) >> 8) & 0x7F);
    if (drv->init_i2c_ctrlr(drv, i2c_addr) != I2C_OK) {
        simputs("FAIL: I2C init failed\n");
        return false;
    }
    ctx->drv.i2c_drv = drv;
    ctx->type = DRIVER_TYPE_I2C;
    ctx->slave_addr = 0; // unused for I2C path
    return true;
}

static iface_id_t pick_random_iface(void) {
    /* Map random selection 0..1 to 2 I2C interfaces */
    uint32_t r = get_random_int() % 2;
    switch (r) {
    case 0:
        return IFACE_I2C0;
    case 1:
        return IFACE_I2C1;
    default:
        return IFACE_I2C0;
    }
}

/* Only two interfaces are in play, so the distinct one is determined, not drawn:
 * retrying pick_random_iface() until it differs never terminates when the LFSR
 * is stuck (a SCRATCH seed of 0 leaves _RANDOM_LFSR at 0, smc_test.h:138-143)
 * and adds no randomness that ifaceA has not already spent. */
static iface_id_t pick_distinct_iface(iface_id_t exclude) {
    return (exclude == IFACE_I2C0) ? IFACE_I2C1 : IFACE_I2C0;
}

static bool get_status_and_check_cmd_count(test_context_t *ctx, uint8_t expected_cmd_count) {
    uint32_t status_data = 0;
    int retval = occp_send_get_occp_command_count_command(ctx, ctx->slave_addr, &status_data);
    if (retval != OCCP_SUCCESS) {
        simputs("FAIL: GET_OCCP_COMMAND_COUNT failed\n");
        ctx->overall_result = false;
        return false;
    }
    /* GET_OCCP_COMMAND_COUNT returns the ROM status register bits [15:8] in the
     * low byte (occp.c:1028-1032, status ID 2); only the command count is
     * checked here. Interface and boot status are not on this path. */
    uint8_t actual_cmd_count = status_data & 0xFF;
    if (actual_cmd_count != expected_cmd_count) {
        simputshex16("FAIL: cmd_count mismatch after status, expected ", expected_cmd_count);
        simputshex16(", actual ", actual_cmd_count);
        simputs("\n");
        ctx->overall_result = false;
        return false;
    }
    return true;
}

int main(void) {
    static test_context_t ctxA = {0};
    static test_context_t ctxB = {0};

    init_test(0);

    /* Randomly pick two distinct interfaces from 2 I2C interfaces */
    iface_id_t ifaceA = pick_random_iface();
    simputshex32("ifaceA: ", ifaceA);
    iface_id_t ifaceB = pick_distinct_iface(ifaceA);
    simputshex32("ifaceB: ", ifaceB);

    ctxA.overall_result = true;
    ctxB.overall_result = true;
    ctxA.cmd_count = 0;
    ctxB.cmd_count = 0;
    ctxA.exp_occp_last_error = 0;
    ctxB.exp_occp_last_error = 0;
    set_ctx_addr_bounds(&ctxA);
    set_ctx_addr_bounds(&ctxB);
    /* Read the strap instead of relying on the entry's +FORCE_STATUS_REPORTING
     * plusarg to pin it to 0; the helpers pick and check commands differently
     * when status reporting is disabled. */
    ctxA.status_reporting_disabled = smc_strap_is_set(SMC_STRAP_STATUS_RPT_DISABLE);
    ctxB.status_reporting_disabled = smc_strap_is_set(SMC_STRAP_STATUS_RPT_DISABLE);
    /* Bounded so an unresponsive ifaceA is reported here rather than as an outer
     * simulation timeout with none of these diagnostics. */
    ctxA.timeout = OCCP_IFACE_A_BUDGET_ITERS;

    simputs("=== OCCP Interface Latch Test ===\n");

    /* Wait for target up (GPIO) before transacting */
    simputs("Waiting for target to be ready...\n");
    // Reuse the helper sequence from interface init: just poll the same GPIO
    {
        /* DATA_CTRL is at offset 0 of the GPIO interface register block. */
        gpio_intf__DATA_CTRL_t gpio_control;
        gpio_control.w = read_gpio(58, 0x0u);
        gpio_control.f.interface_enable = 1;
        gpio_control.f.enable_rx_tx = 2;
        write_gpio(58, 0x0u, gpio_control.w);
        do {
            gpio_control.w = read_gpio(58, 0x0u);
        } while (gpio_control.f.pad2core == 0);
    }

    /* Initialize both contexts */
    if (!init_ctx_for_iface(&ctxA, ifaceA)) {
        simputs("FAIL: init ifaceA\n");
        test_fail(0);
        while (1) {
            __asm__("wfi");
        }
    }
    if (!init_ctx_for_iface(&ctxB, ifaceB)) {
        simputs("FAIL: init ifaceB\n");
        test_fail(0);
        while (1) {
            __asm__("wfi");
        }
    }

    /* 0) Positive control for the negative observations in Steps 2 and 3.
     *
     * Everything this test concludes about the latch is drawn from ifaceB being
     * silent. Silence has a second cause: a DUT channel whose init_target failed
     * is silently never registered as an OCCP interface (the failure log in
     * smc_occp_init_i2c_channel, occp.c:1738-1754, is commented out) and answers
     * nothing for the whole run; an address or routing divergence on the ifaceB
     * link does the same. init_ctx_for_iface above cannot see either, because it
     * only checks that the host's own I2C controller accepted its configuration.
     * With ifaceA/ifaceB drawn at random, such a dead interface shows up as a
     * ~50% intermittent failure rather than a clean one.
     *
     * So, before anything latches, require ifaceB to answer. The ROM is unlatched
     * at this point and polls every registered channel (smc_occp_poll_channels,
     * occp.c:494-509), so a live ifaceB must respond and a dead one cannot.
     *
     * The control command carries an invalid AppID, which the ROM rejects with an
     * Invalid_Appid error response (occp.c:762-772) *without* latching: latching
     * happens only for an AppID of Base or Boot with a MsgID below the command
     * boundary (occp.c:686-690 and 722-725). The control therefore proves ifaceB
     * reaches the ROM and is answered on ifaceB, while leaving the latch unspent
     * for Step 1 to take. It runs under the same OCCP_IFACE_B_RESP_BUDGET_ITERS
     * that Step 2 later requires ifaceB to stay silent through, which is what
     * makes that budget a demonstrated bound rather than a magic number. */
    ctxB.timeout = OCCP_IFACE_B_RESP_BUDGET_ITERS;
    ctxB.exp_timeout = false;
    simputs("Step 0: Positive control - ifaceB must answer while the ROM is unlatched\n");
    ctxB.invalid_header_inject_mode = OCCP_INVALID_HDR_INVALID_APPID;
    int rc_control = occp_send_invalid_header_command(&ctxB, ctxB.slave_addr);
    ctxB.invalid_header_inject_mode = OCCP_INVALID_HDR_INJECT_NONE;
    if (rc_control != OCCP_SUCCESS) {
        simputs("FAIL: ifaceB did not answer the pre-latch control command\n");
        simputs("      ifaceB is not proven reachable, so its silence in Step 2 would prove "
                "nothing about the latch\n");
        simputshex32("      ifaceB: ", ifaceB);
        simputshex32("      rc: ", (uint32_t)rc_control);
        ctxB.overall_result = false;
        test_fail(0);
        while (1) {
            __asm__("wfi");
        }
    }
    simputs("Step 0: PASS - ifaceB answered before the latch\n");
    /* The ROM counts the rejected command like any other (occp_status_increment_
     * command_count runs on the error path too, occp.c:822), and that counter is
     * global across channels, so ifaceA's model has to start from ifaceB's. */
    increment_cmd_count(&ctxB);
    ctxA.cmd_count = ctxB.cmd_count;
    /* The ROM's error-code field is sticky - it is written on every failed command
     * and cleared only at occp_status_init (occp.c:792/810, smc_occp_status.c:41),
     * so it now reads OCCP_ERROR_INVALID_COMMAND (0x1, smc_occp_status.h:56) for
     * the rest of the run and every later GET_OCCP_ERROR_CODE must expect that. */
    ctxA.exp_occp_last_error = 0x1;
    ctxB.exp_occp_last_error = 0x1;

    /* 1) Latch on ifaceA with a safe valid command */
    // 50/50 chance of 1 or random number of initial commands
    int num_initial_commands = (get_random_int() % 2) ? (1) : ((get_random_int() % 10) + 1);
    simputshex32("Step 1: Send valid commands on ifaceA to trigger latch, count: ",
                 (uint32_t)num_initial_commands);
    execute_random_commands(&ctxA, num_initial_commands);

    ctxB.exp_timeout = true;
    ctxB.timeout = OCCP_IFACE_B_RESP_BUDGET_ITERS;
    /* 2) Attempt to send commands on ifaceB which should be ignored. Read against
     * Step 0: the same ifaceB answered inside this same budget moments ago, so a
     * timeout here is the latch and not a dead link. A response instead makes
     * occp_get_response_header return OCCP_ERR (occp_commands.c:273-276). */
    simputs("Step 2: Send probe writes on ifaceB; expect to be ignored due to latch\n");
    execute_random_commands(&ctxB, 1);

    /* 3) Re-read status on ifaceA and verify cmd_count unchanged */
    simputs("Step 3: Verify cmd_count unchanged on ifaceA after ifaceB attempts\n");
    if (!get_status_and_check_cmd_count(&ctxA, (uint8_t)ctxA.cmd_count)) {
        test_fail(0);
        while (1) {
            __asm__("wfi");
        }
    }
    /* Reflect second GET_STATUS consumed by ROM */
    increment_cmd_count(&ctxA);

    /* 4) Sanity: Send another GET_STATUS on ifaceA; cmd_count++ then verify */
    simputs("Step 4: Sanity check ifaceA remains responsive\n");
    execute_random_commands(&ctxA, 1);

    if (ctxA.overall_result && ctxB.overall_result) {
        simputs("\nOCCP INTERFACE LATCH TEST PASSED!\n");
        test_pass(0);
    } else {
        simputs("\nOCCP INTERFACE LATCH TEST FAILED!\n");
        simputshex32("  ifaceA (latched): ", ifaceA);
        simputshex32("  ifaceB (probed):  ", ifaceB);
        simputshex32("  ifaceA cmd_count model: ", (uint32_t)ctxA.cmd_count);
        simputshex32("  ifaceB cmd_count model: ", (uint32_t)ctxB.cmd_count);
        simputshex32("  ifaceA result: ", (uint32_t)ctxA.overall_result);
        simputshex32("  ifaceB result: ", (uint32_t)ctxB.overall_result);
        test_fail(0);
    }

    simputs("Done\n");
    while (1) {
        __asm__("wfi");
    }
    return 0;
}
