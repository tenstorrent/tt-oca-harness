/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"
#include "virt_console.h"
#include "metal/cpu.h"

#define addy 0x1000
#define n_addr 0x8

int main(void) {

    // Write to sram addy 0x1000
    simputs("Writing to sram addy 0x1000\n");
    for (int i = 0; i < n_addr; i++) {
        write_reg(SMC_TOP_SPM_MEMORY_BASE_ADDR + addy + (i * 4), 0xdeadbeef);
    }

    // read to ensure write was successful
    for (int i = 0; i < n_addr; i++) {
        if (read_reg(SMC_TOP_SPM_MEMORY_BASE_ADDR + addy + (i * 4)) != 0xdeadbeef) {
            simputs("Write to sram failed\n");
            test_fail(0);
        }
    }

    simputs("Zeroer sanity test\n");
    // Zero out sram addy 0x1000 - 0x1008
    int n_bytes = n_addr * 4; // 4 bytes per word
    write64_reg(SMC_TOP_ZEROER_CTRL_SIZE_BASE_ADDR, n_bytes);
    write64_reg(SMC_TOP_ZEROER_CTRL_DEST_ADDR_BASE_ADDR, SMC_TOP_SPM_MEMORY_BASE_ADDR + addy);
    write64_reg(SMC_TOP_ZEROER_CTRL_CTRL_STATUS_BASE_ADDR, 0); // Start zeroer

    simputs("Waiting for zeroer to finish...\n");
    /* Wait for zeroer to finish.
     *
     * This poll had no bound. A zeroer that never dropped its busy bit hung
     * the hart until the harness killed the run, and a harness kill is not
     * this test declaring a failure -- so the test could not tell "the zeroer
     * completed" from "the zeroer never responded", which is exactly the
     * distinction the checks below depend on.
     *
     * The transfer here is n_addr words, and the loop body is a single 64-bit
     * register read, so completion is a handful of iterations. 200 leaves a
     * wide margin and still expires quickly enough to reach test_fail. */
    uint64_t status = 0;
    uint32_t poll = 200u;
    do {
        status = read_reg_64(SMC_TOP_ZEROER_CTRL_CTRL_STATUS_BASE_ADDR);
        // Get bit 32
        status = (status >> 32) & 0x1;
    } while (status != 0 && --poll != 0u);

    if (status != 0) {
        simputs("Zeroer never reported completion\n");
        test_fail(0);
    }

    simputs("Zeroer finished, checking sram\n");
    // Read sram addy 0x1000
    for (int i = 0; i < n_addr; i++) {
        if (read_reg(SMC_TOP_SPM_MEMORY_BASE_ADDR + addy + (i * 4)) != 0) {
            simputs("Zeroer failed, sram not zeroed\n");
            test_fail(0);
        }
    }

    test_pass(0);

    while (true) {
        __asm__("wfi");
    }

    return 0;
}

int secondary_main(void) {
    int hartid = metal_cpu_get_current_hartid();

    if (hartid == 0) {
        return main();
    }

    /* Harts 1-3 park here for the whole run; a `wfi` may return spuriously, so the
     * wait loops. */
    while (true) {
        __asm__("wfi");
    }

    return 0;
}
