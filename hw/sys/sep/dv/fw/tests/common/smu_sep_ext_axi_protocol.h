/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */
/*
 * smu_sep_ext_axi_combined_probe_test  --  shared protocol contract.
 *
 * Included by both firmwares (the SEP and SMC outbound producers). Python
 * goldens derive CSR facts independently from PeakRDL; they do not parse this
 * header.
 *
 * Test shape (four legal external legs + one blocked route + recovery):
 *   ext_in -> SMC aperture (route data 0x11223344 @ SMC scratch8)
 *   ext_in -> SEP aperture (route data 0x55667788 @ SEP cold scratch0)
 *   SEP    -> ext_out      (0xA5A55A5A/0xCAFEBABE @ 0x80000000, xbar fall-through)
 *   SMC    -> ext_out      (0x5A5AA5A5/0xC001CAFE @ 0x80001000, xbar fall-through)
 *   ext_in -> ext_out      (0x80002000) is unsupported -> DECERR (checked DV-side)
 *
 * Barrier: each firmware programs+reads back its OWN aperture, publishes a READY
 * marker, and waits for a distinct GO token that the authentic tb.ext_in master
 * writes only after both setups/readbacks are proven.  After all four legal legs,
 * the DECERR and the recovery read, ext_in writes ROUTE_DONE_* and each firmware
 * publishes its final PASS marker and parks in a named pass loop.
 *
 * The firmware keeps the SEP egress store (it is the CHK-SEP-OUT stimulus) and bounds
 * every post-egress wait so it never hangs; if ROUTE_DONE/PASS cannot be reached the
 * firmware parks at a defined, named PC and DV reports the observed PC/phase.  Whether
 * the SEP egress reaches ext_out is adjudicated from the run, not preassigned.
 *
 * ADDRESSING (firmware uses LOCAL register-header symbols; the GLOBAL forms below
 * are what the external tb.ext_in master uses through the programmed apertures):
 *   SMC CPU_CTRL scratch (SMC-local base 0xC0039080, 8-byte stride):
 *     scratch6  SMC_READY        local 0xC00390B0  ext_in-global 0x020390B0
 *     scratch7  SMC_GO           local 0xC00390B8  ext_in-global 0x020390B8
 *     scratch8  route data       local 0xC00390C0  ext_in-global 0x020390C0
 *     scratch9  ROUTE_DONE_SMC   local 0xC00390C8  ext_in-global 0x020390C8
 *     scratch10 SMU016_SMC_PASS  local 0xC00390D0  (0x000390D0 is the SMU
 *               post-remap monitor form of the same register; the SMC firmware
 *               writes its LOCAL register 0xC00390D0 per smc_top_regs.h.)
 *   SEP cold scratch (SEP-local base 0x10802000, 8-byte stride). The ext_in-global form is
 *   sep_global_base + local (0x04000000 + 0x108020xx = 0x148020xx); the SEP inbound
 *   axi_window_remap (target_base=0) subtracts sep_global_base back to the local register.
 *   (cold6 SMU016_SEP_PASS is SEP-local only -- the SEP writes it, DV reads it backdoor --
 *    so it needs no ext_in-global form.):
 *     cold0     route data       local 0x10802000  ext_in-global 0x14802000
 *     cold4     SEP_READY        local 0x10802020  ext_in-global 0x14802020
 *     cold5     SEP_GO           local 0x10802028  ext_in-global 0x14802028
 *     cold7     ROUTE_DONE_SEP   local 0x10802038  ext_in-global 0x14802038
 */
#ifndef SMU_SEP_EXT_AXI_PROTOCOL_H
#define SMU_SEP_EXT_AXI_PROTOCOL_H

/* ---- READY / GO handshake tokens ---- */
#define EXTAXI_SMC_READY 0x16050001 /* SMC publishes at scratch6 */
#define EXTAXI_SMC_GO 0x16060001    /* ext_in writes at scratch7 after setup proven */
#define EXTAXI_SEP_READY 0x16050002 /* SEP publishes at cold scratch4 */
#define EXTAXI_SEP_GO 0x16060002    /* ext_in writes at cold scratch5 after setup proven */

/* ---- SEP -> ext_out egress (xbar default-master fall-through) ----
 * The SEP fw opens its outbound egress filter over [SEP_OUT_ADDR, SEP_OUT_END]; DV asserts the
 * exact programmed window (canonicalized to the 4KB filter page) + policy. */
