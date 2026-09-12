/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OCCP Interface Latch Test
 *
 * Verifies that ROM latches to the first interface that issues a valid OCCP command
 * and ignores commands from other interfaces thereafter.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
/* smc_top_regs.h is not included: the dv_rom build force-includes I3C shims whose
 * types collide with it. */
#include "smc_strap.h"

typedef enum { IFACE_I2C0 = 0, IFACE_I2C1 = 1 } iface_id_t;

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

static iface_id_t pick_distinct_iface(iface_id_t exclude) {
    while (1) {
        iface_id_t c = pick_random_iface();
        if (c != exclude) return c;
    }
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

    /* 1) Latch on ifaceA with a safe valid command */
    // 50/50 chance of 1 or random number of initial commands
    int num_initial_commands = (get_random_int() % 2) ? (1) : ((get_random_int() % 10) + 1);
    simputs("Step 1: Send valid commands on ifaceA to trigger latch\n");
    execute_random_commands(&ctxA, 1);

    ctxB.exp_timeout = true;
    ctxB.timeout = 2000;
    /* 2) Attempt to send commands on ifaceB which should be ignored */
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
        test_fail(0);
    }

    simputs("Done\n");
    while (1) {
        __asm__("wfi");
    }
    return 0;
}
