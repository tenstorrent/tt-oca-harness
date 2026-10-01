// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU debug-bridge functional coverage, from the SMU-JTAG2AXI-SMC,
// SMU-OTPAXI-SMC, SMU-OTPAXI-SEP, SMU-LC-DBGDIS and INT-LC-DBG-BRIDGE
// scenarios of the feature list: the three DTP bridges SMU wires into the
// chiplet, and the lifecycle debug-disable slice that gates them apart.
//
// One passive, signal-driven module. The three bridge buses are smu-internal
// nets between u_dtp and its targets, so the bench flattens them at its top
// level and passes the handshake and response pins in; no hierarchy is
// referenced here.
//
// A bridge point fires on the response handshake, which only a completed
// transaction produces. The gating points fire on the debug-disable slice
// rising, or on a counted window in which the gate stayed asserted and the
// fabric bridge stayed silent -- so "the gate blocks it" is a measured
// silence rather than the absence of stimulus.
//
// SEP PRESENCE: the gated points and the SEP OTP bridge points sit in the
// `g_sep` generate block, so a SEP=0 build carries no unhittable point and
// one coverage policy can grade both elaborations.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use. Every register
// carries a reset branch.

`include "ocah_fcov_macros.svh"

module smu_dbg_fcov #(
  // 0 on an elaboration without SEP. Two things the SEP supplies disappear
  // there: the lifecycle debug-disable slice, which smu.sv's gen_no_sep
  // branch ties to '0, and the SEP OTP target, which that branch replaces
  // with an AXI-Lite DECERR error slave. Points that need the gate asserted
  // or an OKAY response from the SEP OTP bridge are dropped rather than
  // carried unhittable.
  parameter bit SepPresent = 1'b1
) (
  input wire clk_smu_i,
  input wire rst_primary_smc_clk_ni,

  // SMC fabric JTAG2AXI bridge (AXI4) between u_dtp and the SMC fabric.
  input wire smc_dbg_awvalid_i,
  input wire smc_dbg_arvalid_i,
  input wire smc_dbg_bvalid_i,
  input wire smc_dbg_bready_i,
  input wire [1:0] smc_dbg_bresp_i,
  input wire smc_dbg_rvalid_i,
  input wire smc_dbg_rready_i,
  input wire smc_dbg_rlast_i,
  input wire [1:0] smc_dbg_rresp_i,

  // SMC OTP JTAG2AXI bridge (AXI4-Lite).
  input wire smc_otp_bvalid_i,
  input wire smc_otp_bready_i,
  input wire [1:0] smc_otp_bresp_i,
  input wire smc_otp_rvalid_i,
  input wire smc_otp_rready_i,
  input wire [1:0] smc_otp_rresp_i,

  // SEP OTP JTAG2AXI bridge (AXI4-Lite).
  input wire sep_otp_bvalid_i,
  input wire sep_otp_bready_i,
  input wire [1:0] sep_otp_bresp_i,
  input wire sep_otp_rvalid_i,
  input wire sep_otp_rready_i,
  input wire [1:0] sep_otp_rresp_i,

  // Lifecycle debug-disable slice as u_dtp receives it.
  input wire dbg_disable_smc_jtag2axi_i,
  input wire dbg_disable_smc_otp_i,
  input wire dbg_disable_sep_otp_i
);

  localparam logic [1:0] RespOkay = 2'b00;
  localparam logic [7:0] QuietWindow = 8'd255;

  wire in_reset = (rst_primary_smc_clk_ni !== 1'b1);

  // ------------------------------------------------------------------
  // Completed bridge transactions, taken at the response handshake.
  // ------------------------------------------------------------------
  wire smc_dbg_b_hs = (smc_dbg_bvalid_i === 1'b1) && (smc_dbg_bready_i === 1'b1);
  wire smc_dbg_r_hs = (smc_dbg_rvalid_i === 1'b1) && (smc_dbg_rready_i === 1'b1)
      && (smc_dbg_rlast_i === 1'b1);
  wire smc_otp_b_hs = (smc_otp_bvalid_i === 1'b1) && (smc_otp_bready_i === 1'b1);
  wire smc_otp_r_hs = (smc_otp_rvalid_i === 1'b1) && (smc_otp_rready_i === 1'b1);
  wire sep_otp_b_hs = (sep_otp_bvalid_i === 1'b1) && (sep_otp_bready_i === 1'b1);
  wire sep_otp_r_hs = (sep_otp_rvalid_i === 1'b1) && (sep_otp_rready_i === 1'b1);

  wire jtag2axi_write_reaches_smc_csr_e = smc_dbg_b_hs && (smc_dbg_bresp_i == RespOkay);
  wire jtag2axi_read_returns_csr_value_e = smc_dbg_r_hs && (smc_dbg_rresp_i == RespOkay);
  wire smc_otp_write_response_returned_e = smc_otp_b_hs;
  wire smc_otp_read_response_returned_e = smc_otp_r_hs;
  `OCAH_FCOV_COVER(c_jtag2axi_write_reaches_smc_csr, jtag2axi_write_reaches_smc_csr_e, clk_smu_i,
                   in_reset)
  `OCAH_FCOV_COVER(c_jtag2axi_read_returns_csr_value, jtag2axi_read_returns_csr_value_e, clk_smu_i,
                   in_reset)
  `OCAH_FCOV_COVER(c_smc_otp_write_response_returned, smc_otp_write_response_returned_e, clk_smu_i,
                   in_reset)
  `OCAH_FCOV_COVER(c_smc_otp_read_response_returned, smc_otp_read_response_returned_e, clk_smu_i,
                   in_reset)

  // ------------------------------------------------------------------
  // Debug-disable gating and the SEP OTP bridge. The gate is a level the
  // lifecycle controller holds, so the "applied" point is its rising edge
  // and the "blocked" point is a counted window over which the gate stayed
  // asserted and the fabric bridge launched nothing.
  //
  // Only elaborated with SEP present: without it the whole slice is a
  // constant '0 and the SEP OTP target is a DECERR error slave, so the gate
  // never rises and no OKAY ever comes back from that bridge.
  // ------------------------------------------------------------------
  if (SepPresent) begin : g_sep
    wire sep_otp_write_response_returned_e = sep_otp_b_hs && (sep_otp_bresp_i == RespOkay);
    wire sep_otp_read_response_returned_e = sep_otp_r_hs && (sep_otp_rresp_i == RespOkay);
    `OCAH_FCOV_COVER(c_sep_otp_write_response_returned, sep_otp_write_response_returned_e,
                     clk_smu_i, in_reset)
    `OCAH_FCOV_COVER(c_sep_otp_read_response_returned, sep_otp_read_response_returned_e, clk_smu_i,
                     in_reset)

    wire smc_dbg_launch = (smc_dbg_awvalid_i === 1'b1) || (smc_dbg_arvalid_i === 1'b1);
    wire fabric_gated = (dbg_disable_smc_jtag2axi_i === 1'b1);

    logic gate_q;
    logic [7:0] quiet_cnt_q;
    always_ff @(posedge clk_smu_i) begin
      if (in_reset) begin
        gate_q <= 1'b0;
        quiet_cnt_q <= '0;
      end else begin
        gate_q <= dbg_disable_smc_jtag2axi_i;
        if (!fabric_gated || smc_dbg_launch) quiet_cnt_q <= '0;
        else if (quiet_cnt_q != QuietWindow) quiet_cnt_q <= quiet_cnt_q + 8'd1;
      end
    end

    wire gate_rose_e = fabric_gated && (gate_q === 1'b0);
    wire quiet_window_done = fabric_gated && !smc_dbg_launch
        && (quiet_cnt_q == QuietWindow - 8'd1);
    wire otp_bridges_enabled =
        (dbg_disable_smc_otp_i === 1'b0) && (dbg_disable_sep_otp_i === 1'b0);

    wire dbg_disable_blocks_smc_fabric_bridge_e = gate_rose_e;
    wire no_axi_traffic_observed_e = quiet_window_done;
    wire smc_otp_bridge_enabled_under_dbg_disable_e =
        gate_rose_e && (dbg_disable_smc_otp_i === 1'b0);
    wire sep_otp_bridge_enabled_under_dbg_disable_e =
        gate_rose_e && (dbg_disable_sep_otp_i === 1'b0);
    wire fabric_bridge_blocked_and_otp_bridges_enabled_e =
        quiet_window_done && otp_bridges_enabled;
    wire smc_otp_access_succeeds_while_fabric_blocked_e = fabric_gated
        && ((smc_otp_b_hs && (smc_otp_bresp_i == RespOkay))
            || (smc_otp_r_hs && (smc_otp_rresp_i == RespOkay)));
    wire sep_otp_access_succeeds_while_fabric_blocked_e = fabric_gated
        && ((sep_otp_b_hs && (sep_otp_bresp_i == RespOkay))
            || (sep_otp_r_hs && (sep_otp_rresp_i == RespOkay)));
    `OCAH_FCOV_COVER(c_dbg_disable_blocks_smc_fabric_bridge, dbg_disable_blocks_smc_fabric_bridge_e,
                     clk_smu_i, in_reset)
    `OCAH_FCOV_COVER(c_no_axi_traffic_observed, no_axi_traffic_observed_e, clk_smu_i, in_reset)
    `OCAH_FCOV_COVER(c_smc_otp_bridge_enabled_under_dbg_disable,
                     smc_otp_bridge_enabled_under_dbg_disable_e, clk_smu_i, in_reset)
    `OCAH_FCOV_COVER(c_sep_otp_bridge_enabled_under_dbg_disable,
                     sep_otp_bridge_enabled_under_dbg_disable_e, clk_smu_i, in_reset)
    `OCAH_FCOV_COVER(c_fabric_bridge_blocked_and_otp_bridges_enabled,
                     fabric_bridge_blocked_and_otp_bridges_enabled_e, clk_smu_i, in_reset)
    `OCAH_FCOV_COVER(c_smc_otp_access_succeeds_while_fabric_blocked,
                     smc_otp_access_succeeds_while_fabric_blocked_e, clk_smu_i, in_reset)
    `OCAH_FCOV_COVER(c_sep_otp_access_succeeds_while_fabric_blocked,
                     sep_otp_access_succeeds_while_fabric_blocked_e, clk_smu_i, in_reset)
  end

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroup: the three debug-disable bits as one
  // vector, which is the selectivity a flat point list cannot cross.
  // ------------------------------------------------------------------
  covergroup cg_dbg_disable_slice with function sample (logic fabric, logic smc_otp, logic sep_otp);
    option.per_instance = 1;
    cp_fabric: coverpoint fabric;
    // sep_lifecycle_ctrl ties both OTP debug-disable terms low, so neither
    // bridge can be disabled by the lifecycle controller in this design.
    cp_smc_otp: coverpoint smc_otp {
      ignore_bins tied_low = {1'b1};
    }
    cp_sep_otp: coverpoint sep_otp {ignore_bins tied_low = {1'b1};}
    x_slice: cross cp_fabric, cp_smc_otp, cp_sep_otp;
  endgroup

  cg_dbg_disable_slice u_cg_dbg_disable_slice = new();

  always_ff @(posedge clk_smu_i) begin
    if (!in_reset) begin
      u_cg_dbg_disable_slice.sample(dbg_disable_smc_jtag2axi_i, dbg_disable_smc_otp_i,
                                    dbg_disable_sep_otp_i);
    end
  end
`endif

endmodule : smu_dbg_fcov