#define EXTAXI_SEP_OUT_ADDR 0x80000000
#define EXTAXI_SEP_OUT_END 0x800000FF /* sep_outbound_filter.h FILTER_END_ADDR */
#define EXTAXI_SEP_OUT_DATA0 0xA5A55A5A
#define EXTAXI_SEP_OUT_DATA1 0xCAFEBABE

/* ---- SMC -> ext_out egress (non-aperture address, {01,smc_id} route) ----
 * The SMC fw opens its outbound egress filter over [SMC_OUT_ADDR, SMC_OUT_END]. */
#define EXTAXI_SMC_OUT_ADDR 0x80001000
#define EXTAXI_SMC_OUT_END 0x800010FF /* main.c SMC_OUT_END */
#define EXTAXI_SMC_OUT_DATA0 0x5A5AA5A5
#define EXTAXI_SMC_OUT_DATA1 0xC001CAFE

/* ---- ROUTE_DONE barrier tokens (ext_in writes, firmware bounded-waits) ---- */
#define EXTAXI_ROUTE_DONE_SMC 0x160D0001 /* ext_in writes at scratch9 */
#define EXTAXI_ROUTE_DONE_SEP 0x160D0002 /* ext_in writes at cold scratch7 */

/* ---- Final PASS / FAIL markers (firmware writes; named pass/fail loops) ---- */
#define EXTAXI_SMC_PASS 0x160C0001 /* SMC final @ scratch10 */
#define EXTAXI_SMC_FAIL 0x160CFFEE /* SMC fail  @ scratch10 */
#define EXTAXI_SEP_PASS 0x160A0001 /* SEP final @ cold scratch6 */
#define EXTAXI_SEP_FAIL 0x160AFFEE /* SEP fail  @ cold scratch6 */

/* ---- Built SMC image drift guards ----
 * The SEP firmware uses these to re-vector/release the SMC, while cocotb independently checks
 * them against the freshly built test.dis/test.preload.hex before loading the image. */
#define EXTAXI_SMC_ENTRY 0xC00601B2 /* RECONCILE vs built image */
#define EXTAXI_SMC_IMAGE_FIRST_WORD 0x41014081

/* ---- Aperture goldens (each firmware programs + reads back its OWN) ----
 * SEP inbound global->local remap (axi_window_remap, sep_system_peripherals.sv:432-435,
 * target_base=0): local = global - sep_global_base, and the access must lie INSIDE the
 * alias window [sep_global_base, sep_global_base + sep_region_size). SEP cold scratch is
 * a LOCAL 0x108020xx register (the address the SEP CPU/internal fabric sees), so the
 * external global address MUST be sep_global_base + local = 0x04000000 + 0x108020xx =
 * 0x148020xx -- NOT 0x048020xx, which remaps to the non-existent local 0x008020xx and
 * DECERRs. The window must also cover local offset 0x1080203f:
 * region_size >= 0x1480203f - 0x04000000 + 1 = 0x10802040, so 0x01000000 is far too small.
 * 0x11000000 gives [0x04000000, 0x15000000), covering all SEP-local 0x10xxxxxx while
 * staying well below the 0x80000000 egress addresses. This same region also feeds the SMU
 * xbar sep_in addr_map (smu_axi_xbar.sv:94-95) so ext_in->SEP decodes to mst0.
 * (SMC differs: its remap target_base is nonzero so global 0x020390xx -> local 0x000390xx
 * is a valid SMC-fabric alias.) */
#define EXTAXI_SEP_GLOBAL_BASE 0x04000000 /* SEP_CPU_CTRL.SEP_GLOBAL_BASE_ADDR */
#define EXTAXI_SEP_REGION_SIZE \
    0x11000000 /* SEP_CPU_CTRL.SEP_REGION_SIZE (covers local 0x10802040) */
#define EXTAXI_SMC_GLOBAL_BASE 0x02000000 /* SMC_BASE_CONFIG.GLOBAL_BASE */
#define EXTAXI_SMC_REGION_SIZE 0x01000000 /* SMC_BASE_CONFIG.REGION_SIZE */

/* ---- ext_in -> aperture route-test data (ext_in writes / reads back) ---- */
#define EXTAXI_SMC_SCRATCH8_DATA 0x11223344 /* ext_in -> SMC scratch8 */
#define EXTAXI_SEP_COLD0_DATA 0x55667788    /* ext_in -> SEP cold scratch0 */

/* ---- ext_in unsupported-route (DECERR) probe address (checked DV-side) ---- */
#define EXTAXI_EXT_IN_DECERR_ADDR 0x80002000 /* outside BOTH apertures */

