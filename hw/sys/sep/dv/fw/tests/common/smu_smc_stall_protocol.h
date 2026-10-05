/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */
/*
 * smu_smc_stall_sep  --  shared protocol contract (single source of truth).
 *
 * Included by both firmwares (SMC hold/release + SEP GO-poll) and parsed by the
 * cocotb checker so DUT stimulus and DV expectations share one contract.
 * Keep every value a plain integer/hex #define so the Python parser can read it.
 *
 * Channels (SMC CPU_CTRL scratch array, 8-byte stride, base 0xC0039080):
 *   scratch0 : SMC status/progress markers (SMC -> observers)
 *   scratch1 : common CLA arm token (written by the SMC fw in this test to satisfy the SV
 *              liveness monitor)
 *   scratch2 : SMC -> SEP command channel
 *   scratch3 : SEP -> SMC response channel
 * The SEP reaches the SMC scratch through the SEP->SMC alias (subtract 0x4000_0000 then SMC
 * local rebase to 0xC000_0000): SEP 0x40039090 -> SMC scratch2, 0x40039098 -> scratch3.
 */
#ifndef SMU_SMC_STALL_PROTOCOL_H
#define SMU_SMC_STALL_PROTOCOL_H

/* common CLA arm token (scratch1) the SV real-CLA liveness monitor waits for */
#define SMU_STALL_ARM_TOKEN 0x02200100

/* Frontdoor SMC bring-up over the SEP->SMC port -- no net force, no ext_in master, and
 * NOT behind the SMC sys-INBOUND filter. (The SEP's own OUTBOUND egress filter IS
 * configured as required setup -- see open_sep_outbound_xbar_window; that is what "no
 * filter" excludes: only the SMC sys-inbound BLOCK_BY_DEFAULT filter, which this port does
 * not traverse.) The TB backdoor-preloads the SMC image into SRAM (accepted setup that
 * stands in for the SMC-ROM-loads-SRAM step; this test does not verify the production SMC
 * secure-boot / manifest / BL1 flow). The real SEP firmware then, over the same alias
 * path used for scratch, (a) polls SMC SRAM until the exact preload cookie lands (fails
 * to S0_FAIL on timeout), (b) re-vectors all four SMC cores to the entry and pulses their
 * reset -- releasing them to run the image. SEP alias = SMC-internal - 0x8000_0000
 * (0xC0039000 -> 0x40039000, 0xC0060000 -> 0x40060000). SMU_STALL_SMC_ENTRY is the
 * SMC-internal reset-vector value; SMU_STALL_SMC_IMAGE_FIRST_WORD is the first image word
 * (both cocotb-drift-checked against the built image). */
#define SMU_STALL_SMC_SRAM_BASE_ALIAS 0x40060000  /* SEP-view of SMC SRAM base */
#define SMU_STALL_SMC_IMAGE_FIRST_WORD 0x41014081 /* exact preload cookie (SRAM[0]) */
#define SMU_STALL_S0_FAIL 0x00460FA1              /* SEP->scratch3: preload never landed */
#define SMU_STALL_SMC_ENTRY 0x00000000C00601BEULL /* built SMC image entry */
#define SMU_STALL_RESET_VECTOR_ALIAS 0x40039000   /* SEP-view of SMC RESET_VECTOR_0 */
#define SMU_STALL_RESET_CTRL_ALIAS 0x40039020     /* SEP-view of SMC RESET_CTRL */
#define SMU_STALL_RESET_CTRL_PULSE \
    0x00000000000001FFULL /* default 0x10F | core0-3 reset_pulse_start */

/* scratch indices */
#define SMU_STALL_SCRATCH_STATUS 0
#define SMU_STALL_SCRATCH_ARM 1
#define SMU_STALL_SCRATCH_CMD 2
#define SMU_STALL_SCRATCH_RSP 3

/* SEP-side alias addresses for the SMC status/command/response scratch registers */
#define SMU_STALL_STATUS_ALIAS_ADDR 0x40039080
#define SMU_STALL_CMD_ALIAS_ADDR 0x40039090
#define SMU_STALL_RSP_ALIAS_ADDR 0x40039098

/* scratch0 : SMC status/progress markers */
#define SMU_STALL_INIT_RELEASE_OK 0x0040A000
#define SMU_STALL_HALT_OK 0x0040A001
#define SMU_STALL_HELD_OK 0x0040A002
#define SMU_STALL_RELEASE_OK 0x0040A003
#define SMU_STALL_TEST_PASS 0xACAFACA1
#define SMU_STALL_TEST_FAIL 0xFFFFFFFF

/* scratch2 : SMC -> SEP command channel (PROBE must stay distinct from GO) */
#define SMU_STALL_PROBE 0x0040B000
#define SMU_STALL_GO 0x0040B001
#define SMU_STALL_RELEASE_GATE 0x0040B002
#define SMU_STALL_ACK 0x0040B003

/* scratch3 : SEP -> SMC response channel */
#define SMU_STALL_READY 0x00470001
#define SMU_STALL_GO_SEEN 0x00470002
#define SMU_STALL_POLL_ARMED 0x00470003
#define SMU_STALL_COMPLETION 0x0045A55A
#define SMU_STALL_PASS 0x0045CAFE

/* Held-window policy (single source). The SMC does a deterministic fixed hold of
 * SMU_STALL_HELD_HOLD_ITERS firmware loop iterations between HALT_OK and HELD_OK;
 * the cocotb checker requires the measured HALT_OK->HELD_OK span to be >=
 * SMU_STALL_HELD_MIN_CYCLES clk_smu and samples scratch3 at both endpoints and
 * every SMU_STALL_HELD_SAMPLE_STRIDE clk_smu, all == POLL_ARMED. */
#define SMU_STALL_HELD_HOLD_ITERS 8000
#define SMU_STALL_HELD_MIN_CYCLES 1024
#define SMU_STALL_HELD_SAMPLE_STRIDE 128

/* Firmware poll/settle bounds (loop iterations) */
#define SMU_STALL_FW_POLL_LIMIT 4000000
#define SMU_STALL_HALT_SETTLE_ITERS 2000

/* CLA node0 EAP CSR values (verbatim literals matching smu_sep_cla_node0_eap_value):
 *   RELEASE = value(1,4,true)/value(4,4,false): fires actions [1] mpc_debug_run_req_i
 *             and [4] cpu_run_req_i (the standard run/resume pair).
 *   HALT    = value(0,0,false): fires action [0] mpc_debug_halt_req_i, the VeeR MPC
 *             debug halt that stalls a running core. Action [3] cpu_halt_req_i does
 *             not halt a live core (the core keeps retiring and o_cpu_halt_status
 *             stays 0), so this test halts via action [0] and resumes via the release
 *             actions [1]/[4]. */
#define SMU_STALL_CLA_CTRLSTATUS_EXPECT 0x60
#define SMU_STALL_CLA_EAP0_RELEASE 0x341FBFC000ULL
#define SMU_STALL_CLA_EAP1_RELEASE 0x144FBFC000ULL
#define SMU_STALL_CLA_EAP0_HALT 0x100FBFC000ULL
#define SMU_STALL_CLA_EAP1_HALT 0x0

#endif /* SMU_SMC_STALL_PROTOCOL_H */
