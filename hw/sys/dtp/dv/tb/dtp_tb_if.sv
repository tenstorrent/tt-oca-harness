// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP-local TB interface for the SV-UVM flow: system/power-on resets
// (sequenced by the test) and the DUT-produced one-hot IEEE 1149.1 TAP state
// used by the FSM reference-model checks. Deliberately separate from the
// shared ocah_jtag_if, which carries generic JTAG pins only.
//
// The JTAG2AXI additions carry the test-drivable lifecycle
// debug disables, the SVA suppress knobs, and mirrors of the tb_top
// request-activity pulse counters, so sequences never reach into tb_top
// hierarchy directly. Both AXI responders are shared ocah_axi_vip UVM slave
// agents; error injection is programmed through their slave sequences, not
// TB error ports.

interface dtp_tb_if;

  // Driven by the TB (reset sequencing owned by the test/sequence).
  logic por_rst_n;
  logic sys_rst_n;

  // Driven by the DUT top (jtag_tap_pkg::tap_state_e, one-hot).
  logic [15:0] tap_state;

  // Driven by the DUT top: decoded-IR one-hot observable
  // (jtag_inst_reg_pkg::jtag_instruction_decoded_e) for CHK-IR-DECODE.
  jtag_inst_reg_pkg::jtag_instruction_decoded_e inst_decoded;

  // Driven by the DUT top: boundary-scan chain control observables for the
  // basic-JTAG instruction checks.
  logic jtag_bsr_select;
  logic jtag_bsr_shift_en;
  logic jtag_bsr_capture_en;
  logic jtag_bsr_update_en;

  // Lifecycle debug disables (sep_lifecycle_ctrl_pkg::dbg_disable_t,
  // active-high: 1 = interface disabled). Init '1 = fail-closed, matching
  // the DUT synchronizers' reset value; JTAG2AXI sequences must clear the
  // target's disable first.
  sep_lifecycle_ctrl_pkg::dbg_disable_t dbg_disable = '1;

  // Runtime enable for the shared AXI protocol SVA checkers.
  logic axi_sva_en = 1'b1;

  // Runtime enable for the shared JTAG protocol SVA checker.
  logic jtag_sva_en = 1'b1;

  // Request-activity pulse-counter mirrors (driven by tb_top).
  logic [31:0] smc_axi_awvalid_count;
  logic [31:0] smc_axi_wvalid_count;
  logic [31:0] smc_axi_arvalid_count;
  logic [31:0] smc_otp_axil_awvalid_count;
  logic [31:0] smc_otp_axil_wvalid_count;
  logic [31:0] smc_otp_axil_arvalid_count;
  logic [31:0] sep_otp_axil_awvalid_count;
  logic [31:0] sep_otp_axil_wvalid_count;
  logic [31:0] sep_otp_axil_arvalid_count;

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

  // Scan-network observables (driven by tb_top): iJTAG SIB scan controls,
  // STAP forwarding pins, and the extended STAP host scan controls for
  // the scan-scenario temporal windows.
  logic jtag_dft_secure_select;
  logic jtag_dft_secure_shift_en;
  logic jtag_dft_secure_capture_en;
  logic jtag_dft_secure_update_en;
  logic jtag_dft_select;
  logic jtag_dft_shift_en;
  logic jtag_dft_capture_en;
  logic jtag_dft_update_en;
  logic jtag_dfd_select;
  logic jtag_dfd_shift_en;
  logic jtag_dfd_capture_en;
  logic jtag_dfd_update_en;
  logic jtag_stap_io_tms;
  logic jtag_stap_io_tdo_oen;
  logic jtag_stap_smc_tms;
  logic jtag_stap_smc_tdo_oen;
  logic jtag_stap_sep_tms;
  logic jtag_stap_sep_tdo_oen;
  logic jtag_stap_extra0_tms;
  logic jtag_stap_extra0_tdo_oen;
  logic jtag_stap_host_select;
  logic jtag_stap_host_shift_en;
  logic jtag_stap_host_capture_en;
  logic jtag_stap_host_update_en;

  // Cross-trigger CTM/CTP pin surface. Request-side vectors are driven by
  // the XTRIG sequences (init '0 = quiescent, matching the cocotb agent's
  // idle state); the remaining vectors are DUT-driven observables. The
  // internal-CT ports use the src/dst req-ack pairs; the external CTPs use
  // the pad-cell din/dout/en quartets.
  logic [dtp_pkg::DEFAULT_NUM_INT_CT-1:0] xtrig_ctm_src_ack = '0;
  logic [dtp_pkg::DEFAULT_NUM_INT_CT-1:0] xtrig_ctm_dst_req = '0;
  logic [dtp_pkg::DEFAULT_NUM_CTP-1:0] xtrig_ctp_req_out_din = '0;
  logic [dtp_pkg::DEFAULT_NUM_CTP-1:0] xtrig_ctp_req_in_din = '0;
  logic [dtp_pkg::DEFAULT_NUM_CTP-1:0] xtrig_ctp_ack_in_din = '0;
  logic [dtp_pkg::DEFAULT_NUM_CTP-1:0] xtrig_ctp_ack_out_din = '0;

  logic [dtp_pkg::DEFAULT_NUM_INT_CT-1:0] xtrig_ctm_src_req;
  logic [dtp_pkg::DEFAULT_NUM_INT_CT-1:0] xtrig_ctm_dst_ack;
  logic [dtp_pkg::DEFAULT_NUM_CTP-1:0] xtrig_ctp_req_out_dout;
  logic [dtp_pkg::DEFAULT_NUM_CTP-1:0] xtrig_ctp_req_out_dout_en;
  logic [dtp_pkg::DEFAULT_NUM_CTP-1:0] xtrig_ctp_req_out_din_en;
  logic [dtp_pkg::DEFAULT_NUM_CTP-1:0] xtrig_ctp_req_in_dout;
  logic [dtp_pkg::DEFAULT_NUM_CTP-1:0] xtrig_ctp_req_in_dout_en;
  logic [dtp_pkg::DEFAULT_NUM_CTP-1:0] xtrig_ctp_req_in_din_en;
  logic [dtp_pkg::DEFAULT_NUM_CTP-1:0] xtrig_ctp_ack_in_dout;
  logic [dtp_pkg::DEFAULT_NUM_CTP-1:0] xtrig_ctp_ack_in_dout_en;
  logic [dtp_pkg::DEFAULT_NUM_CTP-1:0] xtrig_ctp_ack_in_din_en;
  logic [dtp_pkg::DEFAULT_NUM_CTP-1:0] xtrig_ctp_ack_out_dout;
  logic [dtp_pkg::DEFAULT_NUM_CTP-1:0] xtrig_ctp_ack_out_dout_en;
  logic [dtp_pkg::DEFAULT_NUM_CTP-1:0] xtrig_ctp_ack_out_din_en;

  // XTRIG CSR request-activity pulse-counter mirrors (driven by tb_top).
  logic [31:0] xtrig_axil_awvalid_count;
  logic [31:0] xtrig_axil_wvalid_count;
  logic [31:0] xtrig_axil_arvalid_count;

endinterface : dtp_tb_if
