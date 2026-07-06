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

int secondary_main(void) {
  /* crt0 dispatches every hart here; all harts fall into the wfi idle above. */
  return main();
}

/*
 * Bare-metal _exit stub.
 *
 * crt0 (_enter) links against picolibc, whose exit() pulls in _exit as the
 * platform hook. tt-oca-hw satisfied this from libgloss; here we keep the ROM
 * self-contained and free of semihosting (which would trap the RTL sim) by
 * providing our own. It is never reached at runtime: main() ends in the
 * noreturn wfi of test_rom_pass(). It exists only so the ROM link resolves.
 */
__attribute__((noreturn)) void _exit(int code) {
  (void)code;
  for (;;) asm volatile("wfi");
}
