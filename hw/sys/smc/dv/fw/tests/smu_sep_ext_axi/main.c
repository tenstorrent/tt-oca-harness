/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

#include <stdint.h>

#include "smc_defines.h"
#include "smc_stackless_test.h"
#include "smu_sep_ext_axi_protocol.h"

/*
 * SEP_SMU_016  smu_sep_ext_axi_combined_probe_test  --  SMC external-egress
 * firmware.
 *
 * The SMC is the outbound producer for the SMC->ext_out leg. This firmware:
 *   S2  programs + READS BACK its own aperture (smc_global_base/smc_region_size),
 *       opens its ext_in inbound windows (so tb.ext_in can reach SMC scratch), and
 *       opens its outbound egress filter covering 0x80001000. Any mismatch/bus
 *       fault -> smu_sep_ext_axi_smc_fail_loop.
 *   S3  publishes SMC_READY at scratch6 and polls SMC_GO at scratch7 (the ext_in
 *       master writes GO only after both firmware readbacks/READYs are proven).
 *   S6  after GO, emits 0x5A5AA5A5 then 0xC001CAFE to non-aperture 0x80001000 so
 *       the SMC {01,smc_id} default-master fall-through route is exercised.
 *   S10 waits (bounded) for ROUTE_DONE_SMC at scratch9, then writes EXTAXI_SMC_PASS
 *       to LOCAL scratch10 and parks in smu_sep_ext_axi_smc_pass_loop.
 *
 * STACKLESS (smc_stackless_test.h): the SEP-driven / cocotb-backdoor boot does
 * not init the SMC SRAM stack, so main() makes no function calls (only SMC_*
 * absolute-MMIO/poll macros) and the terminal pass/fail loops are noreturn so
 * the compiler tail-calls them; main must contain no `add sp,sp,-N`.
 *
 * The outbound/inbound filter blocks are write-only programming interfaces (a CPU
 * read of one stalls), so only the aperture CSRs are read back in firmware; the
 * filter values are verified DV-side by passive DUT reads.
 *
 * allow_ns is an exact AxPROT[1] match (traffic_filter.sv), so every window is
 * programmed with a SECURE rule (rule0) AND an NS rule (rule1) covering the same
 * range -> the leg passes regardless of the initiator's security level.
 */
SMC_STACKLESS_ENTRY(smu_sep_ext_axi_smc_entry)

/* SMC-local scratch absolute addresses (CPU_CTRL array, 8-byte stride). */
#define SC6 SMC_CPU_CTRL_SCRATCH_6__REG_ADDR   /* SMC_READY (SMC -> ext_in)     */
#define SC7 SMC_CPU_CTRL_SCRATCH_7__REG_ADDR   /* SMC_GO    (ext_in -> SMC)     */
#define SC9 SMC_CPU_CTRL_SCRATCH_9__REG_ADDR   /* ROUTE_DONE_SMC (ext_in -> SMC) */
#define SC10 SMC_CPU_CTRL_SCRATCH_10__REG_ADDR /* EXTAXI_SMC_PASS (LOCAL)      */

/* SMC aperture CSRs (SMC_BASE_CONFIG; readable). */
#define SMC_GLOBAL_BASE_REG SMC_TOP_SMC_BASE_CONFIG_GLOBAL_BASE_BASE_ADDR
#define SMC_REGION_SIZE_REG SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR

/* SMC filter register bases (each entry 0x20; CFG/START/END at +0/+8/+10). */
#define SMC_INB_BASE SMC_TOP_SMC_INBOUND_FILTER_CTRL_BASE_ADDR(0)
#define SMC_OUT_BASE SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_BASE_ADDR(0)

/* Egress window covering the SMC->ext_out target 0x80001000 (single source:
 * protocol header, which DV also asserts against). */
