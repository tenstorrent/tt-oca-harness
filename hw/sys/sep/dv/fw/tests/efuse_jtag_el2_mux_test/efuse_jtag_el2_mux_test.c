// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP eFuse JTAG-AXIL and EL2-CPU mux coexistence test, CPU side. The CPU reads
// eFuse MMRs through its host AXI path while the testbench drives the SEP-OTP
// JTAG AXI-Lite port; both masters arbitrate at the eFuse interface
// controller's AXI-Lite mux.
//
// The CPU waits for fuse sense, seeds a resetless token word and reads it back,
// publishes CPU_READY, then loops. Each pass requires the token to keep the CPU
// seed and the interface status to keep sense-done set, so a read path that
// returns nothing cannot pass. The JTAG side uses other token words and the CPU
// issues no eFuse writes in the loop, so only the read channel is contended.
// Coexistence is the published loop counter advancing across the JTAG burst
// while the published error count stays zero.

#include <stdint.h>

#include "sep_outbound_filter.h"
#include "sep_mailbox.h"
#include "sep_efuse.h"
#include "sep_scratch_drv.h"

#define CPU_READY_MARKER 0xE9050001u
#define SCRATCH_READY 0u // scratch-cold[0]: CPU_READY
#define SCRATCH_COUNT 2u // scratch-cold[2]: loop counter
#define SCRATCH_ERR 3u   // scratch-cold[3]: CPU MMR read mismatch count
#define SENSE_TIMEOUT 200000
#define CPU_TOKEN_SEED 0x5A5A1000u

int main(void) {
    sep_outbound_filter_init();
    sep_mbx_puts("SEP eFuse JTAG/EL2 mux test\n");

    // Real fuse sense must complete before the eFuse host path is usable.
    if (sep_efuse_wait_sense_done(SENSE_TIMEOUT) != 0) {
        sep_mbx_puts("FAIL: eFuse sense never completed\n");
        return 1;
    }
    sep_mbx_puts("CHK-SENSE PASS: eFuse sense-done\n");

    // TOKEN_I storage has no reset, so write a defined CPU-side value before
    // using it as the corruption sentinel for the mux window.
    sep_efuse_wr(SEP_EFUSE_MMR0, CPU_TOKEN_SEED);
    if (sep_efuse_rd(SEP_EFUSE_MMR0) != CPU_TOKEN_SEED) {
        sep_mbx_puts("FAIL: CPU token seed did not read back\n");
        return 1;
    }
    sep_mbx_puts("CHK-CPU-SEED PASS: CPU token seed read back\n");

    // Let the observer / JTAG side know the CPU is about to start its MMR loop.
    sep_scratch_wr(SCRATCH_ERR, 0);
    sep_scratch_wr(SCRATCH_READY, CPU_READY_MARKER);
    sep_scratch_wr(SCRATCH_COUNT, 0);

    uint32_t i = 0;
    uint32_t integ_err = 0;
    while (1) {
        // CPU eFuse-MMR traffic through the mux; the JTAG side never uses this word.
        uint32_t rb = sep_efuse_rd(SEP_EFUSE_MMR0);
        if (rb != CPU_TOKEN_SEED) {
            integ_err++; // CPU path corrupted under contention
        }
        // Independent live control for the interface status path.
        uint32_t st = sep_efuse_rd(SEP_EFUSE_IFC_STATUS);
        if ((st & SEP_EFUSE_SENSE_DONE) == 0u) {
            integ_err++; // CPU read path dead or returning zeros under contention
        }
        // Publish progress so the observer can prove the CPU advanced while the
        // JTAG burst ran.
        i++;
        sep_scratch_wr(SCRATCH_COUNT, i);
        sep_scratch_wr(SCRATCH_ERR, integ_err);
    }
}
