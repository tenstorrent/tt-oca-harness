/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "smc_defines.h"
#include "smc_stackless_test.h"
#include "smu_smc_stall_protocol.h"

/*
 * SMU SMC stall of SEP - SMC firmware.
 *
 * Checks that SMC firmware can halt and resume a live SEP CPU through the CLA
 * debug halt and run actions, with no forces or deposits. The SMC runs its half
 * of a scratch handshake from which the testbench checker sees the SEP live,
 * polling for GO, frozen while halted as the SMC keeps running, and able to
 * finish an acknowledged completion after release.
 *
 * The image is stackless: the boot flow that runs it does not initialise the
 * SMC stack, so main() makes no function calls and uses only the
 * smc_stackless_test.h macros.
 */
SMC_STACKLESS_ENTRY(smu_smc_stall_sep_entry)

/* SMC scratch registers used as handshake channels. */
#define SC0 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 0 * 8) /* status  */
#define SC1 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 1 * 8) /* arm token */
#define SC2 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 2 * 8) /* cmd  SMC->SEP */
#define SC3 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 3 * 8) /* rsp  SEP->SMC */

/* Bounded wait for an exact SEP response; okvar is 0 on timeout. */
#define WAIT_RSP(val, okvar) SMC_WAIT_EQ(SC3, (val), SMU_STALL_FW_POLL_LIMIT, okvar)

int main(void) {
    uint32_t ok;

    /* Start from clear SMC status, command and SEP response channels. */
    SMC_WR32(SC0, 0u);
    SMC_WR32(SC2, 0u);
    SMC_WR32(SC3, 0u);
    SMC_FENCE();
    if (SMC_RD32(SC0) != 0u || SMC_RD32(SC2) != 0u || SMC_RD32(SC3) != 0u) goto fail;

    /* Release the SEP to run, post the arm token, then check the CLA programming. */
    SMC_WR64(SMC_CLA_CDBGCLACTRLSTATUS_REG_ADDR, SMU_STALL_CLA_CTRLSTATUS_EXPECT);
    SMC_WR64(SMC_CLA_CDBGNODE0EAP0_REG_ADDR, SMU_STALL_CLA_EAP0_RELEASE);
    SMC_WR64(SMC_CLA_CDBGNODE0EAP1_REG_ADDR, SMU_STALL_CLA_EAP1_RELEASE);
    SMC_WR32(SC1, SMU_STALL_ARM_TOKEN);
    SMC_FENCE();
    if (SMC_RD64(SMC_CLA_CDBGCLACTRLSTATUS_REG_ADDR) != SMU_STALL_CLA_CTRLSTATUS_EXPECT) goto fail;
    if (SMC_RD64(SMC_CLA_CDBGNODE0EAP0_REG_ADDR) != SMU_STALL_CLA_EAP0_RELEASE) goto fail;
    if (SMC_RD64(SMC_CLA_CDBGNODE0EAP1_REG_ADDR) != SMU_STALL_CLA_EAP1_RELEASE) goto fail;
    SMC_WR32(SC0, SMU_STALL_INIT_RELEASE_OK);
    SMC_FENCE();

    /* The SEP reports READY only after it sees INIT_RELEASE_OK. */
    WAIT_RSP(SMU_STALL_READY, ok);
    if (!ok) goto fail;

    /* Confirm that the SEP is polling for GO before it is halted. */
    SMC_WR32(SC2, SMU_STALL_PROBE);
    SMC_FENCE();
    WAIT_RSP(SMU_STALL_POLL_ARMED, ok);
    if (!ok) goto fail;

    /* Halt the SEP and check the CLA programming before posting HALT_OK. */
    SMC_WR64(SMC_CLA_CDBGCLACTRLSTATUS_REG_ADDR, SMU_STALL_CLA_CTRLSTATUS_EXPECT);
    SMC_WR64(SMC_CLA_CDBGNODE0EAP0_REG_ADDR, SMU_STALL_CLA_EAP0_HALT);
    SMC_WR64(SMC_CLA_CDBGNODE0EAP1_REG_ADDR, SMU_STALL_CLA_EAP1_HALT);
    SMC_FENCE();
    if (SMC_RD64(SMC_CLA_CDBGCLACTRLSTATUS_REG_ADDR) != SMU_STALL_CLA_CTRLSTATUS_EXPECT) goto fail;
    if (SMC_RD64(SMC_CLA_CDBGNODE0EAP0_REG_ADDR) != SMU_STALL_CLA_EAP0_HALT) goto fail;
    if (SMC_RD64(SMC_CLA_CDBGNODE0EAP1_REG_ADDR) != SMU_STALL_CLA_EAP1_HALT) goto fail;
    SMC_WR32(SC0, SMU_STALL_HALT_OK);
    SMC_FENCE();

    /* Let the debug halt take effect at the SEP core before publishing GO. */
    SMC_DELAY_ITERS(SMU_STALL_HALT_SETTLE_ITERS);

    /* Publish GO while the SEP is halted and hold it for a fixed window. */
    SMC_WR32(SC2, SMU_STALL_GO);
    SMC_FENCE();
    SMC_DELAY_ITERS(SMU_STALL_HELD_HOLD_ITERS);
    SMC_WR32(SC0, SMU_STALL_HELD_OK);
    SMC_FENCE();

    /* Release the SEP; it resumes and consumes GO. */
    SMC_WR64(SMC_CLA_CDBGCLACTRLSTATUS_REG_ADDR, SMU_STALL_CLA_CTRLSTATUS_EXPECT);
    SMC_WR64(SMC_CLA_CDBGNODE0EAP0_REG_ADDR, SMU_STALL_CLA_EAP0_RELEASE);
    SMC_WR64(SMC_CLA_CDBGNODE0EAP1_REG_ADDR, SMU_STALL_CLA_EAP1_RELEASE);
    SMC_FENCE();
    if (SMC_RD64(SMC_CLA_CDBGNODE0EAP0_REG_ADDR) != SMU_STALL_CLA_EAP0_RELEASE) goto fail;
    if (SMC_RD64(SMC_CLA_CDBGNODE0EAP1_REG_ADDR) != SMU_STALL_CLA_EAP1_RELEASE) goto fail;
    WAIT_RSP(SMU_STALL_GO_SEEN, ok);
    if (!ok) goto fail;
    SMC_WR32(SC0, SMU_STALL_RELEASE_OK);
    SMC_FENCE();
    SMC_WR32(SC2, SMU_STALL_RELEASE_GATE);
    SMC_FENCE();

    /* Acknowledged completion: COMPLETION, ACK, then PASS. */
    WAIT_RSP(SMU_STALL_COMPLETION, ok);
    if (!ok) goto fail;
    SMC_WR32(SC2, SMU_STALL_ACK);
    SMC_FENCE();
    WAIT_RSP(SMU_STALL_PASS, ok);
    if (!ok) goto fail;

    SMC_WR32(SC0, SMU_STALL_TEST_PASS);
    SMC_FENCE();
    for (;;) __asm__ volatile("wfi");

fail:
    SMC_WR32(SC0, SMU_STALL_TEST_FAIL);
    SMC_FENCE();
    for (;;) __asm__ volatile("wfi");
}
