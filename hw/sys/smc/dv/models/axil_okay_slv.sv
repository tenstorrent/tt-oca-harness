// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// AXI4-Lite OKAY terminator -- accepts every write and read and completes it
// with RESP_OKAY, returning RESP_DATA on reads.
//
// The placeholder register blocks (pll_wrap, pvt_wrap) terminate an AXI-Lite
// port that a real integration fills with the adopter's CSRs, so every access
// completes with RESP_OKAY.
//
// One write and one read may be in flight at a time. AW and W are accepted
// independently; B rises the cycle after both have been seen and holds until
// b_ready. AR is accepted while no read response is pending; R rises the
// next cycle and holds until r_ready.
//-----------------------------------------------------------------------------

module axil_okay_slv #(
  parameter type                   axil_req_t  = logic,
  parameter type                   axil_resp_t = logic,
  parameter int unsigned           RESP_WIDTH  = 32,
  parameter logic [RESP_WIDTH-1:0] RESP_DATA   = '0
) (
  input  logic       clk_i,
  input  logic       rst_ni,

  input  axil_req_t  axil_req_i,
  output axil_resp_t axil_resp_o
);

  logic aw_seen_q, w_seen_q, b_pending_q, r_pending_q;
  logic aw_hs, w_hs, ar_hs;

  assign axil_resp_o.aw_ready = !aw_seen_q && !b_pending_q;
  assign axil_resp_o.w_ready  = !w_seen_q && !b_pending_q;
  assign axil_resp_o.b_valid  = b_pending_q;
  assign axil_resp_o.b.resp   = axi_pkg::RESP_OKAY;
  assign axil_resp_o.ar_ready = !r_pending_q;
  assign axil_resp_o.r_valid  = r_pending_q;
  assign axil_resp_o.r.data   = RESP_DATA;
  assign axil_resp_o.r.resp   = axi_pkg::RESP_OKAY;

  assign aw_hs = axil_req_i.aw_valid && axil_resp_o.aw_ready;
  assign w_hs  = axil_req_i.w_valid && axil_resp_o.w_ready;
  assign ar_hs = axil_req_i.ar_valid && axil_resp_o.ar_ready;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      aw_seen_q   <= 1'b0;
      w_seen_q    <= 1'b0;
      b_pending_q <= 1'b0;
      r_pending_q <= 1'b0;
    end else begin
      if (b_pending_q) begin
        if (axil_req_i.b_ready) b_pending_q <= 1'b0;
      end else if ((aw_seen_q || aw_hs) && (w_seen_q || w_hs)) begin
        b_pending_q <= 1'b1;
        aw_seen_q   <= 1'b0;
        w_seen_q    <= 1'b0;
      end else begin
        if (aw_hs) aw_seen_q <= 1'b1;
        if (w_hs) w_seen_q <= 1'b1;
      end

      if (r_pending_q) begin
        if (axil_req_i.r_ready) r_pending_q <= 1'b0;
      end else if (ar_hs) begin
        r_pending_q <= 1'b1;
      end
    end
  end

endmodule
