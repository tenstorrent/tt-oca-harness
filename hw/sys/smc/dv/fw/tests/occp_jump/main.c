/*
 * OCCP Master Sanity Test - Simple Write and Readback
 *
 * This test performs a basic OCCP write to a known address,
 * then reads back the data and checks for correctness.
 *
 * The goal is to verify basic OCCP communication and memory access.
 */

#include "occp_test_common.h"
#include "smc_defines.h"
#include "smc_test.h"
#include <string.h> // For memcpy

static void run_test_suite(test_context_t *ctx) {
  simputs("=== Starting OCCP Jump Test ===\n");

  ctx->overall_result = true;
  int retval;

  // Execute 10 random OCCP commands before jump
  // simputs("=== Random OCCP Commands Test (10 commands) ===\n");
  // execute_random_commands(ctx, 10);

  simputs("=== Jump Command Test ===\n");

  // poll until binary loaded in slave and pointer in scratch 4
  uint32_t test_addr = 0;
  while (test_addr == 0) {
    retval = occp_send_read_command(ctx, ctx->slave_addr, SMC_CPU_CTRL_SCRATCH_4__REG_ADDR, (uint8_t *)&test_addr, sizeof(test_addr));
    if (retval != OCCP_SUCCESS) {
      simputs("Failed to read scratch 4\n");
    }
    simputshex32("Test address: ", test_addr);
  }

  // jump directly to the test address + 0x3e0 (0x3e0 is the offset to the main function)
  retval = occp_send_jump_command(ctx, ctx->slave_addr, test_addr + 0x3e0);
  if (retval != OCCP_SUCCESS) {
    simputs("Failed to jump to test address\n");
    ctx->overall_result = false;
    return;
  }
}

static void finalize_test_results(test_context_t *ctx) {
  uint32_t result_code;

  // do nothing if pass since we are polling on ROM to complete program, end test if fail
  if (ctx->overall_result) {
    simputs("Completed bfm test, waiting for ROM to complete!\n");
    //result_code = SMC_SCRATCHPAD_SIM_PASS_CODE;
  } else {
    simputs("BFM failed to jump to test address!\n");
    test_fail(0);
  }
  while(1) {
    __asm__("wfi");
  }
}

int main(void) {
  static test_context_t test_ctx = {0};

  init_test(0);

  if (!initialize_interface(&test_ctx)) {
    simputs("FAIL: Interface initialization failed\n");
    return -1;
  }

  // Set up test context
  test_ctx.test_base_addr = OCCP_TEST_BASE_ADDR;
  test_ctx.test_upper_addr_bound = OCCP_TEST_BUFFER_SAFE_UPPER_ADDR;
  test_ctx.overall_result = true;
  test_ctx.sram_scoreboard_idx = 0;
  test_ctx.cmd_count = 0;
  test_ctx.exp_occp_last_error = 0;

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
