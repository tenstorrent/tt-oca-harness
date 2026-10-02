/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_smc_notify - minimal SEP firmware for the SMU outbound egress-path test.
 *
 * Opens the outbound filter over the STDOUT mailbox, writes the two-word PASS
 * magic and then waits in WFI; the SMU-side test decides the verdict. This
 * test verifies the basic path from SEP CPU reset-vector execution through the
 * outbound filter and crossbar to the external AXI output.
 */

#include "sep_outbound_filter.h"
#include "test_completion.h"

int main(void) {
    sep_outbound_filter_init();

    test_pass(0);

    while (1) {
        __asm__ volatile("wfi");
    }
}
