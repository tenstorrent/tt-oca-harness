/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "smc_defines.h"
#include "smc_stackless_test.h" /* common: SMC_STACKLESS_ENTRY, SMC_WR32/RD32, SMC_WAIT_EQ */
#include "smc_sep_xbar_protocol.h"

/*
 * SEP_SMU_003  smc_sep_xbar  --  SMC (producer/consumer) firmware.
 *
 * Force-free SEP-driven bring-up: the real SEP CPU re-vectored + released these cores over
 * the SEP->SMC alias (no TB reset/vector force; the ext_in path is not used for CPU_CTRL
 * writes).
 * This SMC fw drives the fixed-alias bidirectional datapath handshake with the live SEP:
 * publish SMC_READY -> validate the SEP->SMC scratch8 word (final consumer) -> command the
 * SMC->SEP xbar channel (CMD/DONE) -> two-sided acknowledged completion -> TEST_PASS.
 *
 * STACKLESS (smc_stackless_test.h): the SEP-driven boot does not init the SMC SRAM stack, so
 * main() makes no function calls and uses only SMC_* absolute-MMIO/poll macros; any
 * `add sp,sp,-N` in main() wedges the core.
 */
SMC_STACKLESS_ENTRY(smc_sep_xbar_entry)

/* SMC-local scratch absolute addresses (CPU_CTRL array, 8-byte stride). */
#define SC0 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 0 * 8)   /* status (TEST_PASS/FAIL) */
#define SC1 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 1 * 8)   /* CLA arm token */
#define SC2 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 2 * 8)   /* SMC->SEP status */
#define SC8 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 8 * 8)   /* SEP->SMC data (0xC00390C0) */
#define SC12 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 12 * 8) /* SEP->SMC response */

/* SMC outbound egress filter for the SMC->SEP command channel (SEP cold scratch @0x10802000). */
#define SMC_OUTBOUND_FILTER_BASE 0x00000000C0016000ULL
#define FILTER_CONFIG_OFFSET 0x0ULL
#define FILTER_START_OFFSET 0x8ULL
#define FILTER_END_OFFSET 0x10ULL
/* allow_burst (bit24) CLEARED -> exact byte-granular END 0x1080203F (see axi_filter_wrap rounding).
 */
#define SMC_SEP_FILTER_CONFIG 0x0000000100030013ULL
#define SEP_SHARED_START 0x0000000010802000ULL
#define SEP_SHARED_END 0x000000001080203FULL

#define WAIT12(val, okvar) SMC_WAIT_EQ(SC12, (val), XBAR_FW_POLL_LIMIT, okvar)

int main(void) {
    uint32_t ok;

    /* S1: clear SMC-owned status/data/response scratch; verify zero. */
    SMC_WR32(SC0, 0u);
    SMC_WR32(SC2, 0u);
    SMC_WR32(SC8, 0u);
    SMC_WR32(SC12, 0u);
    SMC_FENCE();
    if (SMC_RD32(SC0) != 0u || SMC_RD32(SC2) != 0u || SMC_RD32(SC8) != 0u || SMC_RD32(SC12) != 0u)
        goto fail;

    /* S2 (setup): open the SMC outbound egress window over the SMC->SEP command channel, then
     * publish SMC_SETUP_OK on scratch0. The outbound-filter block is a write-only programming
     * interface (a CPU read of it would stall), so the exact filter values are verified DV-side by
     * a passive DUT read; SMC_SETUP_OK marks "filter programmed" for the ordered CHK-SETUP
     * evidence. */
    SMC_WR64(SMC_OUTBOUND_FILTER_BASE + FILTER_START_OFFSET, SEP_SHARED_START);
    SMC_WR64(SMC_OUTBOUND_FILTER_BASE + FILTER_END_OFFSET, SEP_SHARED_END);
    SMC_WR64(SMC_OUTBOUND_FILTER_BASE + FILTER_CONFIG_OFFSET, SMC_SEP_FILTER_CONFIG);
    SMC_FENCE();
    SMC_WR32(SC0, XBAR_SMC_SETUP_OK);
    SMC_FENCE();

    /* S3 (setup): publish SMC_READY, then read it back (scratch readback -- safe). Published BEFORE
     * the CLA release below, per the card's CHK-SETUP ordering (SMC_READY < CLA release edge). */
    SMC_WR32(SC2, XBAR_SMC_READY);
    SMC_FENCE();
    if (SMC_RD32(SC2) != XBAR_SMC_READY) goto fail;

    /* S4: CLA run release + arm token (satisfies the SV real-CLA liveness monitor); read back.
     * Ordered AFTER SMC_READY so the cla_ext_action_custom[1]/[4] release edge follows SMC_READY.
     */
    SMC_WR64(SMC_CLA_CDBGCLACTRLSTATUS_REG_ADDR, XBAR_CLA_CTRLSTATUS_EXPECT);
    SMC_WR64(SMC_CLA_CDBGNODE0EAP0_REG_ADDR, XBAR_CLA_EAP0_RELEASE);
    SMC_WR64(SMC_CLA_CDBGNODE0EAP1_REG_ADDR, XBAR_CLA_EAP1_RELEASE);
    SMC_WR32(SC1, XBAR_SMC_ARM_TOKEN);
    SMC_FENCE();
    if (SMC_RD64(SMC_CLA_CDBGNODE0EAP0_REG_ADDR) != XBAR_CLA_EAP0_RELEASE) goto fail;
    if (SMC_RD64(SMC_CLA_CDBGNODE0EAP1_REG_ADDR) != XBAR_CLA_EAP1_RELEASE) goto fail;

    /* S5: wait for SEP READY (SEP setup done + data published on scratch8). */
    WAIT12(XBAR_SEP_READY, ok);
    if (!ok) goto fail;

    /* S6: validate the SEP->SMC fixed-alias datapath word at scratch8 (final consumer read). */
    if (SMC_RD32(SC8) != XBAR_DATA_PATTERN) goto fail;
    SMC_WR32(SC2, XBAR_SMC_SCRATCH8_OK);
    SMC_FENCE();

    /* S7: publish CMD_SENT (CHK-BOTH-PASS ordering marker) BEFORE the CMD write, so it strictly
     * precedes the SEP observing CMD and racing its ACK out; then command the SMC->SEP xbar (SEP
     * cold scratch @0x10802000) and confirm reflect (CHK-SMC-TO-SEP cmd W/R). */
    SMC_WR32(SC0, XBAR_SMC_CMD_SENT);
    SMC_FENCE();
    SMC_WR32(XBAR_SEP_SHARED_ADDR, XBAR_SMC_TO_SEP_CMD);
    SMC_FENCE();
    if (SMC_RD32(XBAR_SEP_SHARED_ADDR) != XBAR_SMC_TO_SEP_CMD) goto fail;

    /* S8: wait for the SEP ACK (scratch12). */
    WAIT12(XBAR_SEP_TO_SMC_ACK, ok);
    if (!ok) goto fail;

    /* S9: publish DONE_SENT BEFORE the DONE write (same ordering reason), then DONE + reflect. */
    SMC_WR32(SC0, XBAR_SMC_DONE_SENT);
    SMC_FENCE();
    SMC_WR32(XBAR_SEP_SHARED_ADDR, XBAR_SMC_TO_SEP_DONE);
    SMC_FENCE();
    if (SMC_RD32(XBAR_SEP_SHARED_ADDR) != XBAR_SMC_TO_SEP_DONE) goto fail;

    /* S10: wait for SEP_PASS, then publish TEST_PASS. */
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
