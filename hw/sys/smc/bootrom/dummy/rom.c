/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "smc_io.h"
#include "smc_test.h"

/*
 * Lightweight SMC boot ROM.
 *
 * This ROM does not load or run any application itself. Its only job is to boot
 * cleanly from ROM (0xc0040000) and hand control back to the testbench: it
 * reports ROM-pass and then idles in wfi. The DV testbench then loads the real
 * firmware into SRAM over the SEP AXI master and re-pulses core reset with the
 * reset vector pointed at SRAM_BASE, so the cores re-boot into that image.
 */
int main(void) {
    /* Writes TEST_ROM_PASS (0x77777777) to scratch_0 so the testbench's
       init_and_reset() ROM-wait completes, then spins in wfi forever. */
    test_rom_pass(0);

    return 0;
}

/*
 * _exit stub so crt0/picolibc's exit() resolves at link time; never actually
 * reached since main() ends in a noreturn wfi.
 */
__attribute__((noreturn)) void _exit(int code) {
    (void)code;
    for (;;) asm volatile("wfi");
}
