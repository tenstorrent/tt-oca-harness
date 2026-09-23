/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Verifies that the ROM latches to the first interface that issues a valid OCCP command and
 * ignores commands from other interfaces thereafter. Step 0 proves ifaceB answers before the
 * latch, so its later silence is the latch and not a dead link.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
/* Do not include smc_top_regs.h: its types collide with the dv_rom build's I3C shims. */
#include "smc_strap.h"

typedef enum { IFACE_I2C0 = 0, IFACE_I2C1 = 1 } iface_id_t;

/* ifaceB must stay silent for this many polls per byte; Step 0 proves it answers within it. */
#define OCCP_IFACE_B_RESP_BUDGET_ITERS 2000

/* Must be non-zero: a timeout of 0 polls forever and hides failures behind the sim timeout. */
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
    ctx->slave_addr = 0;
    return true;
}

static iface_id_t pick_random_iface(void) {
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

/* Derived, not redrawn: a redraw loop never ends when the LFSR seed is 0. */
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
    ctxA.status_reporting_disabled = smc_strap_is_set(SMC_STRAP_STATUS_RPT_DISABLE);
    ctxB.status_reporting_disabled = smc_strap_is_set(SMC_STRAP_STATUS_RPT_DISABLE);
    ctxA.timeout = OCCP_IFACE_A_BUDGET_ITERS;

    simputs("=== OCCP Interface Latch Test ===\n");

    simputs("Waiting for target to be ready...\n");
    {
        gpio_intf__DATA_CTRL_t gpio_control;
        gpio_control.w = read_gpio(58, 0x0u);
        gpio_control.f.interface_enable = 1;
        gpio_control.f.enable_rx_tx = 2;
        write_gpio(58, 0x0u, gpio_control.w);
        do {
            gpio_control.w = read_gpio(58, 0x0u);
        } while (gpio_control.f.pad2core == 0);
    }

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

    /* An invalid AppID is answered without latching, proving ifaceB is live before the latch. */
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
    /* The ROM counts rejected commands too, in one counter shared by all channels. */
    increment_cmd_count(&ctxB);
    ctxA.cmd_count = ctxB.cmd_count;
    /* The ROM error code is sticky until reset, so later GET_OCCP_ERROR_CODE reads expect 0x1. */
    ctxA.exp_occp_last_error = 0x1;
    ctxB.exp_occp_last_error = 0x1;

    int num_initial_commands = (get_random_int() % 2) ? (1) : ((get_random_int() % 10) + 1);
    simputshex32("Step 1: Send valid commands on ifaceA to trigger latch, count: ",
                 (uint32_t)num_initial_commands);
    execute_random_commands(&ctxA, num_initial_commands);

    ctxB.exp_timeout = true;
    ctxB.timeout = OCCP_IFACE_B_RESP_BUDGET_ITERS;
    simputs("Step 2: Send probe writes on ifaceB; expect to be ignored due to latch\n");
    execute_random_commands(&ctxB, 1);

    simputs("Step 3: Verify cmd_count unchanged on ifaceA after ifaceB attempts\n");
    if (!get_status_and_check_cmd_count(&ctxA, (uint8_t)ctxA.cmd_count)) {
        test_fail(0);
        while (1) {
            __asm__("wfi");
        }
    }
    increment_cmd_count(&ctxA);

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
