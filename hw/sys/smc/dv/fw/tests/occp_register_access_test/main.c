/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Writes random data to selected external SMC registers over OCCP WRITE and checks the
 * OCCP READ readback. Runs in non-secure mode only.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"

static bool write_readback_reg32(test_context_t *ctx, uint64_t addr, uint32_t data) {
    uint8_t wb[4];
    wb[0] = (uint8_t)(data & 0xFF);
    wb[1] = (uint8_t)((data >> 8) & 0xFF);
    wb[2] = (uint8_t)((data >> 16) & 0xFF);
    wb[3] = (uint8_t)((data >> 24) & 0xFF);

    int retval = occp_send_write_command(ctx, ctx->slave_addr, addr, wb, sizeof(wb));
    if (retval != OCCP_SUCCESS) {
        simputs("OCCP WRITE failed\n");
        return false;
    }

    uint8_t rb[4] = {0};
    retval = occp_send_read_command(ctx, ctx->slave_addr, addr, rb, sizeof(rb));
    if (retval != OCCP_SUCCESS) {
        simputs("OCCP READ failed\n");
        return false;
    }

    uint32_t rdata = (uint32_t)rb[0] | ((uint32_t)rb[1] << 8) | ((uint32_t)rb[2] << 16) |
                     ((uint32_t)rb[3] << 24);
    if (rdata != data) {
        simputs("READBACK MISMATCH\n");
        simputshex32("Expected: ", data);
        simputshex32("Actual: ", rdata);
        return false;
    }
    return true;
}

static bool write_readback_reg64(test_context_t *ctx, uint64_t addr, uint64_t data) {
    uint8_t wb[8];
    occp_write_le64(wb, data);

    int retval = occp_send_write_command(ctx, ctx->slave_addr, addr, wb, sizeof(wb));
    if (retval != OCCP_SUCCESS) {
        simputs("OCCP WRITE64 failed\n");
        return false;
    }

    uint8_t rb[8] = {0};
    retval = occp_send_read_command(ctx, ctx->slave_addr, addr, rb, sizeof(rb));
    if (retval != OCCP_SUCCESS) {
        simputs("OCCP READ64 failed\n");
        return false;
    }

    bool equal = true;
    for (int i = 0; i < 8; i++) {
        if (rb[i] != wb[i]) {
            equal = false;
        }
    }
    if (!equal) {
        uint64_t rdata = (uint64_t)rb[0] | ((uint64_t)rb[1] << 8) | ((uint64_t)rb[2] << 16) |
                         ((uint64_t)rb[3] << 24) | ((uint64_t)rb[4] << 32) |
                         ((uint64_t)rb[5] << 40) | ((uint64_t)rb[6] << 48) |
                         ((uint64_t)rb[7] << 56);
        simputs("READBACK64 MISMATCH\n");
        simputshex32("Expected hi: ", data >> 32);
        simputshex32("Actual hi: ", rdata >> 32);
        simputshex32("Expected lo: ", data & 0xFFFFFFFF);
        simputshex32("Actual lo: ", rdata & 0xFFFFFFFF);
        return false;
    }
    return true;
}

static void run_test_suite(test_context_t *ctx) {
    ctx->overall_result = true;

    if (is_secure_mode()) {
        simputs("Test requires non-secure mode\n");
        ctx->overall_result = false;
        return;
    }

    for (int i = 0; i < 4; i++) {
        uint64_t addr = SMC_CPU_CTRL_DUMMY_ROM_0_REG_ADDR + (uint64_t)(i * 8);
        uint64_t data =
            ((uint64_t)(uint32_t)get_random_int() << 32) | (uint64_t)(uint32_t)get_random_int();
        if (!write_readback_reg64(ctx, addr, data)) {
            ctx->overall_result = false;
        }
    }

    {
        uint64_t addr = SMC_CPU_CTRL_GLOBAL_BASE_REG_ADDR;
        uint64_t data =
            (((uint64_t)(uint32_t)get_random_int() << 32) | (uint64_t)(uint32_t)get_random_int()) &
            0xffffffffffffff;
        if (!write_readback_reg64(ctx, addr, data)) {
            ctx->overall_result = false;
        }
    }

    for (int i = 0; i < 8; i++) {
        uint64_t addr = SMC_MISC_WRAP_SCRATCH_COLD_REG_MAP_BASE_ADDR + (uint64_t)(i * 4);
        uint32_t data = (uint32_t)get_random_int();
        if (!write_readback_reg32(ctx, addr, data)) {
            ctx->overall_result = false;
        }
    }

    for (int i = 3; i < 8; i++) {
        uint64_t addr = SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + (uint64_t)(i * 8);
        uint32_t data = (uint32_t)get_random_int();
        if (!write_readback_reg32(ctx, addr, data)) {
            ctx->overall_result = false;
        }
    }

    {
        uint64_t addr = SMC_RESET_UNIT_ISOLATE_REQ_FLR_COUNTER_VALUE_REG_ADDR;
        uint32_t data = (uint32_t)get_random_int();
        if (!write_readback_reg32(ctx, addr, data)) {
            ctx->overall_result = false;
        }
    }
}

static void finalize_test_results(test_context_t *ctx) {
    uint32_t result_code;
    if (ctx->overall_result) {
        simputs("ALL TESTS PASSED!\n");
        result_code = SMC_SCRATCHPAD_SIM_PASS_CODE;
    } else {
        simputs("SOME TESTS FAILED!\n");
        result_code = SMC_SCRATCHPAD_SIM_FAIL_CODE;
        test_fail(0);
    }
    occp_send_write_command(ctx, ctx->slave_addr, SMC_CPU_CTRL_SCRATCH_0__REG_ADDR,
                            (uint8_t *)&result_code, sizeof(result_code));
}

int main(void) {
    static test_context_t test_ctx = {0};

    init_test(0);

    if (!initialize_interface(&test_ctx)) {
        simputs("FAIL: Interface initialization failed\n");
        return -1;
    }

    test_ctx.test_base_addr = OCCP_TEST_BASE_ADDR;
    test_ctx.test_upper_addr_bound = OCCP_TEST_BUFFER_SAFE_UPPER_ADDR;
    test_ctx.overall_result = true;
    test_ctx.cmd_count = 0;
    test_ctx.exp_occp_last_error = 0;
    test_ctx.sram_scoreboard_idx = 0;

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
