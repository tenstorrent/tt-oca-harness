/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Status Dump Test Module
 * 
 * Tests for ring buffer status dumping
 */

#include "occp_test_common.h"

bool run_status_dump_tests(test_context_t *ctx) {
  simputs("=== Ring Buffer Status Dump Tests ===\n");
  
  // Dump SMC ring buffer
  dump_ring_buffer_status(ctx, ctx->slave_addr, "SMC", occp_send_get_smc_status_command);
  
  // Dump SEP ring buffer  
  dump_ring_buffer_status(ctx, ctx->slave_addr, "SEP", occp_send_get_sep_status_command);
  
  // Status dump always succeeds - it's informational
  return true;
}
