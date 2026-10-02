/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "smc_defines.h"
#include "smc_stackless_test.h"
#include "smu_sep_ext_axi_protocol.h"

/*
 * SMU-SEP external AXI combined probe: SMC external egress firmware.
 *
 * Opens the SMC to the SMU external AXI ports and drives the SMC to ext_out
 * leg: the SMC sets and reads back its own aperture, opens its inbound and
 * outbound filters, and after GO from ext_in sends two stores to an address
 * outside every aperture so the crossbar default route carries them to ext_out.
 *
 * Stackless: this boot path does not initialize the SMC stack, so main() makes
 * no function calls and enters the pass and fail loops by a tail jump.
 *
 * The CPU cannot read the filter registers (a read stalls), so only the
 * aperture is read back and the DV checks the filters. The filters match the
 * initiator's security level exactly, so each window gets a secure rule and a
 * non-secure rule over the same range.
 */
SMC_STACKLESS_ENTRY(smu_sep_ext_axi_smc_entry)

/* Handshake scratch registers: the token each one carries and its writer. */
#define SC6 SMC_CPU_CTRL_SCRATCH_6__REG_ADDR   /* SMC_READY (SMC -> ext_in)     */
#define SC7 SMC_CPU_CTRL_SCRATCH_7__REG_ADDR   /* SMC_GO    (ext_in -> SMC)     */
#define SC9 SMC_CPU_CTRL_SCRATCH_9__REG_ADDR   /* ROUTE_DONE_SMC (ext_in -> SMC) */
#define SC10 SMC_CPU_CTRL_SCRATCH_10__REG_ADDR /* EXTAXI_SMC_PASS (LOCAL)      */

/* SMC aperture registers; unlike the filters, the CPU can read them. */
#define SMC_GLOBAL_BASE_REG SMC_TOP_SMC_BASE_CONFIG_GLOBAL_BASE_BASE_ADDR
#define SMC_REGION_SIZE_REG SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR

/* First entry of each SMC filter; the next entry holds the non-secure rule. */
#define SMC_INB_BASE SMC_TOP_SMC_INBOUND_FILTER_CTRL_BASE_ADDR(0)
#define SMC_OUT_BASE SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_BASE_ADDR(0)

/* Egress window over the SMC to ext_out target, taken from the protocol header. */
#define SMC_OUT_START ((uint64_t)EXTAXI_SMC_OUT_ADDR)
#define SMC_OUT_END ((uint64_t)EXTAXI_SMC_OUT_END)
/* All-pass inbound window so ext_in can reach the handshake scratch registers. */
#define SMC_INB_START 0x0000000000000000ULL
#define SMC_INB_END 0x00FFFFFFFFFFFFFFULL

__attribute__((noinline, used, noreturn)) void smu_sep_ext_axi_smc_pass_loop(void) {
    for (;;) __asm__ volatile("wfi");
}

__attribute__((noinline, used, noreturn)) void smu_sep_ext_axi_smc_fail_loop(void) {
    for (;;) __asm__ volatile("wfi");
}

