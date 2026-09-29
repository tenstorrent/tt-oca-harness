// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU bench constants shared by the environment (cfgs, reference models,
// scoreboard, env) and the sequence library (JTAG operations, scenario
// helpers). Geometry comes from the generated and RTL collateral
// (jtag_inst_reg_pkg, smu_pkg, smc_pkg, sep_pkg, jtag_tap_pkg,
// smc_top_addrmap_pkg); the few bench-only constants cite their source. No
// class lives here: everything is a package-scope type, constant, or
// `function automatic`. The cocotb twin is seq_lib/smu_jtag_helpers.py
// (constants section).

// ---------------------------------------------------------------------------
// Primary TAP of the embedded DTP (smu.sv u_dtp, jtag_ptap_client_* pins).
// ---------------------------------------------------------------------------
localparam int unsigned SmuPtapIrWidth = jtag_inst_reg_pkg::IR_WIDTH;

// Device identification of the embedded DTP PTAP: the smu_pkg::DefaultCfg
// JTAG_IDCODE_* fields smu.sv hands to the DTP (tb_wrapper_top.sv elaborates
// smu_wrapper with the default Cfg) over the IEEE 1149.1 marker bit.
localparam bit [31:0] SmuPtapIdcode = {
  smu_pkg::DefaultCfg.JTAG_IDCODE_SI_REV,
  smu_pkg::DefaultCfg.JTAG_IDCODE_PART_NUM,
  smu_pkg::DefaultCfg.JTAG_IDCODE_MFR_ID,
  1'b1
};

