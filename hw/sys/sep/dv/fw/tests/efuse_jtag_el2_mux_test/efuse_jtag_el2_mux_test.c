// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP eFuse JTAG-AXIL + EL2-CPU mux firmware test (OSS port of the reference suite
// sep_efuse_jtag_el2_cpu_mux_test, EL2 side). The EL2 CPU continuously issues
// eFuse-MMR read traffic through its host AXI path while, concurrently, the cocotb
// side drives the DUT's real SEP-OTP JTAG AXI-Lite port (axil_sep_otp_jtag). Both
// masters arbitrate at the eFuse interface controller's AXI-Lite mux
// (efuse_interface_controller.u_axi_lite_mux) -- this is the "el2_cpu_mux"
// coexistence the test proves.
//
// EL2 steps:
//   1. wait for real fuse-sense to complete (no +skip_fuse_sense);
//   2. publish CPU_READY to scratch-cold[0] so the cocotb side knows it may start
//      the JTAG burst;
//   3. loop forever, scoring two reads per pass so a path that returns nothing
//      cannot pass: RMA_SIP_TOKEN_I_0 must read its 0 reset value, and
//      EFUSE_INTERFACE_CTRL STATUS must still carry efuse_sense_done set. The
//      zero-expecting read alone is satisfied by a dead or zero-returning path;
//      the set status bit is the live control that makes the pair meaningful.
//      The CPU uses TOKEN_I_0, the JTAG side uses TOKEN_I_1/3/LAST, so they do
//      not overlap. Both are reads: the CPU issues no eFuse writes, so only the
//      read channel is contended. The loop counter and error count go to
//      scratch-cold so the observer can confirm the CPU keeps making progress
//      during the JTAG burst.
//
// The EL2 runs as a live worker. Coexistence is the loop counter advancing
// across the JTAG burst while the CPU-published error count stays zero.

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

int main(void) {
    sep_outbound_filter_init();
    sep_mbx_puts("SEP eFuse JTAG/EL2 mux test\n");

    // Real fuse sense must complete before the eFuse host path is usable.
    if (sep_efuse_wait_sense_done(SENSE_TIMEOUT) != 0) {
        sep_mbx_puts("FAIL: eFuse sense never completed\n");
        return 1;
    }
    sep_mbx_puts("CHK-SENSE PASS: eFuse sense-done\n");

    // Let the observer / JTAG side know the CPU is about to start its MMR loop.
    sep_scratch_wr(SCRATCH_ERR, 0);
    sep_scratch_wr(SCRATCH_READY, CPU_READY_MARKER);
    sep_scratch_wr(SCRATCH_COUNT, 0);

    uint32_t i = 0;
    uint32_t integ_err = 0;
    while (1) {
        // CPU eFuse-MMR traffic through the mux (TOKEN_I_0; JTAG uses 1/3/LAST).
        uint32_t rb = sep_efuse_rd(SEP_EFUSE_MMR0);
        if (rb != 0u) {
            integ_err++; // CPU path corrupted under contention
        }
        // Live control for the compare above. A mux that stops returning CPU
        // read data yields 0, which satisfies the 0-expecting check on its own;
        // requiring a bit that is set makes the pair fail on a dead path.
        uint32_t st = sep_efuse_rd(SEP_EFUSE_IFC_STATUS);
        if ((st & SEP_EFUSE_SENSE_DONE) == 0u) {
            integ_err++; // CPU read path dead or returning zeros under contention
        }
        // Publish progress (1..N) so the observer can prove the CPU advanced while
        // the JTAG burst ran.
        i++;
        sep_scratch_wr(SCRATCH_COUNT, i);
        sep_scratch_wr(SCRATCH_ERR, integ_err);
    }
}