int main(void) {
    uint32_t ok;

    /* The aperture registers are ordinary readable registers, so a readback
     * mismatch is a real fault. */
    SMC_WR64(SMC_GLOBAL_BASE_REG, (uint64_t)EXTAXI_SMC_GLOBAL_BASE);
    SMC_WR32(SMC_REGION_SIZE_REG, EXTAXI_SMC_REGION_SIZE);
    SMC_FENCE();
    if (SMC_RD64(SMC_GLOBAL_BASE_REG) != (uint64_t)EXTAXI_SMC_GLOBAL_BASE) goto fail;
    if (SMC_RD32(SMC_REGION_SIZE_REG) != EXTAXI_SMC_REGION_SIZE) goto fail;

    /* Open the inbound filter so ext_in can reach the SMC scratch registers
     * for the handshake and for its route leg into the SMC. */
    SMC_WR64(SMC_INB_BASE + EXTAXI_FILTER_START_OFF, SMC_INB_START);
    SMC_WR64(SMC_INB_BASE + EXTAXI_FILTER_END_OFF, SMC_INB_END);
    SMC_WR64(SMC_INB_BASE + EXTAXI_FILTER_CFG_OFF, EXTAXI_FILTER_CFG_SECURE);
    SMC_WR64(SMC_INB_BASE + EXTAXI_FILTER_STRIDE + EXTAXI_FILTER_START_OFF, SMC_INB_START);
    SMC_WR64(SMC_INB_BASE + EXTAXI_FILTER_STRIDE + EXTAXI_FILTER_END_OFF, SMC_INB_END);
    SMC_WR64(SMC_INB_BASE + EXTAXI_FILTER_STRIDE + EXTAXI_FILTER_CFG_OFF, EXTAXI_FILTER_CFG_NS);

    /* Open the outbound filter over the egress target. Program the range
     * before the config so the entry enables over the final range. */
    SMC_WR64(SMC_OUT_BASE + EXTAXI_FILTER_START_OFF, SMC_OUT_START);
    SMC_WR64(SMC_OUT_BASE + EXTAXI_FILTER_END_OFF, SMC_OUT_END);
    SMC_WR64(SMC_OUT_BASE + EXTAXI_FILTER_CFG_OFF, EXTAXI_FILTER_CFG_SECURE);
    SMC_WR64(SMC_OUT_BASE + EXTAXI_FILTER_STRIDE + EXTAXI_FILTER_START_OFF, SMC_OUT_START);
    SMC_WR64(SMC_OUT_BASE + EXTAXI_FILTER_STRIDE + EXTAXI_FILTER_END_OFF, SMC_OUT_END);
    SMC_WR64(SMC_OUT_BASE + EXTAXI_FILTER_STRIDE + EXTAXI_FILTER_CFG_OFF, EXTAXI_FILTER_CFG_NS);
    SMC_FENCE();

    /* Clear the registers the SMC polls or reports on so each token arrives
     * on a clean zero. Leave the ext_in route data register untouched. */
    SMC_WR32(SC7, 0u);
    SMC_WR32(SC9, 0u);
    SMC_WR32(SC10, 0u);
    SMC_FENCE();

    /* ext_in writes GO only after both the SMC and SEP setups are proven. */
    SMC_WR32(SC6, EXTAXI_SMC_READY);
    SMC_FENCE();
    SMC_WAIT_EQ(SC7, EXTAXI_SMC_GO, EXTAXI_FW_POLL_LIMIT, ok);
    if (!ok) goto fail;

    /* Single-beat stores outside every aperture; the crossbar default route
     * carries them to ext_out. */
    SMC_WR32(EXTAXI_SMC_OUT_ADDR, EXTAXI_SMC_OUT_DATA0);
    SMC_WR32(EXTAXI_SMC_OUT_ADDR, EXTAXI_SMC_OUT_DATA1);
    SMC_FENCE();

    /* ext_in reports ROUTE_DONE only after every route leg has finished. On
     * timeout, park in the fail loop instead of hanging. */
    SMC_WAIT_EQ(SC9, EXTAXI_ROUTE_DONE_SMC, EXTAXI_FW_POLL_LIMIT, ok);
    if (!ok) goto fail;

    /* PASS must not precede ROUTE_DONE. A tail jump enters the named pass loop
     * without saving a return address, so main stays stackless and the DV can
     * classify the final PC by the loop symbol. */
    SMC_WR32(SC10, EXTAXI_SMC_PASS);
    SMC_FENCE();
    __asm__ volatile("tail smu_sep_ext_axi_smc_pass_loop");
    __builtin_unreachable();

fail:
    SMC_WR32(SC10, EXTAXI_SMC_FAIL);
    SMC_FENCE();
    __asm__ volatile("tail smu_sep_ext_axi_smc_fail_loop");
    __builtin_unreachable();
}
