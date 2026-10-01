// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Open-path environment for the cross_trigger_network formal top: the reset model, the AXI-Lite
// manager's outstanding bound, the far end of one point-to-point port, and the stretch bound.
// Bound to cross_trigger_network by the statement at the end of this file and read only by the
// task file.
//
// The top has one clock, so the reset is asserted up to the first posedge and released there.
// The manager is the DTP's JTAG bridge, which issues one write and one read at a time; its
// handshake rules are the shared AXI checker's, bound in assume mode by dtp_ctn_axi_fv_bind.sv.
// The peer model describes the far end of external
// port 0 on its synchronized, de-inverted request and acknowledge: the far end acknowledges a
// request it sees and withdraws the acknowledge after the request drops, and it holds its own
// request until it sees the acknowledge and raises no new one while the acknowledge is high. The
// stretch bound keeps the pulse stretcher within the cover depth.

`include "ocah_fv_macros.svh"

module dtp_cross_trigger_network_sby_env
  import cross_trigger_network_pkg::*;
(
  input logic           clk_i,
  input logic           rst_ni,
  input ctn_axil_req_t  axil_req_i,
  input ctn_axil_resp_t axil_resp_o,
  // External port 0
  input logic           ctp0_req_out_i,      // handshake ct_req_out_q
  input logic           ctp0_ack_out_i,      // handshake ct_ack_out_q
  input logic           ctp0_req_in_sync_i,  // ct_req_in_din_sync_inv
  input logic           ctp0_ack_in_sync_i,  // ct_ack_in_din_sync_inv
  input logic [15:0]    ctp0_stretch_mult_i  // STRETCH_MULT field
);

`ifdef FORMAL
  logic released_q = 1'b0;
  always_ff @(posedge clk_i) released_q <= 1'b1;

  always_comb begin
    asm_env_reset_asserted : assume (released_q || !rst_ni);
    asm_env_reset_released : assume (!released_q || rst_ni);
  end

  logic write_outstanding_q, read_outstanding_q;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      write_outstanding_q <= 1'b0;
      read_outstanding_q  <= 1'b0;
    end else begin
      if (axil_req_i.aw_valid && axil_resp_o.aw_ready) write_outstanding_q <= 1'b1;
      else if (axil_resp_o.b_valid && axil_req_i.b_ready) write_outstanding_q <= 1'b0;
      if (axil_req_i.ar_valid && axil_resp_o.ar_ready) read_outstanding_q <= 1'b1;
      else if (axil_resp_o.r_valid && axil_req_i.r_ready) read_outstanding_q <= 1'b0;
    end
  end

  // verilog_format: off
  // The manager issues one write and one read at a time.
  `OCAH_FV_ASSUME(asm_axil_one_outstanding,
                  `OCAH_FV_IMPLIES(write_outstanding_q, !axil_req_i.aw_valid) &&
                  `OCAH_FV_IMPLIES(read_outstanding_q, !axil_req_i.ar_valid),
                  clk_i, rst_ni)
  // The far end acknowledges a request it sees and withdraws the acknowledge after it drops.
  `OCAH_FV_ASSUME(asm_ctp_peer_four_phase,
                  `OCAH_FV_IMPLIES($past(rst_ni) && `OCAH_FV_ROSE(ctp0_ack_in_sync_i),
                                   $past(ctp0_req_out_i)) &&
                  `OCAH_FV_IMPLIES($past(rst_ni) && $past(ctp0_ack_in_sync_i) && $past(ctp0_req_out_i),
                                   ctp0_ack_in_sync_i) &&
                  `OCAH_FV_IMPLIES($past(rst_ni) && !$past(ctp0_ack_in_sync_i) && !$past(ctp0_req_out_i),
                                   !ctp0_ack_in_sync_i) &&
                  `OCAH_FV_IMPLIES($past(rst_ni) && $past(ctp0_req_in_sync_i) && !$past(ctp0_ack_out_i),
                                   ctp0_req_in_sync_i) &&
                  `OCAH_FV_IMPLIES($past(rst_ni) && !$past(ctp0_req_in_sync_i) && $past(ctp0_ack_out_i),
                                   !ctp0_req_in_sync_i),
                  clk_i, rst_ni)
  // The stretcher counts down from STRETCH_MULT; the bound keeps a stretched pulse inside the depth.
  `OCAH_FV_ASSUME(asm_ctp_stretch_small, ctp0_stretch_mult_i <= 16'd4, clk_i, rst_ni)
  // verilog_format: on
`endif

endmodule : dtp_cross_trigger_network_sby_env

bind cross_trigger_network dtp_cross_trigger_network_sby_env u_dtp_cross_trigger_network_sby_env (
  .clk_i               (clk_i),
  .rst_ni              (rst_ni),
  .axil_req_i          (axil_req_i),
  .axil_resp_o         (axil_resp_o),
  .ctp0_req_out_i      (gen_ext_ctp[0].u_ctp.u_core.u_handshake_ctrl.ct_req_out_q),
  .ctp0_ack_out_i      (gen_ext_ctp[0].u_ctp.u_core.u_handshake_ctrl.ct_ack_out_q),
  .ctp0_req_in_sync_i  (gen_ext_ctp[0].u_ctp.u_core.ct_req_in_din_sync_inv),
  .ctp0_ack_in_sync_i  (gen_ext_ctp[0].u_ctp.u_core.ct_ack_in_din_sync_inv),
  .ctp0_stretch_mult_i (gen_ext_ctp[0].u_ctp.reg_out.STRETCH_MULT.STRETCH_MULT.value)
);
