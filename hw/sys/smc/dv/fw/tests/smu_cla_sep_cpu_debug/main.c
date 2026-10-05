/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "smc_defines.h"
#include "smc_stackless_test.h"
#include "smu_cla_sep_cpu_debug_protocol.h"

/*
 * SMU CLA to SEP CPU debug control: SMC producer firmware.
 *
 * Fires each CLA single custom action toward the running SEP CPU, reads it back
 * and publishes it, so the DV can check the mapped SEP control input. The
 * reset-run and unmapped actions are held until the DV has applied a core
 * reset edge. Stackless: main() makes no function calls.
 */
SMC_STACKLESS_ENTRY(smu_cla_sep_cpu_debug_entry)

#define SC0 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 0 * 8)
#define SC1 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 1 * 8)
#define SC2 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 2 * 8)
#define SC3 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 3 * 8)
#define SC4 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 4 * 8)
#define SC5 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 5 * 8)
#define SC6 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 6 * 8)
#define SC7 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 7 * 8)
#define SC9 (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 9 * 8)

#define WAIT_RSP(val, okvar) SMC_WAIT_EQ(SC3, (val), CLADBG_FW_POLL_LIMIT, okvar)
#define WAIT_SC9(val, okvar) SMC_WAIT_EQ(SC9, (val), CLADBG_FW_POLL_LIMIT, okvar)

#define FIRE_ACTION(eap0) \
    do { \
        SMC_WR64(SMC_CLA_CDBGCLACTRLSTATUS_REG_ADDR, CLADBG_CLA_CTRLSTATUS_EXPECT); \
        SMC_WR64(SMC_CLA_CDBGNODE0EAP0_REG_ADDR, (eap0)); \
        SMC_WR64(SMC_CLA_CDBGNODE0EAP1_REG_ADDR, 0ull); \
        SMC_FENCE(); \
    } while (0)

#define CHECK_PUBLISH(eap0_expect) \
    do { \
        if (SMC_RD64(SMC_CLA_CDBGCLACTRLSTATUS_REG_ADDR) != CLADBG_CLA_CTRLSTATUS_EXPECT) \
            goto fail; \
        if (SMC_RD64(SMC_CLA_CDBGNODE0EAP0_REG_ADDR) != (eap0_expect)) goto fail; \
        if (SMC_RD64(SMC_CLA_CDBGNODE0EAP1_REG_ADDR) != 0ull) goto fail; \
        SMC_WR32(SC4, (uint32_t)(SMC_RD64(SMC_CLA_CDBGNODE0EAP0_REG_ADDR) & 0xFFFFFFFFu)); \
        SMC_WR32(SC5, (uint32_t)((SMC_RD64(SMC_CLA_CDBGNODE0EAP0_REG_ADDR) >> 32) & 0xFFFFFFFFu)); \
        SMC_WR32(SC6, 0u); \
        SMC_WR32(SC7, 0u); \
        SMC_FENCE(); \
    } while (0)

