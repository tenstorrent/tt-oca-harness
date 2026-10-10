// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

// Filter 64-bit AXI-Lite traffic down to aligned single-lane 32-bit accesses.
//
// Forwards supported beats into the existing 32-bit AXI-Lite to TL-UL bridge, one
// transaction at a time; a read accepted in the same cycle as a write is served first,
// and no read is accepted while write address or data is held. A read must be
// 4-byte aligned and returns the addressed 32-bit lane with the other lane zero; a write
// must be 4-byte aligned with WSTRB exactly 0x0F for the lower lane or 0xF0 for the upper
// lane, selected by address bit 2. Unsupported accesses return AXI SLVERR and emit no
// downstream request.

module drbg_axil64_lane_adapter
  import drbg_pkg::drbg_axil64_req_t;
  import drbg_pkg::drbg_axil64_resp_t;
  import drbg_pkg::drbg_axil32_req_t;
  import drbg_pkg::drbg_axil32_resp_t;
#(
  parameter type axil64_req_t = drbg_axil64_req_t,          // 64-bit AXI-Lite request type.
  parameter type axil64_rsp_t = drbg_axil64_resp_t,         // 64-bit AXI-Lite response type.
  parameter type axil32_req_t = drbg_axil32_req_t,          // 32-bit AXI-Lite request type.
  parameter type axil32_rsp_t = drbg_axil32_resp_t          // 32-bit AXI-Lite response type.
) (
  input  wire logic   clk_i,                                // System clock.
  input  wire logic   rst_ni,                               // Async reset, active-low.

  input  axil64_req_t axil64_req_i,                         // 64-bit AXI-Lite request in.
  output axil64_rsp_t axil64_rsp_o,                         // 64-bit AXI-Lite response out.

  output axil32_req_t axil32_req_o,                         // Forwarded 32-bit AXI-Lite request.
  input  axil32_rsp_t axil32_rsp_i,                         // 32-bit AXI-Lite response from the
                                                            // bridge.

  output logic        unsupported_access_pulse_o,           // One-cycle pulse when an unsupported
                                                            // access is rejected with SLVERR; a
                                                            // SLVERR returned by the bridge does
                                                            // not pulse it.
  output logic        forwarded_read_pulse_o,               // Pulse when a read is forwarded.
  output logic        forwarded_write_pulse_o               // Pulse when a write is forwarded.
);

  `include "prim_assert.sv"
  `include "ocah_assert.svh"

  localparam logic [1:0] AxiRespOkay = 2'b00;
  localparam logic [1:0] AxiRespSlverr = 2'b10;

  typedef enum logic [2:0] {
    ST_IDLE,
    ST_READ_REQ,
    ST_READ_WAIT,
    ST_READ_RESP,
    ST_WRITE_REQ,
    ST_WRITE_WAIT,
    ST_WRITE_RESP
  } state_e;

  state_e state_q, state_d;

  localparam int unsigned Axil64ReqWidth = $bits(axil64_req_t);
  localparam int unsigned Axil64RspWidth = $bits(axil64_rsp_t);
  localparam int unsigned Axil32ReqWidth = $bits(axil32_req_t);
  localparam int unsigned Axil32RspWidth = $bits(axil32_rsp_t);

  logic [31:0] aw_addr_q, aw_addr_d;
  logic [2:0] aw_prot_q, aw_prot_d;
  logic [63:0] w_data_q, w_data_d;
  logic [7:0] w_strb_q, w_strb_d;
  logic aw_pending_q, aw_pending_d;
  logic w_pending_q, w_pending_d;

  logic [31:0] req_addr_q, req_addr_d;
  logic [2:0] req_prot_q, req_prot_d;
  logic [31:0] req_wdata_q, req_wdata_d;
  logic [3:0] req_wstrb_q, req_wstrb_d;
  logic req_lane_q, req_lane_d;
  logic [31:0] resp_rdata_q, resp_rdata_d;
  logic [1:0] resp_code_q, resp_code_d;

  function automatic logic read_supported(input logic [31:0] addr);
    return addr[1:0] == 2'b00;
  endfunction

  function automatic logic write_supported(input logic [31:0] addr, input logic [7:0] strb);
    if (addr[1:0] != 2'b00) begin
      return 1'b0;
    end
    if (addr[2] == 1'b0) begin
      return strb == 8'h0F;
    end
    return strb == 8'hF0;
  endfunction

  function automatic logic [31:0] lane_data(input logic [63:0] data, input logic lane_sel);
    return lane_sel ? data[63:32] : data[31:0];
  endfunction

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      state_q      <= ST_IDLE;
      aw_pending_q <= 1'b0;
      w_pending_q  <= 1'b0;
      aw_addr_q    <= '0;
      aw_prot_q    <= '0;
      w_data_q     <= '0;
      w_strb_q     <= '0;
      req_addr_q   <= '0;
      req_prot_q   <= '0;
      req_wdata_q  <= '0;
      req_wstrb_q  <= '0;
      req_lane_q   <= 1'b0;
      resp_rdata_q <= '0;
      resp_code_q  <= AxiRespOkay;
    end else begin
      state_q      <= state_d;
      aw_pending_q <= aw_pending_d;
      w_pending_q  <= w_pending_d;
      aw_addr_q    <= aw_addr_d;
      aw_prot_q    <= aw_prot_d;
      w_data_q     <= w_data_d;
      w_strb_q     <= w_strb_d;
      req_addr_q   <= req_addr_d;
      req_prot_q   <= req_prot_d;
      req_wdata_q  <= req_wdata_d;
      req_wstrb_q  <= req_wstrb_d;
      req_lane_q   <= req_lane_d;
      resp_rdata_q <= resp_rdata_d;
      resp_code_q  <= resp_code_d;
    end
  end

  always_comb begin
    logic aw_handshake;
    logic w_handshake;
    logic ar_handshake;
    logic aw_pending_next;
    logic w_pending_next;
    logic [31:0] aw_addr_next;
    logic [2:0]  aw_prot_next;
    logic [63:0] w_data_next;
    logic [7:0]  w_strb_next;

    state_d      = state_q;
    aw_pending_d = aw_pending_q;
    w_pending_d  = w_pending_q;
    aw_addr_d    = aw_addr_q;
    aw_prot_d    = aw_prot_q;
    w_data_d     = w_data_q;
    w_strb_d     = w_strb_q;
    req_addr_d   = req_addr_q;
    req_prot_d   = req_prot_q;
    req_wdata_d  = req_wdata_q;
    req_wstrb_d  = req_wstrb_q;
    req_lane_d   = req_lane_q;
    resp_rdata_d = resp_rdata_q;
    resp_code_d  = resp_code_q;

    axil64_rsp_o = '0;
    axil64_rsp_o.b.resp = AxiRespOkay;
    axil64_rsp_o.r.resp = AxiRespOkay;

    axil32_req_o = '0;

    unsupported_access_pulse_o = 1'b0;
    forwarded_read_pulse_o = 1'b0;
    forwarded_write_pulse_o = 1'b0;

    aw_handshake = 1'b0;
    w_handshake = 1'b0;
    ar_handshake = 1'b0;
    aw_pending_next = aw_pending_q;
    w_pending_next = w_pending_q;
    aw_addr_next = aw_addr_q;
    aw_prot_next = aw_prot_q;
    w_data_next = w_data_q;
    w_strb_next = w_strb_q;

    case (state_q)
      ST_IDLE: begin
        axil64_rsp_o.aw_ready = !aw_pending_q;
        axil64_rsp_o.w_ready  = !w_pending_q;
        axil64_rsp_o.ar_ready = !aw_pending_q && !w_pending_q;

        aw_handshake = axil64_req_i.aw_valid && axil64_rsp_o.aw_ready;
        w_handshake = axil64_req_i.w_valid && axil64_rsp_o.w_ready;
        ar_handshake = axil64_req_i.ar_valid && axil64_rsp_o.ar_ready;

        if (aw_handshake) begin
          aw_pending_next = 1'b1;
          aw_addr_next = axil64_req_i.aw.addr;
          aw_prot_next = axil64_req_i.aw.prot;
        end

        if (w_handshake) begin
          w_pending_next = 1'b1;
          w_data_next = axil64_req_i.w.data;
          w_strb_next = axil64_req_i.w.strb;
        end

        aw_pending_d = aw_pending_next;
        w_pending_d = w_pending_next;
        aw_addr_d = aw_addr_next;
        aw_prot_d = aw_prot_next;
        w_data_d = w_data_next;
        w_strb_d = w_strb_next;

        if (ar_handshake) begin
          req_addr_d = axil64_req_i.ar.addr;
          req_prot_d = axil64_req_i.ar.prot;
          req_lane_d = axil64_req_i.ar.addr[2];
          if (read_supported(axil64_req_i.ar.addr)) begin
            state_d = ST_READ_REQ;
          end else begin
            resp_rdata_d = '0;
            resp_code_d = AxiRespSlverr;
            unsupported_access_pulse_o = 1'b1;
            state_d = ST_READ_RESP;
          end
        end else if (aw_pending_next && w_pending_next) begin
          req_addr_d = aw_addr_next;
          req_prot_d = aw_prot_next;
          req_lane_d = aw_addr_next[2];
          req_wdata_d = lane_data(w_data_next, aw_addr_next[2]);
          req_wstrb_d = aw_addr_next[2] ? w_strb_next[7:4] : w_strb_next[3:0];
          aw_pending_d = 1'b0;
          w_pending_d = 1'b0;
          if (write_supported(aw_addr_next, w_strb_next)) begin
            state_d = ST_WRITE_REQ;
          end else begin
            resp_code_d = AxiRespSlverr;
            unsupported_access_pulse_o = 1'b1;
            state_d = ST_WRITE_RESP;
          end
        end
      end

      ST_READ_REQ: begin
        axil32_req_o.ar_valid = 1'b1;
        axil32_req_o.ar.addr = req_addr_q;
        axil32_req_o.ar.prot = req_prot_q;
        if (axil32_rsp_i.ar_ready) begin
          forwarded_read_pulse_o = 1'b1;
          state_d = ST_READ_WAIT;
        end
      end

      ST_READ_WAIT: begin
        axil32_req_o.r_ready = 1'b1;
        if (axil32_rsp_i.r_valid) begin
          resp_rdata_d = axil32_rsp_i.r.data;
          resp_code_d = axil32_rsp_i.r.resp;
          state_d = ST_READ_RESP;
        end
      end

      ST_READ_RESP: begin
        axil64_rsp_o.r_valid = 1'b1;
        axil64_rsp_o.r.data = req_lane_q ? {resp_rdata_q, 32'h0} : {32'h0, resp_rdata_q};
        axil64_rsp_o.r.resp = resp_code_q;
        if (axil64_req_i.r_ready) begin
          state_d = ST_IDLE;
        end
      end

      ST_WRITE_REQ: begin
        axil32_req_o.aw_valid = 1'b1;
        axil32_req_o.aw.addr = req_addr_q;
        axil32_req_o.aw.prot = req_prot_q;
        axil32_req_o.w_valid = 1'b1;
        axil32_req_o.w.data = req_wdata_q;
        axil32_req_o.w.strb = req_wstrb_q;
        if (axil32_rsp_i.aw_ready && axil32_rsp_i.w_ready) begin
          forwarded_write_pulse_o = 1'b1;
          state_d = ST_WRITE_WAIT;
        end
      end

      ST_WRITE_WAIT: begin
        axil32_req_o.b_ready = 1'b1;
        if (axil32_rsp_i.b_valid) begin
          resp_code_d = axil32_rsp_i.b.resp;
          state_d = ST_WRITE_RESP;
        end
      end

      ST_WRITE_RESP: begin
        axil64_rsp_o.b_valid = 1'b1;
        axil64_rsp_o.b.resp = resp_code_q;
        if (axil64_req_i.b_ready) begin
          state_d = ST_IDLE;
        end
      end

      default: state_d = ST_IDLE;
    endcase
  end

  `OCAH_ASSERT_STATIC(Axil64ReqWidthValid_A, Axil64ReqWidth == $bits(drbg_axil64_req_t))
  `OCAH_ASSERT_STATIC(Axil64RspWidthValid_A, Axil64RspWidth == $bits(drbg_axil64_resp_t))
  `OCAH_ASSERT_STATIC(Axil32ReqWidthValid_A, Axil32ReqWidth == $bits(drbg_axil32_req_t))
  `OCAH_ASSERT_STATIC(Axil32RspWidthValid_A, Axil32RspWidth == $bits(drbg_axil32_resp_t))
  `OCAH_OT_ASSERT(
      UnsupportedBlocksForwarding_A,
      unsupported_access_pulse_o |-> !(forwarded_read_pulse_o || forwarded_write_pulse_o))
  `OCAH_OT_ASSERT(ReadForwardingSinglePulse_A, forwarded_read_pulse_o |-> state_q == ST_READ_REQ)
  `OCAH_OT_ASSERT(WriteForwardingSinglePulse_A, forwarded_write_pulse_o |-> state_q == ST_WRITE_REQ)
  `OCAH_OT_ASSERT(StIdleAwReady_A,
                  (state_q == ST_IDLE) |-> (axil64_rsp_o.aw_ready == !aw_pending_q))
  `OCAH_OT_ASSERT(StIdleWReady_A, (state_q == ST_IDLE) |-> (axil64_rsp_o.w_ready == !w_pending_q))
  `OCAH_OT_ASSERT(
      StIdleArReady_A,
      (state_q == ST_IDLE) |-> (axil64_rsp_o.ar_ready == (!aw_pending_q && !w_pending_q)))
  `OCAH_OT_ASSERT(
      BusyHoldsChannelReadyLow_A,
      (state_q != ST_IDLE) |-> (!axil64_rsp_o.aw_ready && !axil64_rsp_o.w_ready && !axil64_rsp_o.ar_ready))
  `OCAH_OT_ASSERT_KNOWN(Axil64AwReadyKnown_A, axil64_rsp_o.aw_ready)
  `OCAH_OT_ASSERT_KNOWN(Axil64WReadyKnown_A, axil64_rsp_o.w_ready)
  `OCAH_OT_ASSERT_KNOWN(Axil64BValidKnown_A, axil64_rsp_o.b_valid)
  `OCAH_OT_ASSERT_KNOWN(Axil64BRespKnown_A, axil64_rsp_o.b.resp)
  `OCAH_OT_ASSERT_KNOWN(Axil64ArReadyKnown_A, axil64_rsp_o.ar_ready)
  `OCAH_OT_ASSERT_KNOWN(Axil64RValidKnown_A, axil64_rsp_o.r_valid)
  `OCAH_OT_ASSERT_KNOWN(Axil64RRespKnown_A, axil64_rsp_o.r.resp)
  `OCAH_OT_ASSERT_KNOWN(Axil64RDataKnown_A, axil64_rsp_o.r.data)

endmodule : drbg_axil64_lane_adapter
