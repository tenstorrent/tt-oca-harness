/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Issues random OCCP READs and WRITEs in the lowest and highest SCOREBOARD_SIZE bytes of the
 * test range and checks each READ against a scoreboard of earlier WRITEs.
 */

#include "occp_test_common.h"
#include <string.h>

#define SCOREBOARD_SIZE 256
#define NUM_RANDOM_COMMANDS 5

typedef struct {
    uint8_t lower_scoreboard[SCOREBOARD_SIZE];
    uint8_t upper_scoreboard[SCOREBOARD_SIZE];
} boundary_scoreboard_t;

static boundary_scoreboard_t scoreboard = {0};

static void update_scoreboard(uint64_t addr, uint8_t *data, uint16_t len, uint64_t lower_base,
                              uint64_t upper_base) {
    for (int i = 0; i < len; i++) {
        uint64_t byte_addr = addr + (uint64_t)i;
        if (byte_addr >= lower_base && byte_addr < (lower_base + SCOREBOARD_SIZE)) {
            uint32_t offset = (uint32_t)(byte_addr - lower_base);
            scoreboard.lower_scoreboard[offset] = data[i];
        } else if (byte_addr >= upper_base && byte_addr < (upper_base + SCOREBOARD_SIZE)) {
            uint32_t offset = (uint32_t)(byte_addr - upper_base);
            scoreboard.upper_scoreboard[offset] = data[i];
        }
    }
}

static bool verify_scoreboard(test_context_t *ctx, uint64_t addr, uint8_t *data, uint16_t len,
                              uint64_t lower_base, uint64_t upper_base) {
    for (int i = 0; i < len; i++) {
        uint64_t byte_addr = addr + i;

        if (byte_addr < lower_base || byte_addr >= (upper_base + SCOREBOARD_SIZE) ||
            ((byte_addr >= (lower_base + SCOREBOARD_SIZE)) && (byte_addr < (upper_base)))) {
            simputs("FAIL: Address out of scoreboard range\n");
            simputshex32("Address: 0x", (uint32_t)byte_addr);
            simputshex32("Lower base: 0x", (uint32_t)lower_base);
            simputshex32("Upper base: 0x", (uint32_t)upper_base);
            simputshex32("Scoreboard size: 0x", SCOREBOARD_SIZE);
            ctx->overall_result = false;
        }

        if (byte_addr >= lower_base && byte_addr < (lower_base + SCOREBOARD_SIZE)) {
            uint32_t offset = byte_addr - lower_base;
            if (scoreboard.lower_scoreboard[offset] != data[i]) {
                simputshex32("Data mismatch at lower offset 0x", offset);
                simputshex32("Expected: 0x", scoreboard.lower_scoreboard[offset]);
                simputshex32("Actual: 0x", data[i]);
                return false;
            }
        } else if (byte_addr >= upper_base && byte_addr < (upper_base + SCOREBOARD_SIZE)) {
            uint32_t offset = byte_addr - upper_base;
            if (scoreboard.upper_scoreboard[offset] != data[i]) {
                simputshex32("Data mismatch at upper offset 0x", offset);
                simputshex32("Expected: 0x", scoreboard.upper_scoreboard[offset]);
                simputshex32("Actual: 0x", data[i]);
                return false;
            }
        }
    }
    return true;
}

static void execute_random_boundary_commands(test_context_t *ctx, int num_commands) {
    uint64_t lower_base = ctx->test_base_addr;
    uint64_t upper_base = OCCP_TEST_UPPER_ADDR - SCOREBOARD_SIZE;

    simputs("=== Random Boundary Access with Scoreboarding ===\n");
    simputshex32("Lower scoreboard range: 0x", (uint32_t)lower_base);
    simputshex32(" to 0x", (uint32_t)(lower_base + SCOREBOARD_SIZE - 1));
    simputshex32("Upper scoreboard range: 0x", (uint32_t)upper_base);
    simputshex32(" to 0x", (uint32_t)(upper_base + SCOREBOARD_SIZE - 1));

    for (int i = 0; i < num_commands; i++) {
        bool target_lower = (get_random_int() % 2) == 0;
        uint64_t base_addr = target_lower ? lower_base : upper_base;

        uint32_t offset = get_random_int() % SCOREBOARD_SIZE;
        uint64_t target_addr = (base_addr + offset) & 0xfffffffc;

        bool is_read = get_random_int() % 2;

        if (is_read) {
            uint16_t len = get_random_int() % (MAX_OCCP_READ_SIZE - 1) + 1;
            len = (len % (SCOREBOARD_SIZE - offset)) + 1;

            uint8_t recv_data[MAX_OCCP_READ_SIZE];

            simputshex32("READ ", len);
            simputshex32(" bytes from 0x", (uint32_t)target_addr);
            simputs(target_lower ? " (lower)\n" : " (upper)\n");

            int retval = occp_send_read_command(ctx, ctx->slave_addr, target_addr, recv_data, len);
            if (retval == OCCP_SUCCESS) {
                if (verify_scoreboard(ctx, target_addr, recv_data, len, lower_base, upper_base)) {
                    simputs("READ: PASS (scoreboard verified)\n");
                } else {
                    simputs("READ: FAIL (scoreboard mismatch)\n");
                    ctx->overall_result = false;
                }
            } else {
                simputs("READ: FAIL (command failed)\n");
                ctx->overall_result = false;
            }
        } else {
            uint16_t len = get_random_int() % (MAX_OCCP_WRITE_SIZE - 1) + 1;
            len = (len % (SCOREBOARD_SIZE - offset)) + 1;

            uint8_t write_data[MAX_OCCP_WRITE_SIZE];

            for (int j = 0; j < len; j++) {
                write_data[j] = get_random_int() & 0xFF;
            }

            simputshex32("WRITE ", len);
            simputshex32(" bytes to 0x", (uint32_t)target_addr);
            simputs(target_lower ? " (lower)\n" : " (upper)\n");

            int retval =
                occp_send_write_command(ctx, ctx->slave_addr, target_addr, write_data, len);
            if (retval == OCCP_SUCCESS) {
                update_scoreboard(target_addr, write_data, len, lower_base, upper_base);
                simputs("WRITE: PASS (scoreboard updated)\n");
            } else {
                simputs("WRITE: FAIL (command failed)\n");
                ctx->overall_result = false;
            }
        }

        increment_cmd_count(ctx);
    }
}

static void run_test_suite(test_context_t *ctx) {
    simputs("=== Starting OCCP Memory Boundary Access Test with Scoreboarding ===\n");

    ctx->overall_result = true;

    execute_random_boundary_commands(ctx, NUM_RANDOM_COMMANDS);
}

static void finalize_test_results(test_context_t *ctx) {
    uint32_t result_code;

    if (ctx->overall_result) {
        simputs("ALL TESTS PASSED!\n");
        result_code = SMC_SCRATCHPAD_SIM_PASS_CODE;
        test_pass(0);
    } else {
        simputs("SOME TESTS FAILED!\n");
        result_code = SMC_SCRATCHPAD_SIM_FAIL_CODE;
        test_fail(0);
    }
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
    test_ctx.sram_scoreboard_idx = 0;
    test_ctx.cmd_count = 0;
    test_ctx.exp_occp_last_error = 0;

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
