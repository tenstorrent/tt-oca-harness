// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

`ifndef OCAH_VENDOR_DEFINES_SVH
`define OCAH_VENDOR_DEFINES_SVH

// Force-include this header (or use an OCAH flow that already does). Adopters
// set the OCAH names; this file defines the vendor aliases those names imply.
// Command-line `+define+` is global; a `define here is visible only in
// compilation units that include this file.

`ifdef SYNTHESIS
`ifndef TARGET_SYNTHESIS
`define TARGET_SYNTHESIS
`endif
`endif

`ifdef SIMULATION
`ifndef ABR_SIMULATION
`define ABR_SIMULATION
`endif
`endif

`ifdef VERILATOR
`ifndef TARGET_VERILATOR
`define TARGET_VERILATOR
`endif
`endif

`ifdef XSIM
`ifndef TARGET_XSIM
`define TARGET_XSIM
`endif
`endif

// EMULATION keeps PULP assertion macros compiled when SYNTHESIS is also set.
// PULP_FPGA_EMUL is an FPGA clock-mux path, not this view.
`ifdef EMULATION
`ifndef ASSERTS_OVERRIDE_ON
`define ASSERTS_OVERRIDE_ON
`endif
`endif

/*
  Unmapped vendor defines
  -----------------------
  Names vendored RTL still tests that this file does not derive from an OCAH
  define. Identity globals (SYNTHESIS, SIMULATION, VERILATOR, XSIM, VCS, UVM,
  YOSYS, FORMAL) are the OCAH names. Mapped aliases above are omitted here.
  None of the names below alias from SYNTHESIS, SIMULATION, VERILATOR, XSIM,
  EMULATION, or FORMAL.

  chipsalliance/i3c-core
  - I3C_USE_AXI: i3c_defines.svh already `define I3C_USE_AXI 1. The OCAH wrap
    instantiates the AXI CSR ports. Do not restate (redefinition).
  - I3C_USE_AHB: AHB CSR ports. i3c.sv is `ifdef I3C_USE_AHB `elsif I3C_USE_AXI.
    The wrap has no AHB ports. Leave unset.
  - I3C_USE_AXI_LITE: no vendor reader. The wrap presents AXI-Lite signalling
    and drives AXI4 single-beat into the core; that is not this name.
  - CONTROLLER_SUPPORT / TARGET_SUPPORT: i3c_defines.svh already defines both
    to 1. The wrap always connects DAT/DCT/RLT (controller) and recovery
    (target) ports. Do not restate.
  - CALIPTRA_AXI_SUB_EX_EN: AxLOCK exclusive-access monitor in i3c_axi_sub.
    The wrap ties awlock/arlock to 0. Leave unset.
  - AXI_ID_FILTERING: adds disable_id_filtering_i / priv_ids_i on i3c. The wrap
    does not have those ports. Leave unset.

  chipsalliance/adams-bridge
  - CALIPTRA: Caliptra KV / SoC ports on abr_top. The Bender `sep` Adams Bridge
    source group sets it with SEP_ABR_EN. Not a global OCAH default; this
    header must not define it.
  - TECH_SPECIFIC_ICG: Bender `sep` Adams Bridge source group. Skips the latch
    in abr_icg.sv; overlay abr_clk_gate instantiates prim_clock_gating with te as
    DFT test-enable. Not derived from SYNTHESIS (lint/Yosys set that view; the
    foundry cell is `-t synth`).
  - ABR_PRIM_DEFAULT_IMPL: each abr_prim_* already defaults to ImplGeneric.
    Overlay abr_prim_generic_{flop,buf,flop_en} instantiate prim_flop /
    prim_buf / prim_flop_en. Do not restate.
  - ABR_INC_ASSERT: derived in abr_prim_assert.sv (dummy on VERILATOR /
    SYNTHESIS, defined otherwise). Do not restate.
  - ABR_ASSERT_ON: opt-in concurrent SVA in abr_sva.svh and ntt_butterfly2x2.
    Independent of ABR_INC_ASSERT; a global set would elaborate those asserts
    on Verilator too. Leave unset.

  chipsalliance/caliptra-rtl (and the i3c-core third_party copy)
  - CALIPTRA_INC_ASSERT: derived in caliptra_prim_assert.sv (dummy on
    VERILATOR / SYNTHESIS, defined on YOSYS and the else VCS/Xcelium path).
    Same tool keys as ABR_INC_ASSERT / OCAH_OT_INC_ASSERT. Do not restate.
  - CLP_ASSERT_ON: opt-in concurrent SVA in caliptra_sva.svh and i3c_sva.svh
    (I3CCSR.sv, i2c_controller_fsm.sv). Independent of CALIPTRA_INC_ASSERT;
    a global set would elaborate those asserts on Verilator too. Leave unset.

  chipsalliance/Cores-VeeR-EL2
  - RV_BUILD_AXI4: snapshot common_defines.vh already `define RV_BUILD_AXI4 1.
    el2_veer_wrapper.sv tests it. Do not restate (redefinition).
  - RV_BUILD_AHB_LITE: AHB ports on el2_veer_wrapper. Snapshot is AXI. Leave
    unset.
  - RV_BUILD_AXI_NATIVE: snapshot already `define RV_BUILD_AXI_NATIVE 1. No
    `ifdef reader. Do not restate.
  - TECH_SPECIFIC_EC_RV_ICG: Bender `sep_el2` source group. Skips the latch in
    beh_lib.sv; overlay user_clock_gate instantiates prim_clock_gating. Not derived
    from SYNTHESIS (lint/Yosys set that view; the foundry cell is `-t synth`).
    This header must not define it.
  - TEC_RV_ICG / USER_EC_RV_ICG: snapshot values naming the behavioural gate
    (`clockhdr`) and overlay (`user_clock_gate`). Not command-line selectors.
    Do not restate.
  - RV_ASSERT_ON: opt-in VeeR concurrent SVA (el2_veer.sv, el2_lsu.sv, tlu).
    Independent of OCAH_INC_ASSERT; a global set would elaborate those asserts
    on Verilator too. Leave unset.
  - RV_CLOCKGATE: #0 $strobe ICG debug in beh_lib.sv. Leave unset.
  - RV_FPGA_OPTIMIZE: FPGA ICG/clock bypass in beh_lib and IFU/LSU. Snapshot
    generated with fpga_optimize=0. Not a global FPGA alias. Leave unset.
  - RV_PHYSICAL: PD snapshot pd_defines.vh (not on the Bender filelist) sets
    it and `undef`s TEC_RV_ICG. Relaxes rvdffe WIDTH checks. Leave unset.
  - RV_USER_MODE / RV_SMEPMP: snapshot already defines both to 1. Do not
    restate.
  - RV_LOCKSTEP_ENABLE / RV_LOCKSTEP_REGFILE_ENABLE: snapshot generated with
    both off. sep_cpu.sv only connects VeeR lockstep ports when the first is
    set. Leave unset.
  - RV_ICCM_ENABLE / RV_DCCM_ENABLE / RV_*_NUM_BANKS_*: snapshot memory
    geometry. Not OCAH command-line names. Do not restate.
  - RV_OPENOCD_TEST / DSIM: VeeR upstream tb_top / riscv-dv only. Leave unset.

  lowRISC/opentitan
  - OCAH_OT_INC_ASSERT: derived in prim_assert.sv (dummy path on VERILATOR /
    SYNTHESIS, defined on YOSYS and the else VCS/Xcelium path). Same tool keys
    as ABR_INC_ASSERT / CALIPTRA_INC_ASSERT. Yosys synth prepends a shim so
    yosys-slang's YOSYS predefine does not enable it. Do not restate.
  - FPV_ON: formal-only ASSUME_FPV / COVER_FPV in prim_assert.sv. DTP sby
    passes FORMAL, not this name. A global set would elaborate those assumes
    on DV. Leave unset.
  - FPV_ALERT_NO_SIGINT_ERR: drops sigint assertions on prim_alert_sender /
    prim_diff_decode and enables FPV assumes. Leave unset.
  - FPV_SEC_CM_ON: no OpenTitan reader. ABR abr_prim_count.sv leaves fpv_force
    undriven when set. Leave unset.
  - SYNTHESIS_MEMORY_BLACK_BOXING: empties prim_ram_1p / prim_ram_1r1w /
    prim_ram_2p bodies for GTECH experiments. OCAH compiles those models
    (including ABR SRAMs via prim_ram_1r1w). Leave unset.

  pulp-platform/common_cells
  - OCAH_PULP_INC_ASSERT: derived in assertions.svh (off on ASSERTS_OFF /
    SYNTHESIS / XSIM, on whenever ASSERTS_OVERRIDE_ON is set, which EMULATION
    maps above). Does not test VERILATOR. Do not restate.
  - ASSERTS_OFF: Verilator DUT flags (smc, smu, dtp) and Verilator lint. Not
    on VCS/Xcelium (PULP macros stay on). Not an alias of VERILATOR. Leave
    unset here.
  - COMMON_CELLS_ASSERTS_OFF: strips inline module-body asserts. Native
    `[target_defaults.default].defines` already sets it on every native tool.
    Do not restate (redefinition). Lint/synth already empty those macros via
    SYNTHESIS.
  - PULP_FPGA_EMUL: FPGA ICG/clock-mux in deprecated common_cells files that
    are not on the OCAH compile. Not EMULATION. Leave unset.
  - PULP_DFT: DFT clock-mux in deprecated clock_divider_counter.sv (not on
    the compile). Leave unset.
  - NO_SYNOPSYS_FF: read only by registers.svh, which no OCAH source includes;
    the vendored sources use ocah_registers.svh, whose sync_set_reset pragmas
    test VERILATOR. Leave unset.

  pulp-platform/axi
  - QUESTA: flattens CDC FIFO payload types in axi_cdc_*.sv. Demux files
    `define TARGET_VSIM from it. Questa-only; the $bits flatten is the
    workaround VCS cannot use. Leave unset.
  - TARGET_VSIM: Questa demux spill_register flatten (axi_lite_demux,
    axi5_lite_demux*). Derived from QUESTA in those files. Leave unset.
  - TARGET_SIMULATION: $fopen tracer in axi_dumper.sv. That file is Bender
    target axi_simulation; no OCAH flow passes that target. Not an alias of
    SIMULATION. Leave unset.
  - TARGET_XILINX: xpm_fifo in axi_fifo_delay_dyn.sv. No OCAH FPGA view.
    Leave unset.
  - TARGET_GENUS: skips axi_xbar_unmuxed_intf (Genus cannot take an array of
    interfaces). Nested under `ifndef VCS. Leave unset.
  - TARGET_VIVADO: Vivado unused-pin workaround in common_cells unread.sv,
    not AXI. Leave unset.

  pulp-platform/idma
  - TARGET_SYNTHESIS / TARGET_VERILATOR / TARGET_XSIM: mapped above from
    SYNTHESIS / VERILATOR / XSIM. guard.svh IDMA_NONSYNTH_BLOCK already tests
    both the TARGET_* and identity names. Do not restate.
  - IDMA_TYPEDEF_*: typedef helpers in typedef.svh. idma_wrapper.sv invokes
    them. Not command-line knobs.
  - IDMA_TRACER_*: overlay tracer.svh helpers. Bodies nest SYNTHESIS then
    VERILATOR. Not command-line knobs.

  tenstorrent/aou
  - TWO_PHY: second-PHY ports on AOU_TOP. Integrator pairs it with FDI_CONFIG
    TP_* values. AOU filelist.f leaves it unset (single-PHY). This header
    must not define it.
  - ASSERTION_ON: opt-in concurrent SVA (AOU_EARLY_TABLE.sv, AXI mux helpers).
    Independent of OCAH_INC_ASSERT; a global set would elaborate those
    asserts on Verilator too. Leave unset.
  - AXI_UP_RS_EN: optional AW/W register-slice FIFO in AOU_AXI_UP.v. Not a
    view alias. Leave unset.

  tenstorrent/tt-hw-debug
  - ASSERTION_ENABLE: opt-in ASSERT_MACRO in trace_sink.sv and
    generic_axilitetommr.sv. Independent of OCAH_INC_ASSERT; a global set
    would elaborate those asserts on Verilator too. Leave unset.

  tenstorrent/tt-picorv32
  - RISCV_FORMAL: adds RVFI ports on picorv32 / picorv32_axi / picorv32_wb.
    picorv32_wrapper.sv (SEP key_manager) does not connect them. Leave unset.
  - RISCV_FORMAL_ALTOPS: replaces mul/div results with XOR hashes in
    picorv32_pcpi_{div,fast_mul}.sv. Leave unset.
  - RISCV_FORMAL_BLACKBOX_ALU / RISCV_FORMAL_BLACKBOX_REGS: $anyseq ALU and
    register-file reads in picorv32.sv. Leave unset.
  - PICORV32_REGS: picorv32.sv already `define PICORV32_REGS picorv32_regs.
    Do not restate.
  - PICORV32_TESTBUG_*: injects register-file / RVFI bugs in picorv32.sv.
    Leave unset.
  - DEBUG / DEBUGNETS / DEBUGREGS / DEBUGASM: decode $display, keep nets,
    debug register taps. DEBUG is a generic name; a header set would leak
    into every compilation unit. Leave all unset.
*/

`endif  // OCAH_VENDOR_DEFINES_SVH
