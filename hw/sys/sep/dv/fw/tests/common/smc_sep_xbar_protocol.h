/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */
/*
 * smc_sep_xbar  --  shared protocol contract (single source of truth).
 *
 * Included by the SMC producer firmware hw/sys/smc/dv/fw/tests/smc_sep_xbar/main.c and by
 * the SEP driver header sep_outbound_filter.h. Python goldens
 * derive CSR facts independently from PeakRDL; they do not parse this header.
 *
 * Force-free SEP-driven bootstrap: the real SEP CPU boots
 * from its own fuse/reset, opens its outbound egress window, polls SMC SRAM for the exact
 * preload cookie, then re-vectors + releases the four SMC cores over the SEP->SMC alias
 * (sep_smc_bringup.h). The TB issues no reset/CSR/vector force. Then the two firmwares run
 * the fixed-alias bidirectional datapath + acknowledged completion protocol.
 *
 * SMC CPU_CTRL scratch array (8-byte stride, SMC-local base 0xC0039080; SEP-view alias =
 * SMC-internal - 0x8000_0000, base 0x40039080):
 *   scratch0  : SMC status/progress markers (SMC -> observers)   SMC 0xC0039080 / SEP 0x40039080
 *   scratch1  : SMC CLA arm token (satisfies the SV real-CLA liveness monitor)
 *   scratch2  : SMC -> SEP status channel (SMC_READY, SCRATCH8_OK)
 *   scratch8  : SEP -> SMC dedicated fixed-alias datapath word    SMC 0xC00390C0 / SEP 0x400390C0
 *   scratch12 : SEP -> SMC response channel (READY, ACK, SEP_PASS) SMC 0xC00390E0 / SEP 0x400390E0
 * SMC -> SEP command channel is the SEP cold scratch0 at SEP-local 0x10802000 (via SMU xbar).
 */
#ifndef SMC_SEP_XBAR_PROTOCOL_H
#define SMC_SEP_XBAR_PROTOCOL_H

/* ---- Frontdoor SMC bring-up over the SEP->SMC port (SEP-driven; no net force/ext_in) ---- */
#define XBAR_SMC_SRAM_BASE_ALIAS 0x40060000  /* SEP-view of SMC SRAM base */
#define XBAR_SMC_IMAGE_FIRST_WORD 0x41014081 /* exact preload cookie (SRAM[0]); drift-checked */
#define XBAR_SMC_ENTRY 0x00000000C00601B2ULL /* built SMC image entry (smc_sep_xbar_entry) */
#define XBAR_RESET_VECTOR_ALIAS 0x40039000   /* SEP-view of SMC RESET_VECTOR_0 */
#define XBAR_RESET_CTRL_ALIAS 0x40039020     /* SEP-view of SMC RESET_CTRL */
#define XBAR_S0_FAIL 0x00460FA1              /* SEP->scratch12: preload never landed */

/* ---- SEP->SMC dedicated fixed-alias datapath (scratch8) ---- */
#define XBAR_SEP_TO_SMC_SCRATCH8_SEP 0x400390C0u /* SEP-view (global)  */
#define XBAR_SEP_TO_SMC_SCRATCH8_SMC 0xC00390C0u /* SMC local-fabric rebase (final consumer) */
#define XBAR_DATA_PATTERN 0x13579BDFu            /* the correlated SEP->SMC word */

/* ---- SEP->SMC response channel (scratch12) ---- */
#define XBAR_SCRATCH12_SEP 0x400390E0u
#define XBAR_SEP_READY 0x51EAD001u      /* SEP: setup done, data published */
#define XBAR_SEP_TO_SMC_ACK 0x5E9ACCE5u /* SEP: saw SMC CMD */
#define XBAR_SEP_PASS 0x5E9A600Du       /* SEP: saw DONE, datapath complete */

/* ---- SMC->SEP command channel (SEP cold scratch0 at SEP-local 0x10802000, via SMU xbar) ---- */
#ifdef SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR
#define XBAR_SEP_SHARED_ADDR SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(0)
#else
#define XBAR_SEP_SHARED_ADDR 0x10802000u
#endif
#define XBAR_SMC_TO_SEP_CMD 0xC001CAFEu
#define XBAR_SMC_TO_SEP_DONE 0xD0E0F00Du

/* ---- SMC scratch0 (status) markers ---- */
#define XBAR_SMC_TEST_PASS 0xACAFACA1u
#define XBAR_SMC_TEST_FAIL 0xFFFFFFFFu
/* ---- SMC scratch2 (SMC->SEP status) markers ---- */
#define XBAR_SMC_READY 0x00330001u       /* SMC: setup done, ready for SEP */
#define XBAR_SMC_SCRATCH8_OK 0x0038A001u /* SMC: validated scratch8 == DATA_PATTERN */
/* ---- SMC scratch1 CLA arm token (SV real-CLA liveness monitor) ---- */
#define XBAR_SMC_ARM_TOKEN 0x02200100u

/* SEP-view alias addresses of the SMC status/response scratch registers */
#define XBAR_SMC_STATUS_ALIAS 0x40039080u /* scratch0 (SMC status)  */
#define XBAR_SMC_READY_ALIAS 0x40039090u  /* scratch2 (SMC->SEP status) */

/* SMU xbar SEP aperture: cover 0x10802000 for SMC->SEP without overlapping SMC @0x40000000 */
#define XBAR_SEP_APERTURE_SIZE 0x20000000ULL

