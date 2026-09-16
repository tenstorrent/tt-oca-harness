// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU bench constants shared by the environment (cfgs, scoreboard, env) and
// the sequence library (JTAG operations, scenario helpers). Geometry comes
// from the generated and RTL collateral (jtag_inst_reg_pkg, smu_pkg); the
// few bench-only constants cite their source. No class lives here:
// everything is a package-scope type, constant, or `function automatic`.
// The cocotb twin is seq_lib/smu_jtag_helpers.py (constants section).

// ---------------------------------------------------------------------------
// Primary TAP of the embedded DTP (smu.sv u_dtp, jtag_ptap_client_* pins).
// ---------------------------------------------------------------------------
localparam int unsigned SmuPtapIrWidth = jtag_inst_reg_pkg::IR_WIDTH;

// Device identification of the embedded DTP PTAP: the smu_pkg::DefaultCfg
// JTAG_IDCODE_* fields smu.sv hands to the DTP (tb_top instantiates `smu`
// with the default Cfg) over the IEEE 1149.1 marker bit.
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
