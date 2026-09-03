// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC ROM for smu_sep_ext_axi_test: hand control to the SMC half of the
// protocol, which lives in scratch RAM.
//
// The SMC-side firmware (hw/sys/smc/dv/fw/tests/smu_sep_ext_axi) is preloaded
// into SMC scratch RAM by the testbench (+smc_scratch_ram_hex) and its header
// says it expects "the SEP-driven / cocotb-backdoor boot" -- something has to
// vector the SMC core at its entry symbol, because nothing does so by default
// and the ROM otherwise just parks. hw/sys/smc/dv does that re-vectoring
// through CPU_CTRL RESET_VECTOR + a tile reset pulse (smc_cpu_vip_utils.py).
// That route is not available here: reaching those CSRs from outside means
// coming in through the SMC aperture, and the aperture is opened by the very
// firmware being started -- a cycle. This ROM already runs on the SMC core with
// full local access, so it simply jumps.
//
// The jump uses no stack. The target is stackless by design (its own comment:
// the backdoor boot does not init the SMC SRAM stack), so entering it from here
// must not leave a frame behind either -- hence a bare tail jump rather than a
// call.

#include <stdint.h>

#define SMC_SCRATCH0_ADDR ((uintptr_t)0xC0039080u)
#define SMC_TEST_PASS 0xACAFACA1u

// EXTAXI_SMC_ENTRY from hw/sys/sep/dv/fw/tests/common/smu_sep_ext_axi_protocol.h,
// where it is marked "RECONCILE vs built image". It cannot be taken from that
// header directly: this image is built by the SMU DV firmware builder, which
// does not carry the SEP test include paths. The sequence reconciles this value
// against smu_sep_ext_axi_smc_entry in the built .sram.sym, so a relink that
// moves the entry fails the test instead of silently jumping into the middle of
// an instruction.
#define EXTAXI_SMC_ENTRY 0xC00601B2u

int main(void) {
    // Keep the marker the other wrapper tests look for, so a run that dies
    // before the handoff is still distinguishable from one that never booted.
    *((volatile uint32_t *)SMC_SCRATCH0_ADDR) = SMC_TEST_PASS;
    __asm__ volatile("fence iorw, iorw" ::: "memory");

    // Make sure the store above has landed before control leaves the ROM: the
    // scratch-RAM image immediately reprogrammes apertures, and a marker still
    // in flight would be attributed to the wrong owner.
    __asm__ volatile("fence.i" ::: "memory");

    ((void (*)(void))(uintptr_t)EXTAXI_SMC_ENTRY)();

    // Not reached: the target parks in its own terminal loop.
    for (;;) {
        __asm__ volatile("wfi");
    }
}