/* Firmware poll bounds (loop iterations; never hang). Secondary bound only -- the cocotb
 * MONITOR_TIMEOUT (~3ms sim) is the primary fail-loud gate. Sized to comfortably cover the
 * legit cookie / SMC_READY waits (the whole post-fuse datapath is <~0.1ms sim) with wide
 * margin, without being absurdly long. */
#define XBAR_FW_POLL_LIMIT 200000

/* CLA node0 EAP CSR values (verbatim, matching the real-CLA release; satisfies the SV
 * testbench real-CLA liveness monitor). */
#define XBAR_CLA_CTRLSTATUS_EXPECT 0x60
#define XBAR_CLA_EAP0_RELEASE 0x341FBFC000ULL
#define XBAR_CLA_EAP1_RELEASE 0x144FBFC000ULL

/* ---- CHK-SEP-HOLD-RELEASE fw ordering gate: SMC/SEP fuse-sense-done status CSRs ---- */
/* SEP-local CPU_CTRL status CSRs (bit0). The SEP FW must observe the SMC's fuse-sense-done
 * (hw/sys/sep/rtl/sep.sv port smc_fuse_sense_done_i -> this CSR) == 1 BEFORE its first
 * sep_axi_in CPU_CTRL write, so the SEP never drives the SMC before the SMC's fuse sense has
 * completed. */
#ifdef SEP_TOP_SEP_CPU_CTRL_SMC_FUSE_SENSE_STATUS_BASE_ADDR
#define XBAR_SMC_FUSE_STATUS_ADDR SEP_TOP_SEP_CPU_CTRL_SMC_FUSE_SENSE_STATUS_BASE_ADDR
#define XBAR_SEP_FUSE_STATUS_ADDR SEP_TOP_SEP_CPU_CTRL_SEP_FUSE_SENSE_STATUS_BASE_ADDR
#define XBAR_FUSE_SENSE_DONE_MASK SEP_CPU_CTRL__SMC_FUSE_SENSE_STATUS__SMC_FUSE_SENSE_DONE_bm
#else
#define XBAR_SMC_FUSE_STATUS_ADDR 0x10A30140u
#define XBAR_SEP_FUSE_STATUS_ADDR 0x10A30150u
#define XBAR_FUSE_SENSE_DONE_MASK 0x1u
#endif

/* ---- CHK-SETUP readback goldens (each programmed aperture/filter is read back and compared) */
/* SEP aperture + filter register bases/offsets are pulled from sep.h in the fw. */
#define XBAR_SEP_REGION_SIZE_GOLDEN 0x20000000u       /* SEP_REGION_SIZE (32b) */
#define XBAR_SEP_OUTBOUND_START 0x0000000040000000ULL /* SEP outbound egress filter */
#define XBAR_SEP_OUTBOUND_END 0x00000000800000FFULL
/*
 * FILTER_CONFIG words (hw/ip/axi_filter/regs/filter_ctrl.rdl): read_allowed[0],
 * write_allowed[1], entry_enabled[4], allow_ns[8], data_bus_width[14:12] (sw=r,
 * reset 3), src_id[19:16], allow_burst[24], locked[63]. Bits 32..62 hold no
 * field. Each word carries data_bus_width at its reset value, so the written
 * word is also the value a readback returns. sep_outbound_filter.h checks
 * XBAR_SEP_OUTBOUND_CFG against the generated filter_ctrl.h field masks.
 *   OUTBOUND_CFG: read | write | entry_enabled | allow_burst
 *   INBOUND_CFG0 / SMC_OUTBOUND_CFG: read | write | entry_enabled | src_id=3
 *   INBOUND_CFG1: INBOUND_CFG0 | allow_ns
 */
#define XBAR_SEP_OUTBOUND_CFG 0x0000000001003013ULL
#ifdef SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR
#define XBAR_SEP_INBOUND_START ((unsigned long long)SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(0))
#define XBAR_SEP_INBOUND_END \
    ((unsigned long long)(SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(7) + 7u))
#define XBAR_SMC_OUTBOUND_START XBAR_SEP_INBOUND_START
#define XBAR_SMC_OUTBOUND_END XBAR_SEP_INBOUND_END
#else
#define XBAR_SEP_INBOUND_START 0x0000000010802000ULL
#define XBAR_SEP_INBOUND_END 0x000000001080203FULL
#define XBAR_SMC_OUTBOUND_START 0x0000000010802000ULL
#define XBAR_SMC_OUTBOUND_END 0x000000001080203FULL
#endif
#define XBAR_SEP_INBOUND_CFG0 0x0000000000033013ULL
#define XBAR_SEP_INBOUND_CFG1 0x0000000000033113ULL
#define XBAR_SMC_OUTBOUND_CFG 0x0000000000033013ULL
/* SMC CPU_CTRL RESET_CTRL post-pulse readback: default value (pulse_start bits self-clear). */
#define XBAR_SMC_RESET_CTRL_DEFAULT 0x0000010Fu

/* ---- SMC scratch0 progress markers (SMC-owned; ordered evidence, CHK-SETUP/CHK-BOTH-PASS) ---- */
#define XBAR_SMC_SETUP_OK 0x0035E100u /* SMC: cleared + outbound filter programmed & read back */
#define XBAR_SMC_CMD_SENT 0x00C0DDE1u /* SMC wrote CMD to SEP cold scratch0. */
#define XBAR_SMC_DONE_SENT \
    0x00D0DDE1u /* SMC: wrote DONE to SEP cold scratch0 (CHK-BOTH-PASS: DONE) */

#endif /* SMC_SEP_XBAR_PROTOCOL_H */
