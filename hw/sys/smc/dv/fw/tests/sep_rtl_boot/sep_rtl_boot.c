/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * sep_rtl_boot — SMC firmware for the SMC-SEP co-simulation boot test.
 *
 * This firmware runs on the SMC CPU while the real SEP RTL (smu_wrapper with
 * SEP=1) boots and executes sep_smc_notify firmware in parallel.  The TB's
 * cocotb test layer monitors both sides independently:
 *
 *   • SMC side : scratch[0] == TEST_PASS  (this firmware)
 *   • SEP side : ext_out_awaddr == 0x80000000 + TEST_MAGIC_PASS written
 *                via the SEP outbound AXI path
 *
 * The SMC firmware simply signals pass immediately after booting.  The real
 * verification work is confirming that the SEP RTL can boot from TCM,
 * configure its outbound filter, and reach the external AXI fabric — all
 * while the SMC CPU is running normally.
 *
 * Spec basis: OCH §Crypto Key Manager — both SMC and SEP must operate
 * concurrently on their respective clocks.  Ensuring neither blocks the
 * other at boot validates the shared crossbar and reset-sequencing logic.
 */

#include <stdbool.h>
#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"

int main(void)
{
    test_pass(0);

    /* Unreachable — test_pass() never returns. */
    while (true) {
        __asm__ volatile("wfi");
    }
    return 0;
}
