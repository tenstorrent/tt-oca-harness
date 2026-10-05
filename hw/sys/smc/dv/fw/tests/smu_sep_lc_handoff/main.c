/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "smc_defines.h"
#include "smc_stackless_test.h"
#include "sep_smu_lc_handoff_protocol.h"

/*
 * SMU lifecycle security handoff - SMC PVT arm firmware.
 *
 * Arms the PVT process-clock observation and clears the observation pad's
 * hardware override, then tells the SEP that PVT is enabled. The SEP cannot
 * reach the SMC PVT registers through its alias window, so the SMC does it.
 * The image is stackless: main() makes no function calls.
 */
SMC_STACKLESS_ENTRY(smu_sep_lc_handoff_entry)

__attribute__((naked, section(".text"), used)) void smu_sep_lc_handoff_smc_pass_loop(void) {
    __asm__ volatile("1:\n wfi\n j 1b\n");
}
__attribute__((naked, section(".text"), used)) void smu_sep_lc_handoff_smc_fail_loop(void) {
    __asm__ volatile("1:\n wfi\n j 1b\n");
}

int main(void) {
    uint32_t v;

    SMC_DELAY_ITERS(1024);

    SMC_WR32(LC_HANDOFF_PVT_PROCESS_CTRL, 1u);
    SMC_FENCE();
    v = SMC_RD32(LC_HANDOFF_PVT_PROCESS_CTRL);
    if ((v & 1u) == 0u) {
        goto fail;
    }

    SMC_WR32(LC_HANDOFF_PVT_REFCLK_LO, 0x100u);
    SMC_WR32(LC_HANDOFF_PVT_CLK_CNT_CTRL, 1u);
    SMC_FENCE();

    SMC_WR32(LC_HANDOFF_PVT_CLK_OBS_CTRL, LC_HANDOFF_PVT_OBS_DEFAULT | LC_HANDOFF_PVT_OBS_UPDATE);
    SMC_FENCE();
    SMC_WR32(LC_HANDOFF_PVT_CLK_OBS_CTRL,
             LC_HANDOFF_PVT_OBS_DEFAULT | LC_HANDOFF_PVT_OBS_UPDATE | LC_HANDOFF_PVT_OBS_ENABLE);
    SMC_FENCE();
    v = SMC_RD32(LC_HANDOFF_PVT_CLK_OBS_CTRL);
    if ((v & LC_HANDOFF_PVT_OBS_ENABLE) == 0u) {
        goto fail;
    }

    v = SMC_RD32(LC_HANDOFF_PVT_GPIO_CTRL);
    SMC_WR32(LC_HANDOFF_PVT_GPIO_CTRL, v & ~(1u << LC_HANDOFF_HW2_OVRD_BIT));
    SMC_FENCE();
    v = SMC_RD32(LC_HANDOFF_PVT_GPIO_CTRL);
    if ((v & (1u << LC_HANDOFF_HW2_OVRD_BIT)) != 0u) {
        goto fail;
    }

    SMC_WR32(LC_HANDOFF_SMC_SCRATCH2, LC_HANDOFF_PVT_EN);
    SMC_FENCE();
    __asm__ volatile("j smu_sep_lc_handoff_smc_pass_loop");

fail:
    SMC_WR32(LC_HANDOFF_SMC_SCRATCH9, LC_HANDOFF_SMC_FAIL);
    SMC_FENCE();
    __asm__ volatile("j smu_sep_lc_handoff_smc_fail_loop");
}
