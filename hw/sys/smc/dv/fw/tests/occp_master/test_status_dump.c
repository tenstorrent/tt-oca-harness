/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Dumps the SMC and SEP status ring buffers over OCCP; never fails.
 */

#include "occp_test_common.h"

bool run_status_dump_tests(test_context_t *ctx) {
    simputs("=== Ring Buffer Status Dump Tests ===\n");

    dump_ring_buffer_status(ctx, ctx->slave_addr, "SMC", occp_send_get_smc_status_command);

    dump_ring_buffer_status(ctx, ctx->slave_addr, "SEP", occp_send_get_sep_status_command);

    return true;
}
