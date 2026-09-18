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

// EMULATION is the OCAH emulation-view name. No vendor alias maps from it.
// PULP_FPGA_EMUL is an FPGA clock-mux path, not this view.

/*
  Unmapped vendor defines
  -----------------------
  Names vendored RTL still tests that this file does not derive from an OCAH
  define. Identity globals (SYNTHESIS, SIMULATION, VERILATOR, XSIM, VCS, UVM,
  YOSYS, FORMAL) are the OCAH names. Mapped aliases above are omitted here.

  chipsalliance/i3c-core
  - I3C_USE_AXI: header default in i3c_defines.svh selects the AXI CSR path.
  - I3C_USE_AHB: AHB CSR alternative; not selected.
  - I3C_USE_AXI_LITE: no vendor reader.
  - CONTROLLER_SUPPORT / TARGET_SUPPORT: header defaults both to 1.
  - CALIPTRA_AXI_SUB_EX_EN: extra AXI subordinate features; unset.
  - AXI_ID_FILTERING: optional AXI ID filter ports; unset.

  chipsalliance/adams-bridge
  - CALIPTRA: Bender define; Caliptra KV / SoC ports on abr_top.
  - TECH_SPECIFIC_ICG: skip the behavioural ICG; unset (behavioural gate).
  - ABR_PRIM_DEFAULT_IMPL: generic prim impl; header default.
  - ABR_INC_ASSERT: derived in abr_prim_assert.sv from VERILATOR / SYNTHESIS.
  - ABR_ASSERT_ON: enables abr_sva helper macros; unset.

  chipsalliance/caliptra-rtl (and the i3c-core third_party copy)
  - CALIPTRA_INC_ASSERT: derived in caliptra_prim_assert.sv from VERILATOR /
    SYNTHESIS / YOSYS.
  - CLP_ASSERT_ON: enables caliptra_sva / i3c_sva helpers; unset.

  chipsalliance/Cores-VeeR-EL2
  - RV_BUILD_AXI4: snapshot common_defines.vh already defines it.
  - RV_BUILD_AHB_LITE / RV_BUILD_AXI_NATIVE: AHB / unused native AXI; not in
    the SEP snapshot.
  - TECH_SPECIFIC_EC_RV_ICG: Bender define; selects the overlay ICG.
  - TEC_RV_ICG / USER_EC_RV_ICG: snapshot values naming gate modules, not
    command-line selectors.
  - RV_ASSERT_ON: VeeR inline asserts; unset.
  - RV_CLOCKGATE: #0 $strobe clock-gate debug; unset.
  - RV_FPGA_OPTIMIZE / RV_PHYSICAL: FPGA / physical-view branches.
  - RV_USER_MODE / RV_SMEPMP: user-mode and PMP; snapshot config.
  - RV_LOCKSTEP_ENABLE / RV_LOCKSTEP_REGFILE_ENABLE: lockstep compile; unset
    in the SEP snapshot.
  - RV_ICCM_ENABLE / RV_DCCM_ENABLE / RV_*_NUM_BANKS_*: memory geometry in
    the VeeR testbench and snapshot, not OCAH command-line names.
  - RV_OPENOCD_TEST / DSIM: VeeR upstream TB / riscv-dv only.

  lowRISC/opentitan
  - OCAH_OT_INC_ASSERT: derived in prim_assert.sv from VERILATOR / SYNTHESIS
    / YOSYS.
  - FPV_ON / FPV_ALERT_NO_SIGINT_ERR / FPV_SEC_CM_ON: formal-only arms.
  - SYNTHESIS_MEMORY_BLACK_BOXING: keep memory models unless set.

  pulp-platform/common_cells
  - OCAH_PULP_INC_ASSERT: derived in assertions.svh.
  - ASSERTS_OFF: turns off OCAH_PULP_INC_ASSERT; Verilator DUT flags and lint.
  - ASSERTS_OVERRIDE_ON: forces PULP macros on; unset.
  - COMMON_CELLS_ASSERTS_OFF: strips inline module-body asserts. OCAH already
    uses this spelling on every native tool via native.toml.
  - PULP_FPGA_EMUL: FPGA clock-mux; not EMULATION.
  - PULP_DFT: DFT clock-mux; unset.
  - NO_SYNOPSYS_FF: Verilator path in registers.svh defines this itself.

  pulp-platform/axi
  - QUESTA: CDC / demux workarounds; some files `define TARGET_VSIM from it.
  - TARGET_VSIM: Questa demux workarounds.
  - TARGET_SIMULATION: axi_dumper.sv only; not on DUT filelists.
  - TARGET_XILINX / TARGET_GENUS / TARGET_VIVADO: FPGA / synth-tool quirks.

  pulp-platform/idma
  - TARGET_SYNTHESIS / TARGET_VERILATOR / TARGET_XSIM: mapped above. Remaining
    IDMA_* names are typedef / tracer APIs, not command-line knobs.

  tenstorrent/aou
  - TWO_PHY: dual-PHY compile.
  - ASSERTION_ON: AOU inline asserts; unset.
  - AXI_UP_RS_EN: AXI-up register slice.

  tenstorrent/tt-hw-debug
  - ASSERTION_ENABLE: debug-block asserts; unset.

  tenstorrent/tt-picorv32
  - RISCV_FORMAL / RISCV_FORMAL_ALTOPS / RISCV_FORMAL_BLACKBOX_ALU /
    RISCV_FORMAL_BLACKBOX_REGS: formal TB.
  - PICORV32_REGS / PICORV32_TESTBUG_* / DEBUG / DEBUGNETS / DEBUGREGS /
    DEBUGASM: core/debug compile knobs.
*/

`endif  // OCAH_VENDOR_DEFINES_SVH