#define SMC_OUT_START ((uint64_t)EXTAXI_SMC_OUT_ADDR)
#define SMC_OUT_END ((uint64_t)EXTAXI_SMC_OUT_END)
/* All-pass inbound window so tb.ext_in can reach any SMC address (scratch6..9). */
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

    /* S2 (setup): program the SMC aperture (smc_global_base/smc_region_size) and
     * read it back. The aperture CSRs are ordinary readable registers, so a
     * mismatch is a real bus/programming fault -> fail loop. */
    SMC_WR64(SMC_GLOBAL_BASE_REG, (uint64_t)EXTAXI_SMC_GLOBAL_BASE);
    SMC_WR32(SMC_REGION_SIZE_REG, EXTAXI_SMC_REGION_SIZE);
    SMC_FENCE();
    if (SMC_RD64(SMC_GLOBAL_BASE_REG) != (uint64_t)EXTAXI_SMC_GLOBAL_BASE) goto fail;
    if (SMC_RD32(SMC_REGION_SIZE_REG) != EXTAXI_SMC_REGION_SIZE) goto fail;

    /* S2 (setup): open the ext_in inbound windows (all-pass, secure + NS rules)
     * so tb.ext_in can reach SMC CPU_CTRL scratch for the GO/ROUTE_DONE barrier
     * and the ext_in->SMC route leg. Write-only programming interface -> no CPU
     * readback. */
    SMC_WR64(SMC_INB_BASE + EXTAXI_FILTER_START_OFF, SMC_INB_START);
    SMC_WR64(SMC_INB_BASE + EXTAXI_FILTER_END_OFF, SMC_INB_END);
    SMC_WR64(SMC_INB_BASE + EXTAXI_FILTER_CFG_OFF, EXTAXI_FILTER_CFG_SECURE);
    SMC_WR64(SMC_INB_BASE + EXTAXI_FILTER_STRIDE + EXTAXI_FILTER_START_OFF, SMC_INB_START);
    SMC_WR64(SMC_INB_BASE + EXTAXI_FILTER_STRIDE + EXTAXI_FILTER_END_OFF, SMC_INB_END);
    SMC_WR64(SMC_INB_BASE + EXTAXI_FILTER_STRIDE + EXTAXI_FILTER_CFG_OFF, EXTAXI_FILTER_CFG_NS);

    /* S2 (setup): open the outbound egress filter over the SMC->ext_out target
     * 0x80001000 (secure + NS rules). START/END before CFG so the entry enables
     * atomically over the final range. */
    SMC_WR64(SMC_OUT_BASE + EXTAXI_FILTER_START_OFF, SMC_OUT_START);
    SMC_WR64(SMC_OUT_BASE + EXTAXI_FILTER_END_OFF, SMC_OUT_END);
    SMC_WR64(SMC_OUT_BASE + EXTAXI_FILTER_CFG_OFF, EXTAXI_FILTER_CFG_SECURE);
    SMC_WR64(SMC_OUT_BASE + EXTAXI_FILTER_STRIDE + EXTAXI_FILTER_START_OFF, SMC_OUT_START);
    SMC_WR64(SMC_OUT_BASE + EXTAXI_FILTER_STRIDE + EXTAXI_FILTER_END_OFF, SMC_OUT_END);
    SMC_WR64(SMC_OUT_BASE + EXTAXI_FILTER_STRIDE + EXTAXI_FILTER_CFG_OFF, EXTAXI_FILTER_CFG_NS);
    SMC_FENCE();

    /* Clear the SMC-owned poll targets (GO / ROUTE_DONE / final PASS) so the DV
     * sees clean 0 -> token transitions. Do NOT touch scratch8 (ext_in route
     * data). */
    SMC_WR32(SC7, 0u);
    SMC_WR32(SC9, 0u);
    SMC_WR32(SC10, 0u);
    SMC_FENCE();

    /* S3 (barrier): publish SMC_READY at scratch6, then poll SMC_GO at scratch7.
     * The ext_in master writes GO only after both firmware setups/READYs are
     * proven. */
    SMC_WR32(SC6, EXTAXI_SMC_READY);
    SMC_FENCE();
    SMC_WAIT_EQ(SC7, EXTAXI_SMC_GO, EXTAXI_FW_POLL_LIMIT, ok);
    if (!ok) goto fail;

    /* S6 (egress): emit the two-word SMC->ext_out payload to the non-aperture
     * address 0x80001000. Single-beat stores; the xbar default-master
     * fall-through routes them to ext_out with ID {01,smc_id} (CHK-SMC-OUT
     * stimulus). */
    SMC_WR32(EXTAXI_SMC_OUT_ADDR, EXTAXI_SMC_OUT_DATA0);
    SMC_WR32(EXTAXI_SMC_OUT_ADDR, EXTAXI_SMC_OUT_DATA1);
    SMC_FENCE();

    /* S10 (complete): bounded-wait for ROUTE_DONE_SMC (ext_in writes it only
     * after all four legal legs + DECERR + recovery). On timeout, park at a
     * defined named PC (fail loop) rather than hang. */
    SMC_WAIT_EQ(SC9, EXTAXI_ROUTE_DONE_SMC, EXTAXI_FW_POLL_LIMIT, ok);
    if (!ok) goto fail;

    /* No final marker may precede its ROUTE_DONE readback: PASS is written only
     * now. Enter the named pass loop via a tail jump (no `jalr`/link) so main
     * saves no ra and never touches the (unbacked) SRAM stack -- keeps main
     * stackless while preserving the global loop symbol for the DV PC
     * classifier. */
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
