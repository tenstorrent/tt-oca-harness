/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * OCCP Interface Unlatch Test
 *
 * Goal: Verify that after latching to one interface on a valid command, the ROM
 * unlatches when a threshold of invalid commands are received on the latched
 * interface, and then accepts a valid command on another interface.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
/* smc_top_regs.h is not included: the dv_rom build force-includes I3C shims whose
 * types collide with it. SMC_STRAP_STATUS_RPT_DISABLE comes from smc_strap.h. */
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

/* Send one randomized invalid OCCP operation to help trigger unlatch.
 * Error types covered:
 *  - Header CRC error (detectable or CRC-field corrupt)
 *  - Body CRC error (detectable or CRC-field corrupt)
 *  - Unaligned access (READ/WRITE)
 *  - Address outside SRAM range (READ/WRITE)
 *  - Zero-length READ/WRITE
 */
static int send_random_invalid_for_unlatch(test_context_t *ctx) {
    int which = (int)(get_random_int() % 13);
    int rc = OCCP_ERR;
    uint32_t tmp32 = 0;

    /* Default: no injections */
    ctx->header_crc_err_inject_mode = OCCP_CRC_INJECT_NONE;
    ctx->body_crc_err_inject_mode = OCCP_CRC_INJECT_NONE;
    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INJECT_NONE;
    ctx->exp_response_code = OCCP_ERROR_NONE;

    uint64_t base = ctx->test_base_addr;
    uint64_t upper = OCCP_TEST_UPPER_ADDR;
    uint64_t range = (upper > base) ? (upper - base) : 0;

    switch (which) {
    case 0: /* Header CRC error (detectable) */
        simputs("Injecting Header CRC error (detectable)\n");
        ctx->header_crc_err_inject_mode = OCCP_CRC_INJECT_DETECTABLE;
        /* Expect ROM to return CORRUPT_HEADER; API treats that as success when injection set */
        execute_random_commands(ctx, 1);
        rc = OCCP_SUCCESS;
        break;
    case 1: /* Header CRC error (corrupt CRC field) */
        simputs("Injecting Header CRC error (corrupt CRC field)\n");
        ctx->header_crc_err_inject_mode = OCCP_CORRUPT_CRC;
        execute_random_commands(ctx, 1);
        rc = OCCP_SUCCESS;
        break;
    case 2: /* Body CRC error (detectable) */
        simputs("Injecting Body CRC error (detectable)\n");
        ctx->body_crc_err_inject_mode = OCCP_CRC_INJECT_DETECTABLE;
        /* Use a GET_* command with a small body */
        execute_random_commands(ctx, 1);
        rc = OCCP_SUCCESS;
        break;
    case 3: /* Body CRC error (corrupt CRC field) */
        simputs("Injecting Body CRC error (corrupt CRC field)\n");
        ctx->body_crc_err_inject_mode = OCCP_CORRUPT_CRC;
        execute_random_commands(ctx, 1);
        rc = OCCP_SUCCESS;
        break;
    case 4: /* Unaligned access (READ/WRITE) */
        simputs("Injecting Unaligned access (READ/WRITE)\n");
        {
            bool do_write = ((get_random_int() % 2) == 0);
            /* Create an address within [base, upper) but not 4-byte aligned */
            uint16_t len = do_write ? get_random_occp_write_size() : get_random_occp_read_size();
            uint64_t addr = base + (get_random_int() % (range - len + 1)) & 0xfffffffffffffffc;
            // make it not 4-byte aligned
            addr += ((get_random_int() % 3) + 1);
            ctx->exp_response_code = OCCP_INVALID_ADDRESS;
            if (do_write) {
                static uint8_t wbuf[MAX_OCCP_WRITE_SIZE];
                for (uint16_t i = 0; i < len; i++) wbuf[i] = (uint8_t)(get_random_int() & 0xFF);
                rc = occp_send_write_command(ctx, ctx->slave_addr, addr, wbuf, len);
            } else {
                static uint8_t rbuf[MAX_OCCP_READ_SIZE];
                rc = occp_send_read_command(ctx, ctx->slave_addr, addr, rbuf, len);
            }
            ctx->exp_response_code = OCCP_ERROR_NONE;
            increment_cmd_count(ctx);
            break;
        }
    case 5: /* Address outside SRAM (READ/WRITE) */
    {
        simputs("Injecting Address outside SRAM range (READ/WRITE)\n");
        bool do_write = ((get_random_int() % 2) == 0);
        uint16_t len = do_write ? get_random_occp_write_size() : get_random_occp_read_size();
        /* Pick an address clearly outside the SRAM test window: above upper bound */
        uint64_t addr;
        if (is_secure_mode()) {
            uint8_t is_above = get_random_int() % 2;
            if (is_above) {
                addr = (upper + (get_random_int() % 0x100) + 1) & ~3ULL;
            } else {
                addr = (base - (get_random_int() % 0x10000) - 1) & ~3ULL;
            }
        } else {
            addr = (0xc0060000 + (get_random_int() % 0x5fff)) & ~3ULL;
        }
        ctx->exp_response_code = OCCP_INVALID_ADDRESS;
        if (do_write) {
            static uint8_t wbuf[MAX_OCCP_WRITE_SIZE];
            for (uint16_t i = 0; i < len; i++) wbuf[i] = (uint8_t)(get_random_int() & 0xFF);
            rc = occp_send_write_command(ctx, ctx->slave_addr, addr, wbuf, len);
        } else {
            static uint8_t rbuf[MAX_OCCP_READ_SIZE];
            rc = occp_send_read_command(ctx, ctx->slave_addr, addr, rbuf, len);
        }
        ctx->exp_response_code = OCCP_ERROR_NONE;
        increment_cmd_count(ctx);
        break;
    }
    case 6: /* Zero-length READ/WRITE */
    {
        simputs("Injecting Zero-length READ/WRITE\n");
        bool do_write = ((get_random_int() % 2) == 0);
        uint64_t addr = base + (get_random_int() % (range - 1 + 1)) & 0xfffffffffffffffc;
        ctx->exp_response_code = OCCP_INVALID_HEADER;
        if (do_write) {
            uint8_t dummy = 0;
            rc = occp_send_write_command(ctx, ctx->slave_addr, addr, &dummy, 0);
        } else {
            uint8_t rbuf[1] = {0};
            rc = occp_send_read_command(ctx, ctx->slave_addr, addr, rbuf, 0);
        }
        ctx->exp_response_code = OCCP_ERROR_NONE;
        increment_cmd_count(ctx);
        break;
    }
    case 7: // oversize body
        simputs("Injecting Oversize body\n");
        ctx->inject_oversize_body_err = true;
        ctx->exp_response_code = OCCP_OVERSIZE_MSG;
        execute_random_commands(ctx, 1);
        rc = OCCP_SUCCESS;
        ctx->inject_oversize_body_err = false;
        ctx->exp_response_code = OCCP_ERROR_NONE;
        break;
    case 8: // undersize body
        simputs("Injecting Undersize body\n");
        ctx->inject_undersize_body_err = true;
        ctx->exp_response_code = OCCP_INCOMPLETE_MSG;
        execute_random_commands(ctx, 1);
        rc = OCCP_SUCCESS;
        ctx->inject_undersize_body_err = false;
        ctx->exp_response_code = OCCP_ERROR_NONE;
        break;
    case 9: // undersize header
        simputs("Injecting Undersize header\n");
        ctx->inject_undersize_header_err = true;
        ctx->exp_response_code = OCCP_INCOMPLETE_MSG;
        execute_random_commands(ctx, 1);
        rc = OCCP_SUCCESS;
        ctx->inject_undersize_header_err = false;
        ctx->exp_response_code = OCCP_ERROR_NONE;
        break;
    case 10: // invalid command
        simputs("Injecting Invalid command\n");
        int injection_mode = get_random_int() % 3;
        switch (injection_mode) {
        case 0:
            ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INVALID_MSGID;
            break;
        case 1:
            ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INVALID_APPID;
            break;
        case 2:
            ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INVALID_BOTH;
            break;
        }
        execute_random_commands(ctx, 1);
        rc = OCCP_SUCCESS;
        ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INJECT_NONE;
        ctx->exp_response_code = OCCP_ERROR_NONE;
        break;
    case 11: // invalid length field
        simputs("Injecting Invalid length field\n");
        ctx->invalid_len_err_inject_enable = true;
        execute_random_commands(ctx, 1);
        rc = OCCP_SUCCESS;
        ctx->invalid_len_err_inject_enable = false;
        break;
    case 12: // unsupported status ID
        simputs("Injecting Unsupported status ID\n");
        ctx->unsupported_status_id_inject_enable = true;
        ctx->exp_response_code = OCCP_UNSUPPORTED_STATUS;
        uint32_t status = 0;
        rc = occp_send_get_occp_boot_status_command(ctx, ctx->slave_addr, &status);
        ctx->unsupported_status_id_inject_enable = false;
        ctx->exp_response_code = OCCP_ERROR_NONE;
        increment_cmd_count(ctx);
        break;
    default:
        rc = OCCP_ERR;
        break;
    }

    /* Reset injections to keep later commands clean */
    ctx->header_crc_err_inject_mode = OCCP_CRC_INJECT_NONE;
    ctx->body_crc_err_inject_mode = OCCP_CRC_INJECT_NONE;
    ctx->invalid_header_inject_mode = OCCP_INVALID_HDR_INJECT_NONE;

    return rc;
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

    simputs("=== OCCP Interface Unlatch Test ===\n");

    /* Wait for target up (GPIO) before transacting */
    simputs("Waiting for target to be ready...\n");
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

    /* 1) Latch on ifaceA with valid commands */
    int num_initial_commands = (get_random_int() % 2) ? (1) : ((get_random_int() % 5) + 1);
    simputs("Step 1: Send valid commands on ifaceA to trigger latch\n");
    execute_random_commands(&ctxA, 1);

    /* 2) Send 5 invalid commands on ifaceA to trigger unlatch */
    simputs("Step 2: Send randomized invalid commands on ifaceA to force unlatch\n");
    for (int i = 0; i < 5; i++) {
        int rc = send_random_invalid_for_unlatch(&ctxA);
        if (rc != OCCP_SUCCESS) {
            simputs("Invalid command send failed\n");
            ctxA.overall_result = false;
        }
    }

    ctxB.exp_occp_last_error = ctxA.exp_occp_last_error;
    ctxB.cmd_count = ctxA.cmd_count;
    /* 3) Attempt command on ifaceB - should succeed if unlatch happened */
    simputs("Step 3: Send random commands on ifaceB to confirm unlatch\n");
    execute_random_commands(&ctxB, 1);

    /* 4) relatch to A */
    simputs("Step 4: Relatch to ifaceA\n");
    for (int i = 0; i < 5; i++) {
        int rc = send_random_invalid_for_unlatch(&ctxB);
        if (rc != OCCP_SUCCESS) {
            simputs("Invalid command send failed\n");
            ctxA.overall_result = false;
        }
    }

    ctxA.exp_occp_last_error = ctxB.exp_occp_last_error;
    ctxA.cmd_count = ctxB.cmd_count;
    simputs("Step 5: Send random commands on ifaceA to confirm relatch\n");
    execute_random_commands(&ctxA, 1);

    if (ctxA.overall_result && ctxB.overall_result) {
        simputs("\nOCCP INTERFACE UNLATCH TEST PASSED!\n");
        test_pass(0);
    } else {
        simputs("\nOCCP INTERFACE UNLATCH TEST FAILED!\n");
        test_fail(0);
    }

    simputs("Done\n");
    while (1) {
        __asm__("wfi");
    }
    return 0;
}
