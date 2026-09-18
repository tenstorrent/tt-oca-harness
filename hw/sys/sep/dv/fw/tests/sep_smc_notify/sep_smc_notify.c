/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smc_notify — minimal SEP firmware for SMC-SEP co-simulation boot test.
 *
 * This firmware is loaded into the SEP ICCM/DCCM via backdoor from the SMU
 * testbench when +define+SEP_RTL is asserted (i.e., smu_wrapper is compiled
 * with parameter SEP=1).
 *
 * Behaviour:
 *   1. Configure the outbound filter so the STDOUT mailbox (0x80000000) is
 *      reachable from the SEP AXI master port.
 *   2. Signal TEST_PASS to the testbench via the two-word magic sequence
 *      written to STDOUT.  The cocotb test monitors ext_out_awaddr /
 *      ext_out_wdata at the top level of the SMU testbench to detect this.
 *   3. Spin forever in WFI (the SMC cocotb test handles overall pass/fail).
 *
 * Spec basis: OCAH Specification §Crypto Key Manager — SEP must be able to
 * reach the outbound AXI fabric (smn_outbound_axi → smu_axi_out) to
 * communicate results/status.  This test verifies the basic path from SEP
 * CPU reset-vector execution through the outbound filter and crossbar to the
 * external AXI output.
 */

#include "sep_outbound_filter.h"
#include "test_completion.h"

int main(void) {
    /* Allow access to the testbench mailbox at 0x80000000. */
    sep_outbound_filter_init();

    /* Signal test pass — two 32-bit writes to STDOUT (0x80000000). */
    test_pass(0);

    /* Unreachable — test_pass() spins in WFI. */
    while (1) {
        __asm__ volatile("wfi");
    }
    return 0;
}
