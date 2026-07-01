// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// TL-UL Device to Register Interface Bridge (Async)
//
// This module bridges TL-UL device side to a register interface with support
// for variable latency backends (like AXI). Unlike tlul_adapter_reg, this
// properly handles multi-cycle response latency.
//
//------------------------------------------------------------------------------

module tlul_to_reg_async
  import tlul_pkg::*;
  import prim_mubi_pkg::mubi4_t;
#(
  parameter int unsigned RegAw = 32,  // Register address width
  parameter int unsigned RegDw = 32,  // Register data width (must match TL_DW)
  parameter bit EnableRspIntgGen  = 1'b1,  // Generate response integrity
  parameter bit EnableDataIntgGen = 1'b1,  // Generate data integrity
  localparam int unsigned RegBw = RegDw / 8
) (
  input  logic clk_i,
  input  logic rst_ni,

  // TL-UL device interface (receives requests)
  input  tl_h2d_t tl_i,
  output tl_d2h_t tl_o,

  // Register interface (to downstream, e.g., reg_to_axi)
  output logic             reg_req_valid_o,
  output logic [RegAw-1:0] reg_req_addr_o,
  output logic             reg_req_write_o,
  output logic [RegDw-1:0] reg_req_wdata_o,
  output logic [RegBw-1:0] reg_req_wstrb_o,
  input  logic [RegDw-1:0] reg_rsp_rdata_i,
  input  logic             reg_rsp_error_i,  // 1 = error, 0 = okay
  input  logic             reg_rsp_ready_i   // Response valid
);

  // Request tracking
  logic                        outstanding_q;
  logic [top_pkg::TL_AIW-1:0]  source_q;
  logic [top_pkg::TL_SZW-1:0]  size_q;
  tl_d_op_e                    opcode_q;

  // Register request holding
  logic                        req_valid_q;
  logic                        req_write_q;
  logic [RegAw-1:0]            req_addr_q;
  logic [RegDw-1:0]            req_wdata_q;
  logic [RegBw-1:0]            req_wstrb_q;

  // TL-UL handshake signals
  logic a_ack, d_ack;
  assign a_ack = tl_i.a_valid & tl_o.a_ready;
  assign d_ack = tl_o.d_valid & tl_i.d_ready;

  // Request capture and state tracking
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      outstanding_q <= 1'b0;
      source_q      <= '0;
      size_q        <= '0;
      opcode_q      <= AccessAck;
      req_valid_q   <= 1'b0;
      req_write_q   <= 1'b0;
      req_addr_q    <= '0;
      req_wdata_q   <= '0;
      req_wstrb_q   <= '0;
    end else begin
      // New TL-UL request accepted
      if (a_ack) begin
        outstanding_q <= 1'b1;
        source_q      <= tl_i.a_source;
        size_q        <= tl_i.a_size;
        opcode_q      <= (tl_i.a_opcode == Get) ? AccessAckData : AccessAck;
        // Capture for register interface
        req_valid_q   <= 1'b1;
        req_write_q   <= (tl_i.a_opcode != Get);
        req_addr_q    <= tl_i.a_address[RegAw-1:0];
        req_wdata_q   <= tl_i.a_data;
        req_wstrb_q   <= tl_i.a_mask;
      end

      // Clear request valid once response received
      if (reg_rsp_ready_i) begin
        req_valid_q <= 1'b0;
      end

      // TL-UL response acknowledged
      if (d_ack) begin
        outstanding_q <= 1'b0;
      end
    end
  end

  // Drive register interface outputs
  assign reg_req_valid_o = req_valid_q;
  assign reg_req_addr_o  = req_addr_q;
  assign reg_req_write_o = req_write_q;
  assign reg_req_wdata_o = req_wdata_q;
  assign reg_req_wstrb_o = req_wstrb_q;

  // Build TL-UL response
  // Accept new requests only when not busy
  // Response valid when we have outstanding request AND register response is ready
  tl_d2h_t tl_o_pre;
  assign tl_o_pre.a_ready  = ~outstanding_q;
  assign tl_o_pre.d_valid  = outstanding_q & reg_rsp_ready_i;
  assign tl_o_pre.d_opcode = opcode_q;
  assign tl_o_pre.d_param  = '0;
  assign tl_o_pre.d_size   = size_q;
  assign tl_o_pre.d_source = source_q;
  assign tl_o_pre.d_sink   = '0;
  assign tl_o_pre.d_data   = reg_rsp_error_i ? '1 : reg_rsp_rdata_i;
  assign tl_o_pre.d_user   = '0;
  assign tl_o_pre.d_error  = reg_rsp_error_i;

  // Generate response integrity
  tlul_rsp_intg_gen #(
    .EnableRspIntgGen  (EnableRspIntgGen),
    .EnableDataIntgGen (EnableDataIntgGen),
    .UserInIsZero      (1'b1)
  ) u_rsp_intg_gen (
    .tl_i (tl_o_pre),
    .tl_o (tl_o)
  );

endmodule