int main(void) {
    uint32_t ok;

    SMC_WR32(SC0, 0u);
    SMC_WR32(SC2, 0u);
    SMC_WR32(SC3, 0u);
    SMC_WR32(SC4, 0u);
    SMC_WR32(SC5, 0u);
    SMC_WR32(SC6, 0u);
    SMC_WR32(SC7, 0u);
    SMC_WR32(SC9, 0u);
    SMC_FENCE();
    if (SMC_RD32(SC0) != 0u || SMC_RD32(SC2) != 0u || SMC_RD32(SC3) != 0u) goto fail;

    SMC_WR64(SMC_CLA_CDBGCLACTRLSTATUS_REG_ADDR, CLADBG_CLA_CTRLSTATUS_EXPECT);
    SMC_WR64(SMC_CLA_CDBGNODE0EAP0_REG_ADDR, CLADBG_CLA_EAP0_RELEASE);
    SMC_WR64(SMC_CLA_CDBGNODE0EAP1_REG_ADDR, CLADBG_CLA_EAP1_RELEASE);
    SMC_WR32(SC1, CLADBG_ARM_TOKEN);
    SMC_FENCE();
    if (SMC_RD64(SMC_CLA_CDBGNODE0EAP0_REG_ADDR) != CLADBG_CLA_EAP0_RELEASE) goto fail;
    if (SMC_RD64(SMC_CLA_CDBGNODE0EAP1_REG_ADDR) != CLADBG_CLA_EAP1_RELEASE) goto fail;
    SMC_WR32(SC4, (uint32_t)((uint64_t)CLADBG_CLA_EAP0_RELEASE & 0xFFFFFFFFu));
    SMC_WR32(SC5, (uint32_t)(((uint64_t)CLADBG_CLA_EAP0_RELEASE >> 32) & 0xFFFFFFFFu));
    SMC_WR32(SC6, (uint32_t)((uint64_t)CLADBG_CLA_EAP1_RELEASE & 0xFFFFFFFFu));
    SMC_WR32(SC7, (uint32_t)(((uint64_t)CLADBG_CLA_EAP1_RELEASE >> 32) & 0xFFFFFFFFu));
    SMC_WR32(SC0, CLADBG_INIT_RELEASE_OK);
    SMC_FENCE();

    WAIT_RSP(CLADBG_READY, ok);
    if (!ok) goto fail;

    SMC_DELAY_ITERS(CLADBG_HOLD_ITERS);

    FIRE_ACTION(CLADBG_CLA_EAP0_ACT0);
    CHECK_PUBLISH(CLADBG_CLA_EAP0_ACT0);
    SMC_WR32(SC0, CLADBG_ACT0_ARMED);
    SMC_FENCE();
    SMC_DELAY_ITERS(CLADBG_HOLD_ITERS);

    FIRE_ACTION(CLADBG_CLA_EAP0_ACT1);
    CHECK_PUBLISH(CLADBG_CLA_EAP0_ACT1);
    SMC_WR32(SC0, CLADBG_ACT1_ARMED);
    SMC_FENCE();
    SMC_DELAY_ITERS(CLADBG_HOLD_ITERS);

    /* Reset-run maps inverted onto the SEP input. Hold it until the DV has
     * applied the first core reset edge. */
    FIRE_ACTION(CLADBG_CLA_EAP0_ACT2);
    CHECK_PUBLISH(CLADBG_CLA_EAP0_ACT2);
    SMC_WR32(SC0, CLADBG_ACT2_ARMED);
    SMC_FENCE();
    SMC_DELAY_ITERS(CLADBG_HOLD_ITERS);
    WAIT_SC9(CLADBG_DV_INVERT2_A, ok);
    if (!ok) goto fail;

    /* The unmapped action drops reset-run, so the SEP input returns to its
     * default. Wait for the DV to apply the second core reset edge. */
    FIRE_ACTION(CLADBG_CLA_EAP0_ACT5);
    CHECK_PUBLISH(CLADBG_CLA_EAP0_ACT5);
    SMC_WR32(SC0, CLADBG_ACT5_ARMED);
    SMC_FENCE();
    SMC_DELAY_ITERS(CLADBG_HOLD_ITERS);
    WAIT_SC9(CLADBG_DV_INVERT2_B, ok);
    if (!ok) goto fail;

    FIRE_ACTION(CLADBG_CLA_EAP0_ACT3);
    CHECK_PUBLISH(CLADBG_CLA_EAP0_ACT3);
    SMC_WR32(SC0, CLADBG_A3_BUSY_ARMED);
    SMC_FENCE();
    SMC_DELAY_ITERS(CLADBG_A3_HOLD_ITERS);
    SMC_WR32(SC0, CLADBG_A3_BUSY_HELD);
    SMC_FENCE();
    FIRE_ACTION(CLADBG_CLA_EAP0_ACT4);
    CHECK_PUBLISH(CLADBG_CLA_EAP0_ACT4);
    SMC_DELAY_ITERS(CLADBG_HOLD_ITERS);

    SMC_WR32(SC2, CLADBG_GO_IDLE);
    SMC_FENCE();
    WAIT_RSP(CLADBG_IDLE_ACK, ok);
    if (!ok) goto fail;
    SMC_DELAY_ITERS(CLADBG_HALT_SETTLE_ITERS);
    FIRE_ACTION(CLADBG_CLA_EAP0_ACT3);
    CHECK_PUBLISH(CLADBG_CLA_EAP0_ACT3);
    SMC_WR32(SC0, CLADBG_A3_IDLE_ARMED);
    SMC_FENCE();
    SMC_DELAY_ITERS(CLADBG_A3_HOLD_ITERS);

    SMC_WR32(SC0, CLADBG_DONE);
    SMC_FENCE();
    for (;;) __asm__ volatile("wfi");

fail:
    SMC_WR32(SC0, CLADBG_TEST_FAIL);
    SMC_FENCE();
    for (;;) __asm__ volatile("wfi");
}
