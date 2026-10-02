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

    simputs("Writing to sram addy 0x1000\n");
    for (int i = 0; i < n_addr; i++) {
        write_reg(SMC_TOP_SPM_MEMORY_BASE_ADDR + addy + (i * 4), 0xdeadbeef);
    }

    // The pattern must be present so that a zero read later proves the zeroer cleared it
    for (int i = 0; i < n_addr; i++) {
        if (read_reg(SMC_TOP_SPM_MEMORY_BASE_ADDR + addy + (i * 4)) != 0xdeadbeef) {
            simputs("Write to sram failed\n");
            test_fail(0);
        }
    }

    simputs("Zeroer sanity test\n");
    int n_bytes = n_addr * 4;
    write64_reg(SMC_TOP_ZEROER_CTRL_SIZE_BASE_ADDR, n_bytes);
    write64_reg(SMC_TOP_ZEROER_CTRL_DEST_ADDR_BASE_ADDR, SMC_TOP_SPM_MEMORY_BASE_ADDR + addy);
    write64_reg(SMC_TOP_ZEROER_CTRL_CTRL_STATUS_BASE_ADDR, 0); // Any write starts the clear

    simputs("Waiting for zeroer to finish...\n");
    /* A zeroer that stays busy must fail the test, not hang it. The clear is a
     * few words long, so 200 polls is a wide margin. */
    uint64_t status = 0;
    uint32_t poll = 200u;
    do {
        status = read_reg_64(SMC_TOP_ZEROER_CTRL_CTRL_STATUS_BASE_ADDR);
        status = (status >> 32) & 0x1;
    } while (status != 0 && --poll != 0u);

    if (status != 0) {
        simputs("Zeroer never reported completion\n");
        test_fail(0);
    }

    simputs("Zeroer finished, checking sram\n");
    for (int i = 0; i < n_addr; i++) {
        if (read_reg(SMC_TOP_SPM_MEMORY_BASE_ADDR + addy + (i * 4)) != 0) {
            simputs("Zeroer failed, sram not zeroed\n");
            test_fail(0);
        }
    }

    test_pass(0);
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
}