/* ---- GLOBAL addresses the external tb.ext_in master uses (through apertures) ---- */
#define EXTAXI_SMC_SCRATCH6_GLOBAL 0x020390B0 /* SMC_READY */
#define EXTAXI_SMC_SCRATCH7_GLOBAL 0x020390B8 /* SMC_GO */
#define EXTAXI_SMC_SCRATCH8_GLOBAL 0x020390C0 /* route data */
#define EXTAXI_SMC_SCRATCH9_GLOBAL 0x020390C8 /* ROUTE_DONE_SMC */
/* GLOBAL = SEP_GLOBAL_BASE(0x04000000) + LOCAL(0x108020xx) so the axi_window_remap
 * subtracts back to the real SEP-local cold-scratch register (see derivation above). */
#define EXTAXI_SEP_COLD0_GLOBAL 0x14802000 /* route data      (0x04000000 + 0x10802000) */
#define EXTAXI_SEP_COLD4_GLOBAL 0x14802020 /* SEP_READY       (0x04000000 + 0x10802020) */
#define EXTAXI_SEP_COLD5_GLOBAL 0x14802028 /* SEP_GO          (0x04000000 + 0x10802028) */
#define EXTAXI_SEP_COLD7_GLOBAL 0x14802038 /* ROUTE_DONE_SEP  (0x04000000 + 0x10802038) */

/* ---- LOCAL scratch addresses (firmware-visible; = the register-header symbols) ---- */
#define EXTAXI_SMC_SCRATCH6_LOCAL 0xC00390B0 /* SMC_CPU_CTRL_SCRATCH_6__REG_ADDR */
#define EXTAXI_SMC_SCRATCH7_LOCAL 0xC00390B8 /* SMC_CPU_CTRL_SCRATCH_7__REG_ADDR */
#define EXTAXI_SMC_SCRATCH9_LOCAL 0xC00390C8 /* SMC_CPU_CTRL_SCRATCH_9__REG_ADDR */
#define EXTAXI_SMC_SCRATCH10_LOCAL \
    0xC00390D0 /* SMC_CPU_CTRL_SCRATCH_10__REG_ADDR (not 0x000390D0) */
#ifdef SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR
#define EXTAXI_SEP_COLD4_LOCAL SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(4)
#define EXTAXI_SEP_COLD5_LOCAL SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(5)
#define EXTAXI_SEP_COLD6_LOCAL SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(6)
#define EXTAXI_SEP_COLD7_LOCAL SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(7)
#else
#define EXTAXI_SEP_COLD4_LOCAL 0x10802020
#define EXTAXI_SEP_COLD5_LOCAL 0x10802028
#define EXTAXI_SEP_COLD6_LOCAL 0x10802030
#define EXTAXI_SEP_COLD7_LOCAL 0x10802038
#endif

/* Bind duplicated protocol literals to each owning generated register header.
 * The hex forms stay for the SMC translation unit, which cannot include sep.h.
 * A firmware build must fail if RDL moves a local scratch or a global-address
 * derivation drifts. */
#if defined(SMC_CPU_CTRL_SCRATCH_6__REG_ADDR)
_Static_assert(EXTAXI_SMC_SCRATCH6_LOCAL == SMC_CPU_CTRL_SCRATCH_6__REG_ADDR,
               "SMC scratch6 local address drift");
_Static_assert(EXTAXI_SMC_SCRATCH7_LOCAL == SMC_CPU_CTRL_SCRATCH_7__REG_ADDR,
               "SMC scratch7 local address drift");
_Static_assert(EXTAXI_SMC_SCRATCH9_LOCAL == SMC_CPU_CTRL_SCRATCH_9__REG_ADDR,
               "SMC scratch9 local address drift");
_Static_assert(EXTAXI_SMC_SCRATCH10_LOCAL == SMC_CPU_CTRL_SCRATCH_10__REG_ADDR,
               "SMC scratch10 local address drift");
_Static_assert(EXTAXI_SMC_SCRATCH6_GLOBAL ==
                   (EXTAXI_SMC_GLOBAL_BASE + SMC_CPU_CTRL_SCRATCH_6__REG_ADDR - 0xC0000000u),
               "SMC scratch6 global address drift");
_Static_assert(EXTAXI_SMC_SCRATCH7_GLOBAL ==
                   (EXTAXI_SMC_GLOBAL_BASE + SMC_CPU_CTRL_SCRATCH_7__REG_ADDR - 0xC0000000u),
               "SMC scratch7 global address drift");
