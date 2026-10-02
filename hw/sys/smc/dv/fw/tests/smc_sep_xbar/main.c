/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * SMC-SEP Crossbar Datapath Test (SMC side)
 *
 * Verifies the fixed-alias datapath between SMC and SEP in both directions
 * with a live SEP peer that follows smc_sep_xbar_protocol.h: the SMC checks
 * the data word the SEP delivers to an SMC scratch register, then sends a
 * command and a done word to the SEP shared scratch, each acknowledged by the
 * SEP.
 *
 * The SEP CPU vectors and releases these cores over the SEP-to-SMC alias, and
 * that boot does not initialize the SMC SRAM stack: main() makes no function
 * calls and uses only the smc_stackless_test.h macros, since any stack frame
 * in main() wedges the core. Only hart 0 runs main().
 */

#include <stdint.h>

#include "smc_defines.h"
#include "smc_stackless_test.h"
#include "smc_sep_xbar_protocol.h"

SMC_STACKLESS_ENTRY(smc_sep_xbar_entry)

#define SC0 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 0 * 8)   /* status (TEST_PASS/FAIL) */
#define SC1 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 1 * 8)   /* CLA arm token */
#define SC2 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 2 * 8)   /* SMC->SEP status */
#define SC8 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 8 * 8)   /* SEP->SMC data */
#define SC12 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 12 * 8) /* SEP->SMC response */

#define SMC_OUTBOUND_FILTER_BASE 0x00000000C0016000ULL
#define FILTER_CONFIG_OFFSET 0x0ULL
#define FILTER_START_OFFSET 0x8ULL
#define FILTER_END_OFFSET 0x10ULL
/* Bursts stay disabled so the window ends at SEP_SHARED_END instead of
 * rounding up to a 4 KB granule. */
#define SMC_SEP_FILTER_CONFIG 0x0000000100030013ULL
#define SEP_SHARED_START 0x0000000010802000ULL
#define SEP_SHARED_END 0x000000001080203FULL

#define WAIT12(val, okvar) SMC_WAIT_EQ(SC12, (val), XBAR_FW_POLL_LIMIT, okvar)

int main(void) {
    uint32_t ok;

    SMC_WR32(SC0, 0u);
    SMC_WR32(SC2, 0u);
    SMC_WR32(SC8, 0u);
    SMC_WR32(SC12, 0u);
    SMC_FENCE();
    if (SMC_RD32(SC0) != 0u || SMC_RD32(SC2) != 0u || SMC_RD32(SC8) != 0u || SMC_RD32(SC12) != 0u)
        goto fail;

    /* The filter is not read back: a CPU read of the filter block stalls. */
    SMC_WR64(SMC_OUTBOUND_FILTER_BASE + FILTER_START_OFFSET, SEP_SHARED_START);
    SMC_WR64(SMC_OUTBOUND_FILTER_BASE + FILTER_END_OFFSET, SEP_SHARED_END);
    SMC_WR64(SMC_OUTBOUND_FILTER_BASE + FILTER_CONFIG_OFFSET, SMC_SEP_FILTER_CONFIG);
    SMC_FENCE();
    SMC_WR32(SC0, XBAR_SMC_SETUP_OK);
    SMC_FENCE();

    /* SMC_READY must be published before the CLA is released. */
    SMC_WR32(SC2, XBAR_SMC_READY);
    SMC_FENCE();
    if (SMC_RD32(SC2) != XBAR_SMC_READY) goto fail;

    SMC_WR64(SMC_CLA_CDBGCLACTRLSTATUS_REG_ADDR, XBAR_CLA_CTRLSTATUS_EXPECT);
    SMC_WR64(SMC_CLA_CDBGNODE0EAP0_REG_ADDR, XBAR_CLA_EAP0_RELEASE);
    SMC_WR64(SMC_CLA_CDBGNODE0EAP1_REG_ADDR, XBAR_CLA_EAP1_RELEASE);
    SMC_WR32(SC1, XBAR_SMC_ARM_TOKEN);
    SMC_FENCE();
    if (SMC_RD64(SMC_CLA_CDBGNODE0EAP0_REG_ADDR) != XBAR_CLA_EAP0_RELEASE) goto fail;
    if (SMC_RD64(SMC_CLA_CDBGNODE0EAP1_REG_ADDR) != XBAR_CLA_EAP1_RELEASE) goto fail;

    /* SEP READY also means the data word is in place. */
    WAIT12(XBAR_SEP_READY, ok);
    if (!ok) goto fail;

    if (SMC_RD32(SC8) != XBAR_DATA_PATTERN) goto fail;
    SMC_WR32(SC2, XBAR_SMC_SCRATCH8_OK);
    SMC_FENCE();

    /* CMD_SENT goes out before the command, because the SEP can acknowledge
     * as soon as it sees the command. */
    SMC_WR32(SC0, XBAR_SMC_CMD_SENT);
    SMC_FENCE();
    SMC_WR32(XBAR_SEP_SHARED_ADDR, XBAR_SMC_TO_SEP_CMD);
    SMC_FENCE();
    if (SMC_RD32(XBAR_SEP_SHARED_ADDR) != XBAR_SMC_TO_SEP_CMD) goto fail;

    WAIT12(XBAR_SEP_TO_SMC_ACK, ok);
    if (!ok) goto fail;

    /* DONE_SENT goes out before the done word for the same reason. */
    SMC_WR32(SC0, XBAR_SMC_DONE_SENT);
    SMC_FENCE();
    SMC_WR32(XBAR_SEP_SHARED_ADDR, XBAR_SMC_TO_SEP_DONE);
    SMC_FENCE();
    if (SMC_RD32(XBAR_SEP_SHARED_ADDR) != XBAR_SMC_TO_SEP_DONE) goto fail;

    WAIT12(XBAR_SEP_PASS, ok);
    if (!ok) goto fail;
    SMC_WR32(SC0, XBAR_SMC_TEST_PASS);
    SMC_FENCE();
    for (;;) __asm__ volatile("wfi");

fail:
    SMC_WR32(SC0, XBAR_SMC_TEST_FAIL);
    SMC_FENCE();
    for (;;) __asm__ volatile("wfi");
}