// The IDCODE the bench expects: the configured value, or the documented
// negative-validation corruption (+SMU_PTAP_IDCODE_NEGATIVE flips bit 1 so
// both the reference model and the scenario evidence must FAIL).
function automatic bit [31:0] smu_ptap_expected_idcode(bit negative);
  return negative ? (SmuPtapIdcode ^ 32'h2) : SmuPtapIdcode;
endfunction

// Named-evidence policy of an env-owned aggregate recorder: whether zero
// checks fail the run and which IDs must be present.
typedef struct {
  bit    require_checks;
  string required_ids[$];
} smu_evidence_policy_t;

// Scoreboard feature names of the SMU-level predictors (smu_scoreboard);
// the embedded DTP's features keep the dtp_env_pkg names.
localparam string SmuFeatureIcResetTdr = "ic_reset_tdr";
localparam string SmuFeatureDebugControlTdr = "debug_control_tdr";
localparam string SmuFeatureBootGate = "boot_gate";

// ---------------------------------------------------------------------------
// IC_RESET TDR (PTAP document "IC_RESET Support"; doc/integrator/src/smu.adoc
// "IC_RESET TDR Structure"). LSB-first shift image: bit 0 is reset_hold
// (nearest TDO), port n carries reset_enable at bit 2n+1 and reset_control at
// bit 2n+2, every bit resetting to 1 (reset_enable = 1 is "override
// disabled"). Port 0 is the external slice (nearest TDO), then the SEP
// slice, then the SMC slice (nearest TDI). Each slice is one port per bit of
// its `.ovrd` struct half, so the widths come from the RTL struct types
// smu.sv hands the DTP; the external slice is the PTAP default type, which
// smu_wrapper leaves in place.
// ---------------------------------------------------------------------------
localparam int unsigned SmuIcResetNumSmcPorts = $bits(smc_pkg::jtag_smc_reset_ctrl_ovrd_t);
localparam int unsigned SmuIcResetNumSepPorts = $bits(sep_pkg::jtag_sep_reset_ctrl_ovrd_t);
localparam int unsigned SmuIcResetNumExtPorts = $bits(jtag_tap_pkg::jtag_ic_reset_default_t) / 2;
localparam int unsigned SmuIcResetNumPorts =
    SmuIcResetNumSmcPorts + SmuIcResetNumSepPorts + SmuIcResetNumExtPorts;
localparam int unsigned SmuIcResetLen = 2 * SmuIcResetNumPorts + 1;
localparam int unsigned SmuIcResetExtPort = 0;
localparam int unsigned SmuIcResetSepPortBase = SmuIcResetNumExtPorts;
localparam int unsigned SmuIcResetSmcPortBase = SmuIcResetNumExtPorts + SmuIcResetNumSepPorts;

typedef bit [SmuIcResetLen-1:0] smu_ic_reset_image_t;

// The reset image: every bit 1 (PTAP IC_RESET fields table, Reset column).
localparam smu_ic_reset_image_t SmuIcResetDefault = '1;

// SMC slice port offsets: counted from the TDO end of the slice, the offset
// of a port equals the bit index of its field in the packed
// jtag_smc_reset_ctrl_ovrd_t / _val_t (smc_pkg declares the fields in
// TDI-to-TDO order, and a packed struct places its first field at the MSB).
localparam int unsigned SmuIcResetSmcFuse = 0;
localparam int unsigned SmuIcResetSmcWarm = 1;
localparam int unsigned SmuIcResetSmcCool = 2;
localparam int unsigned SmuIcResetSmcCold = 3;
localparam int unsigned SmuIcResetSmcSsCold0 = 4;
localparam int unsigned SmuIcResetSmcSsWarm0 = SmuIcResetSmcSsCold0 + 32;

function automatic int unsigned smu_ic_reset_enable_bit(int unsigned port);
  return 2 * port + 1;
endfunction

function automatic int unsigned smu_ic_reset_control_bit(int unsigned port);
  return 2 * port + 2;
endfunction

// TDR port index of an SMC-slice offset.
function automatic int unsigned smu_ic_reset_smc_port(int unsigned smc_offset);
  return SmuIcResetSmcPortBase + smc_offset;
endfunction

// One port overridden (reset_enable = 0) driving `control` on its
// reset_control bit, every other port at its reset value, reset_hold kept.
function automatic smu_ic_reset_image_t smu_ic_reset_override_image(int unsigned port,
                                                                    bit control);
  smu_ic_reset_image_t image = SmuIcResetDefault;
  image[smu_ic_reset_enable_bit(port)]  = 1'b0;
  image[smu_ic_reset_control_bit(port)] = control;
  return image;
endfunction

// The active-high override flag and the driven value of one port in an
// image (PTAP "Polarity convention": ovrd = !reset_enable, val =
// reset_control).
function automatic bit smu_ic_reset_ovrd_of(smu_ic_reset_image_t image, int unsigned port);
  return !image[smu_ic_reset_enable_bit(port)];
endfunction

function automatic bit smu_ic_reset_val_of(smu_ic_reset_image_t image, int unsigned port);
  return image[smu_ic_reset_control_bit(port)];
endfunction

// The SMC slice of an image as the struct halves smu.sv exports
// (jtag_smc_reset_ctrl.ovrd / .val): bit k of each half is SMC port k.
function automatic bit [SmuIcResetNumSmcPorts-1:0] smu_ic_reset_smc_ovrd_of(
    smu_ic_reset_image_t image);
  bit [SmuIcResetNumSmcPorts-1:0] v = '0;
  for (int unsigned k = 0; k < SmuIcResetNumSmcPorts; k++)
    v[k] = smu_ic_reset_ovrd_of(image, smu_ic_reset_smc_port(k));
  return v;
endfunction

function automatic bit [SmuIcResetNumSmcPorts-1:0] smu_ic_reset_smc_val_of(
    smu_ic_reset_image_t image);
  bit [SmuIcResetNumSmcPorts-1:0] v = '0;
  for (int unsigned k = 0; k < SmuIcResetNumSmcPorts; k++)
    v[k] = smu_ic_reset_val_of(image, smu_ic_reset_smc_port(k));
  return v;
endfunction

// ---------------------------------------------------------------------------
// DEBUG_CONTROL TDR (PTAP document "Debug Control"): five bits, LSB-first
// boot_stall, boot_stall_ovrd, cla_clock_stop_en, jtag_clock_stop, then the
// read-only cla_clock_stop status; every bit resets to 0.
// ---------------------------------------------------------------------------
localparam int unsigned SmuDebugControlLen = 5;
localparam int unsigned SmuDbgBootStallBit = 0;
localparam int unsigned SmuDbgBootStallOvrdBit = 1;
localparam int unsigned SmuDbgClaClockStopEnBit = 2;
localparam int unsigned SmuDbgJtagClockStopBit = 3;
localparam int unsigned SmuDbgClaClockStopBit = 4;
// The bits software owns; bit 4 is captured status, not register storage.
localparam bit [SmuDebugControlLen-1:0] SmuDebugControlRwMask = 5'b0_1111;

function automatic bit [SmuDebugControlLen-1:0] smu_debug_control_image(
    bit boot_stall, bit boot_stall_ovrd, bit cla_clock_stop_en = 1'b0, bit jtag_clock_stop = 1'b0);
  bit [SmuDebugControlLen-1:0] v = '0;
  v[SmuDbgBootStallBit]      = boot_stall;
  v[SmuDbgBootStallOvrdBit]  = boot_stall_ovrd;
  v[SmuDbgClaClockStopEnBit] = cla_clock_stop_en;
  v[SmuDbgJtagClockStopBit]  = jtag_clock_stop;
  return v;
endfunction

// ---------------------------------------------------------------------------
// SMC-fabric JTAG2AXI bridge as the SMU configures it (doc/integrator/src/
// smu.adoc "SMU Default Parameters": SMC_RD/WR_PL_DEPTH; "AXI Interface
// Configuration": 56-bit address, 64-bit data, AXI4). *_JTAG2AXI_CAPS packs
// [13:12] rd_pl_depth, [11:10] wr_pl_depth, [9:7] data_size (log2 bytes),
// [6:1] addr_size, [0] bus_type (0 = AXI4).
// ---------------------------------------------------------------------------
localparam int unsigned SmuSmcJ2aAddrBits = 56;
localparam int unsigned SmuSmcJ2aDataBits = 64;
localparam bit [13:0] SmuExpectedSmcJ2aCaps = {
  smu_pkg::DefaultCfg.SMC_RD_PL_DEPTH,
  smu_pkg::DefaultCfg.SMC_WR_PL_DEPTH,
  3'($clog2(SmuSmcJ2aDataBits / 8)),
  6'(SmuSmcJ2aAddrBits),
  1'b0
};
localparam int unsigned SmuJ2aCapsLen = 14;

// SMC registers and memory the JTAG2AXI scenario reaches through the bridge
// (generated smc_top_addrmap_pkg): CPU_CTRL SCRATCH_15 (SCRATCH_0 is the live
// boot-ROM mailbox) and the SPM window.
localparam bit [63:0] SmuSmcScratch15Addr =
    64'(smc_top_addrmap_pkg::SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(15));
localparam bit [63:0] SmuSmcSpmBaseAddr = 64'(smc_top_addrmap_pkg::SMC_TOP_SPM_MEMORY_BASE_ADDR);
localparam bit [63:0] SmuSmcSpmSize = 64'(smc_top_addrmap_pkg::SMC_TOP_SPM_MEMORY_SIZE);
