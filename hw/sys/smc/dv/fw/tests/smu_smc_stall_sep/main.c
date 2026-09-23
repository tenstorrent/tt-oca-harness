/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "smc_defines.h"
#include "smc_stackless_test.h"
#include "smu_smc_stall_protocol.h"

/*
 * SEP_SMU_004  smu_smc_stall_sep  --  SMC (producer) firmware.
 *
 * Real SMC firmware drives the CLA halt/run control path to a live SEP CPU and
 * runs a scratch handshake proving the SEP is (a) live, (b) actively GO-polling,
 * (c) frozen by CLA halt while SMC keeps progressing, (d) resumed by CLA release
 * and able to finish an acknowledged completion protocol. No forces/deposits:
 * halt = CLA node0 EAP action[0] (mpc_debug_halt_req_i), release = actions [1]/[4].
 *
 * STACKLESS (smc_stackless_test.h): the SMU cocotb / SEP-driven boot does not
 * initialise the SMC SRAM stack, so main() makes no function calls and uses only
 * the SMC_* absolute-MMIO/delay/poll macros; any `add sp,sp,-N` in main hangs
 * the core.
 */
SMC_STACKLESS_ENTRY(smu_smc_stall_sep_entry)

/* SMC-local scratch absolute addresses (CPU_CTRL array, 8-byte stride). */
#define SC0 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 0 * 8) /* status  */
#define SC1 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 1 * 8) /* arm token */
#define SC2 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 2 * 8) /* cmd  SMC->SEP */
#define SC3 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 3 * 8) /* rsp  SEP->SMC */

/* Bounded poll of the SEP response channel (scratch3) for an exact value; ok=0
 * on timeout. */
#define WAIT_RSP(val, okvar) SMC_WAIT_EQ(SC3, (val), SMU_STALL_FW_POLL_LIMIT, okvar)

int main(void) {
    uint32_t ok;

    /* S1: clear SMC-owned status/cmd + SEP response channel; verify zero. */
    SMC_WR32(SC0, 0u);
    SMC_WR32(SC2, 0u);
    SMC_WR32(SC3, 0u);
    SMC_FENCE();
    if (SMC_RD32(SC0) != 0u || SMC_RD32(SC2) != 0u || SMC_RD32(SC3) != 0u) goto fail;

    /* S2: initial CLA run release (actions [1]/[4]) + arm token, then read back
     * exact CLA CSRs. The arm token in scratch1 satisfies the SV real-CLA
     * liveness monitor. */
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

    /* S3: wait for SEP READY (it gates on INIT_RELEASE_OK first). */
    WAIT_RSP(SMU_STALL_READY, ok);
    if (!ok) goto fail;

    /* S4: GO-poll-armed handshake -- PROBE then wait POLL_ARMED. */
    SMC_WR32(SC2, SMU_STALL_PROBE);
    SMC_FENCE();
    WAIT_RSP(SMU_STALL_POLL_ARMED, ok);
    if (!ok) goto fail;

    /* S5: program CLA halt (action[0] mpc_debug_halt_req_i) only after POLL_ARMED;
     * read back every halt-phase CLA CSR before publishing HALT_OK. */
    SMC_WR64(SMC_CLA_CDBGCLACTRLSTATUS_REG_ADDR, SMU_STALL_CLA_CTRLSTATUS_EXPECT);
    SMC_WR64(SMC_CLA_CDBGNODE0EAP0_REG_ADDR, SMU_STALL_CLA_EAP0_HALT);
    SMC_WR64(SMC_CLA_CDBGNODE0EAP1_REG_ADDR, SMU_STALL_CLA_EAP1_HALT);
    SMC_FENCE();
    if (SMC_RD64(SMC_CLA_CDBGCLACTRLSTATUS_REG_ADDR) != SMU_STALL_CLA_CTRLSTATUS_EXPECT) goto fail;
    if (SMC_RD64(SMC_CLA_CDBGNODE0EAP0_REG_ADDR) != SMU_STALL_CLA_EAP0_HALT) goto fail;
    if (SMC_RD64(SMC_CLA_CDBGNODE0EAP1_REG_ADDR) != SMU_STALL_CLA_EAP1_HALT) goto fail;
    SMC_WR32(SC0, SMU_STALL_HALT_OK);
    SMC_FENCE();

    /* let the CLA debug-halt settle at the SEP core before publishing GO */
    SMC_DELAY_ITERS(SMU_STALL_HALT_SETTLE_ITERS);

    /* S6: with halt active, publish GO (overwriting PROBE), hold, then HELD_OK. */
    SMC_WR32(SC2, SMU_STALL_GO);
    SMC_FENCE();
    SMC_DELAY_ITERS(SMU_STALL_HELD_HOLD_ITERS);
    SMC_WR32(SC0, SMU_STALL_HELD_OK);
    SMC_FENCE();

    /* S8: release CLA run actions [1]/[4]; SEP resumes and consumes GO. */
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

    /* S9: acknowledged completion protocol -> COMPLETION, ACK, PASS, TEST_PASS. */
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
