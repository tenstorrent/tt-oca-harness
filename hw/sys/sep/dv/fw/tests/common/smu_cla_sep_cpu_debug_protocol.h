/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */
/*
 * smu_cla_sep_cpu_debug_control_test  --  shared protocol contract.
 *
 * Exhaustive CLA node0-EAP action -> SEP CPU control mapping/effect test. The SMC producer fw
 * fires each single custom action and the DV scoreboard checks the mapped SEP input + effect:
 *   action[0] mpc_debug_halt_req_i -> DEBUG halt (freezes a BUSY core)          [functional]
 *   action[1] mpc_debug_run_req_i  -> DEBUG run/resume                          [functional]
 *   action[3] cpu_halt_req_i       -> PMU/FW halt (QUIESCENCE-GATED)            [DIAGNOSTIC]
 *   action[4] cpu_run_req_i        -> PMU run/resume                            [DIAGNOSTIC]
 * action[3] is a PMU/FW halt request: it is characterized idle-vs-busy
 * (CHK-PMU-HALT-DIAG) and is NOT required to freeze a busy core. action[2]
 * (mpc_reset_run_req_i, inverted) and action[5] (unmapped) are checked for mapping only.
 *
 * Included by BOTH firmwares + parsed by the cocotb checker. Plain integer/hex #defines only.
 * Channels: SMC CPU_CTRL scratch (base 0xC0039080, 8-byte stride); s0=SMC status, s1=CLA arm
 * token, s2=SMC->SEP cmd, s3=SEP->SMC rsp. SEP reaches them via the SEP->SMC alias 0x40039080+.
 */
#ifndef SMU_CLA_SEP_CPU_DEBUG_PROTOCOL_H
#define SMU_CLA_SEP_CPU_DEBUG_PROTOCOL_H

/* common CLA arm token (scratch1) the SV real-CLA liveness monitor waits for */
#define CLADBG_ARM_TOKEN 0x02200100

/* Frontdoor boot (reuse the smu_smc_stall_sep mechanism): TB backdoor-preloads the SMC image;
 * the SEP fw
 * brings the SMC up over sep_axi_in (common sep_smc_bringup.h). Entry/cookie are the built SMC
 * image's values (cocotb drift-checks both). */
#define CLADBG_SMC_IMAGE_FIRST_WORD 0x41014081 /* SEP bring-up cookie; stale image -> S0_FAIL */
#define CLADBG_SMC_ENTRY 0x00000000C00601B2ULL /* RECONCILE vs built .dis +SMC_RESET_SYMBOL */

/* SEP-side alias addresses for the SMC status/command/response scratch registers */
#define CLADBG_STATUS_ALIAS_ADDR 0x40039080
#define CLADBG_CMD_ALIAS_ADDR 0x40039090
#define CLADBG_RSP_ALIAS_ADDR 0x40039098

/* s0 : SMC status/progress + per-action ARMED markers (cocotb opens an observation window on
 * each). */
/* Scratch value before the SMC producer has published anything. */
#define CLADBG_STATUS_PRISTINE 0x00000000
#define CLADBG_INIT_RELEASE_OK 0x00500000
#define CLADBG_ACT0_ARMED 0x00500001    /* action[0] debug-halt fired (busy SEP)   */
#define CLADBG_ACT1_ARMED 0x00500002    /* action[1] debug-run fired               */
#define CLADBG_A3_BUSY_ARMED 0x00500003 /* action[3] PMU-halt fired, SEP BUSY; NO action[4] yet */
#define CLADBG_A3_BUSY_HELD 0x00500005  /* action[3] held-window ended; action[4] about to fire */
#define CLADBG_A3_IDLE_ARMED 0x00500004 /* action[3] PMU-halt fired, SEP IDLE(wfi) */
#define CLADBG_ACT2_ARMED 0x00500007    /* action[2] reset-run (inverted); net + CHK-INVERT-2 */
#define CLADBG_ACT5_ARMED 0x00500008    /* action[5] unmapped fired (SEP running); negative leg */
#define CLADBG_DONE 0x0050000F
#define CLADBG_TEST_FAIL 0xFFFFFFFF

/* SMC scratch_4/_5: SMC fw publishes the exact read-back CLA node0 EAP0 for the current phase
 * (low32 -> scratch_4, high32 -> scratch_5) so the cocotb CHK-CLA-PRODUCER can assert+log the exact
 * per-action CSR readback. CDBGCLACTRLSTATUS is read back and enforced by the fw itself.
 */

/* s2 : SMC -> SEP command channel */
#define CLADBG_GO_IDLE 0x0050B001 /* SEP: ack then WFI (go idle for the PMU-halt idle case) */

/* s3 : SEP -> SMC response channel */
#define CLADBG_READY 0x00510001    /* SEP live + spinning in the busy poll loop */
#define CLADBG_IDLE_ACK 0x00510002 /* SEP acked GO_IDLE and is about to WFI */
#define CLADBG_S0_FAIL 0x00510FA1  /* SEP->scratch3: SMC SRAM preload cookie never landed */

/* Firmware poll/settle/hold bounds */
#define CLADBG_FW_POLL_LIMIT 4000000
#define CLADBG_HALT_SETTLE_ITERS 2000
#define CLADBG_HOLD_ITERS 8000
/* DV->SMC handshake (scratch 9) so CHK-INVERT-2 can finish each reset edge
 * before the next CLA action. */
#define CLADBG_DV_INVERT2_A 0x0221A001
#define CLADBG_DV_INVERT2_B 0x0221A002
#define CLADBG_A3_HOLD_ITERS \
    20000 /* bounded action[3]-only hold (no action[4]) so the cocotb \
             can classify halt+stable BEFORE the release (~400us) */

/* CLA node0 EAP single-action values (smu_sep_cla_node0_eap_value literals):
 *   initial release {1,4}: EAP0=0x341FBFC000 / EAP1=0x144FBFC000.
 *   single action N: EAP0 = 0x10<N>FBFC000, EAP1=0 (N in 0..5; bit N of the custom bus). */
#define CLADBG_CLA_CTRLSTATUS_EXPECT 0x60
#define CLADBG_CLA_EAP0_RELEASE 0x341FBFC000ULL
#define CLADBG_CLA_EAP1_RELEASE 0x144FBFC000ULL
#define CLADBG_CLA_EAP0_ACT0 0x100FBFC000ULL /* mpc_debug_halt_req_i */
#define CLADBG_CLA_EAP0_ACT1 0x101FBFC000ULL /* mpc_debug_run_req_i  */
#define CLADBG_CLA_EAP0_ACT3 0x103FBFC000ULL /* cpu_halt_req_i       */
#define CLADBG_CLA_EAP0_ACT4 0x104FBFC000ULL /* cpu_run_req_i        */
#define CLADBG_CLA_EAP0_ACT2 0x102FBFC000ULL /* mpc_reset_run_req_i = ~cla[2] (inverted) */
#define CLADBG_CLA_EAP0_ACT5 0x105FBFC000ULL /* unmapped [5..15]     */

#endif /* SMU_CLA_SEP_CPU_DEBUG_PROTOCOL_H */
