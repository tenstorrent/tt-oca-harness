// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// SMC firmware that marks SEP bring-up ready for the OSS wrapper smoke.
//
// Aligns with OCCP smu_sep_smoke (SEP_SMU_001): SEP default-runs when
// cla_ext_action_custom[2]==0 -> mpc_reset_run_req_i==1. Do NOT assert CLA
// custom actions {1,4} here — holding those as levels across SEP reset
// release leaves EL2 with halt_status=X and zero boot-ROM fetches.

#include <stdint.h>

#define SMC_SCRATCH0_ADDR ((uintptr_t)0xC0039080u)
#define SMC_TEST_PASS 0xACAFACA1u

int main(void) {
    *((volatile uint32_t *)SMC_SCRATCH0_ADDR) = SMC_TEST_PASS;
    for (;;) {
        __asm__ volatile("wfi");
    }
}