_Static_assert(EXTAXI_SMC_SCRATCH8_GLOBAL ==
                   (EXTAXI_SMC_GLOBAL_BASE + SMC_CPU_CTRL_SCRATCH_8__REG_ADDR - 0xC0000000u),
               "SMC scratch8 global address drift");
_Static_assert(EXTAXI_SMC_SCRATCH9_GLOBAL ==
                   (EXTAXI_SMC_GLOBAL_BASE + SMC_CPU_CTRL_SCRATCH_9__REG_ADDR - 0xC0000000u),
               "SMC scratch9 global address drift");
#endif

#if defined(SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR)
_Static_assert(EXTAXI_SEP_COLD0_GLOBAL ==
                   (EXTAXI_SEP_GLOBAL_BASE + SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(0)),
               "SEP cold scratch0 global address drift");
_Static_assert(EXTAXI_SEP_COLD4_GLOBAL ==
                   (EXTAXI_SEP_GLOBAL_BASE + SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(4)),
               "SEP cold scratch4 global address drift");
_Static_assert(EXTAXI_SEP_COLD5_GLOBAL ==
                   (EXTAXI_SEP_GLOBAL_BASE + SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(5)),
               "SEP cold scratch5 global address drift");
_Static_assert(EXTAXI_SEP_COLD7_GLOBAL ==
                   (EXTAXI_SEP_GLOBAL_BASE + SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(7)),
               "SEP cold scratch7 global address drift");
#endif

/* ---- Filter config words (axi_filter FILTER_CONFIG; only bits 0/1/4/8/24 used) ----
 * read_allowed[0] | write_allowed[1] | entry_enabled[4] | allow_ns[8] | allow_burst[24].
 * allow_ns is an EXACT match on AxPROT[1] gated by EnNsFilter (traffic_filter.sv:54)
 * -> program a SECURE rule (allow_ns=0) AND an NS rule (allow_ns=1) over the same
 * range so the leg passes regardless of the initiator's security level.  src_id and
 * group_id are left 0 (ignored: !(|cfg) passes any initiator). */
#define EXTAXI_FILTER_CFG_SECURE 0x0000000001000013ULL /* rd|wr|en|burst, allow_ns=0 */
#define EXTAXI_FILTER_CFG_NS 0x0000000001000113ULL     /* rd|wr|en|burst, allow_ns=1 */
/* Filter-register byte offsets. SEP firmware aliases the generated inbound-filter
 * map; the hex else-branch stays for the SMC translation unit, which cannot
 * include sep.h. The asserts bind the generated offsets to that hex so an RDL
 * layout change fails the SEP firmware build instead of the SMC interop write. */
#ifdef SEP_TOP_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR
#define EXTAXI_FILTER_CFG_OFF \
    (SEP_TOP_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(0) - \
     SEP_TOP_INBOUND_FILTER_CTRL_BASE_ADDR(0))
#define EXTAXI_FILTER_START_OFF \
    (SEP_TOP_INBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR(0) - \
     SEP_TOP_INBOUND_FILTER_CTRL_BASE_ADDR(0))
#define EXTAXI_FILTER_END_OFF \
    (SEP_TOP_INBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR(0) - \
     SEP_TOP_INBOUND_FILTER_CTRL_BASE_ADDR(0))
#define EXTAXI_FILTER_STRIDE SEP_TOP_INBOUND_FILTER_CTRL_STRIDE
_Static_assert(EXTAXI_FILTER_CFG_OFF == 0x0u, "inbound filter CFG offset drift");
_Static_assert(EXTAXI_FILTER_START_OFF == 0x8u, "inbound filter START offset drift");
_Static_assert(EXTAXI_FILTER_END_OFF == 0x10u, "inbound filter END offset drift");
_Static_assert(EXTAXI_FILTER_STRIDE == 0x20u, "inbound filter stride drift");
#else
#define EXTAXI_FILTER_CFG_OFF 0x0u
#define EXTAXI_FILTER_START_OFF 0x8u
#define EXTAXI_FILTER_END_OFF 0x10u
#define EXTAXI_FILTER_STRIDE 0x20u
#endif

/* Firmware poll bound (loop iterations; never hang). Secondary bound only -- the
 * cocotb MONITOR_TIMEOUT is the primary fail-loud gate. Sized wide vs the whole
 * post-boot datapath while bounding every post-egress wait so the firmware always
 * reaches a defined, named PC. */
#define EXTAXI_FW_POLL_LIMIT 200000

#endif /* SMU_SEP_EXT_AXI_PROTOCOL_H */
