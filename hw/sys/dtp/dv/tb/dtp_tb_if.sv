// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP control-domain TB interface, shared by the cocotb and SV-UVM flows:
// the system clock and its period, the test-sequenced resets and their
// assertion counters, the lifecycle debug disables, the TAP-state and
// debug-TDR observables the checkers read, the request-activity pulse
// counters tb_top derives from the bus pins, and the SVA enables.
// The scan-network observables live in dtp_scan_if and the cross-trigger
// pins in dtp_xtrig_if; the primary TAP pins are on the shared ocah_jtag_if.
//
// cocotb deposits the clock, the resets, and the stimulus members through
// hierarchical handles (env/dtp_tb_if.py); SV-UVM sequences reach the same
// members through the virtual interface, and the harness block in tb_top
// generates the clock from clk_period_ns.

interface dtp_tb_if;

  // System-clock period the harness clock generator reads, set by the env
  // from dtp_env_cfg (the test cfg randomizes it from the runner seed).
  int unsigned clk_period_ns = 10;

  // System clock: cocotb drives it with Clock(); the SV-UVM harness toggles
  // it every half period.
  logic clk = 1'b0;

  // Driven by the TB (reset sequencing owned by the test/sequence).
  logic por_rst_n;
  logic sys_rst_n;

  // Reset-assertion counters (driven by tb_top): the scoreboard predictors
  // re-baseline the CSR shadow and the TAP instruction on them.
  logic [31:0] sys_rst_assert_count;
  logic [31:0] por_assert_count;

  // Driven by the DUT top (jtag_tap_pkg::tap_state_e, one-hot).
  logic [15:0] tap_state;

  // Driven by the DUT top: decoded-IR one-hot observable
  // (jtag_inst_reg_pkg::jtag_instruction_decoded_e) for CHK-IR-DECODE.
  jtag_inst_reg_pkg::jtag_instruction_decoded_e inst_decoded;

  // Lifecycle debug disables (sep_lifecycle_ctrl_pkg::dbg_disable_t,
  // active-high: 1 = interface disabled). Init '1 = fail-closed, matching
  // the DUT synchronizers' reset value; JTAG2AXI sequences must clear the
  // target's disable first. cocotb packs the struct from its field table
  // in declaration order.
  sep_lifecycle_ctrl_pkg::dbg_disable_t dbg_disable = '1;

  // Runtime enable for the shared AXI protocol SVA checkers.
  logic axi_sva_en = 1'b1;

  // Runtime enable for the shared JTAG protocol SVA checker.
  logic jtag_sva_en = 1'b1;

  // Request-activity pulse-counter mirrors (driven by tb_top): no-activity
  // security evidence sampled from the bus pins.
  logic [31:0] smc_axi_awvalid_count;
  logic [31:0] smc_axi_wvalid_count;
  logic [31:0] smc_axi_arvalid_count;
  logic [31:0] smc_otp_axil_awvalid_count;
  logic [31:0] smc_otp_axil_wvalid_count;
  logic [31:0] smc_otp_axil_arvalid_count;
  logic [31:0] sep_otp_axil_awvalid_count;
  logic [31:0] sep_otp_axil_wvalid_count;
  logic [31:0] sep_otp_axil_arvalid_count;
  logic [31:0] xtrig_axil_awvalid_count;
  logic [31:0] xtrig_axil_wvalid_count;
  logic [31:0] xtrig_axil_arvalid_count;

  // Debug-TDR observables (driven by tb_top): DEBUG_CONTROL clock-stop /
  // boot-stall outputs and the flattened IC_RESET slice outputs.
  logic stop_clks;
  logic cla_clock_stop_en;
  logic jtag_boot_stall;
  logic jtag_boot_stall_ovrd;
  logic jtag_ic_reset_smc_ovrd;
  logic jtag_ic_reset_smc_ctrl_n;
  logic jtag_ic_reset_sep_ovrd;
  logic jtag_ic_reset_sep_ctrl_n;
  logic jtag_ic_reset_ext_ovrd;
  logic jtag_ic_reset_ext_ctrl_n;

  // CLA clock-stop request vector (driven by debug-TDR sequences; init
  // quiescent so unrelated tests see no requests).
  logic [dtp_pkg::DEFAULT_NUM_CLK_STOP_REQ-1:0] xtrig_clk_stop_req = '0;

endinterface : dtp_tb_if
