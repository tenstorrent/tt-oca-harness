// Copyright lowRISC contributors (OpenTitan project).
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

// Adapt TL-UL device traffic onto a register read/write interface.
//
// Act as a TL-UL device. Accept Get, PutPartialData, and PutFullData on the A channel and
// pass each read or write to the register interface in the same cycle. Return the register
// response on the D channel in the next cycle, whatever ACCESS_LATENCY is. One request is
// outstanding at a time: A_READY stays low until the response is accepted.
//
// Forward a request only when every check passes:
//
// - A_OPCODE is Get, PutPartialData, or PutFullData.
// - A_SIZE is 0, 1, or 2 (a 1-, 2-, or 4-byte operation).
// - A_ADDRESS is naturally aligned for the A_SIZE byte width, and word aligned for writes.
// - A_MASK is true only for active byte lanes. The first active lane is the address modulo
//   the TL-UL data-bus width.
// - A_USER.INSTR_TYPE is a valid MuBi4 encoding.
// - A_OPCODE is Get when A_USER.INSTR_TYPE is MuBi4True.
// - A_USER.INSTR_TYPE is not MuBi4True, or en_ifetch_i is MuBi4True.
// - The command and A-channel data integrity checks pass, when CMD_INTG_CHECK is set.
//
// A request that fails a check reaches no register and gets D_ERROR on the response. D_DATA
// is all ones for writes and errored requests.
//
// Besides the generated reg_top modules, this adapter serves modules with special needs,
// such as the vendored prim_reg_cdc and spi_host_window, which is why its parameter set is
// broader than reg_top needs.

module tlul_adapter_reg
  import tlul_pkg::*;

  `include "prim_assert.sv"
  import prim_mubi_pkg::mubi4_t;
#(
  parameter  bit CMD_INTG_CHECK       = 0,  // Check A-channel command integrity with
                                            // tlul_cmd_intg_chk. On a mismatch, re_o and we_o stay
                                            // low, D_ERROR is set, and intg_error_o rises the next
                                            // cycle.
  parameter  bit ENABLE_RSP_INTG_GEN  = 0,  // Generate D_USER.RSP_INTG; zero when clear.
  parameter  bit ENABLE_DATA_INTG_GEN = 0,  // Generate D_USER.DATA_INTG; zero when clear.
  parameter  int REG_AW               = 8,  // Register address width. Higher A_ADDRESS bits are
                                            // ignored.
  parameter  int REG_DW               = 32, // Register data width. Must match the TL-UL data width
                                            // (MatchedWidth_A).
  parameter  int ACCESS_LATENCY       = 0,  // 0 or 1. 0: the register response is combinatorial and
                                            // is flopped here. 1: the response arrives the cycle
                                            // after re_o/we_o and is forwarded combinatorially.
  localparam int RegBw                = REG_DW/8  // Register byte-enable width from REG_DW.
) (
  input clk_i,                        // System clock.
  input rst_ni,                       // Active-low reset.

  input  tl_h2d_t tl_i,               // TL-UL host-to-device request.
  output tl_d2h_t tl_o,               // TL-UL device-to-host response.

  input  mubi4_t  en_ifetch_i,        // MuBi4True allows Gets whose A_USER.INSTR_TYPE is MuBi4True
                                      // (processor fetches).
  output logic    intg_error_o,       // Integrity error, sticky until reset. Only rises when
                                      // CMD_INTG_CHECK is set.

  output logic              re_o,     // Register read enable.
  output logic              we_o,     // Register write enable.
  output logic [REG_AW-1:0] addr_o,   // A_ADDRESS[REG_AW-1:0], bits 1:0 cleared; 0 if REG_AW <= 2.
  output logic [REG_DW-1:0] wdata_o,  // Register write data.
  output logic [RegBw-1:0]  be_o,     // Register byte enables from the TL-UL mask.
  input                     busy_i,   // Stall: A_READY drops and no new operation is accepted.
  input        [REG_DW-1:0] rdata_i,  // Register read data, ACCESS_LATENCY cycles after re_o.
  input                     error_i   // Register read or write error, ACCESS_LATENCY cycles after
                                      // re_o/we_o. Sets D_ERROR and forces D_DATA to '1.
);
  `OCAH_OT_ASSERT_INIT(AllowedLatency_A, ACCESS_LATENCY inside {0, 1})

  localparam int IW  = $bits(tl_i.a_source);
  localparam int SZW = $bits(tl_i.a_size);

  logic outstanding_q;    // Indicates current request is pending
  logic a_ack, d_ack;

  logic [REG_DW-1:0] rdata, rdata_q;
  logic              error_q, error, err_internal, instr_error, intg_error;

  logic addr_align_err;     // Size and alignment
  logic tl_err;             // Common TL-UL error checker

  logic [IW-1:0]  reqid_q;
  logic [SZW-1:0] reqsz_q;
  tl_d_op_e       rspop_q;

  logic rd_req, wr_req;

  assign a_ack   = tl_i.a_valid & tl_o.a_ready;
  assign d_ack   = tl_o.d_valid & tl_i.d_ready;
  // Request signal
  assign wr_req  = a_ack & ((tl_i.a_opcode == PutFullData) | (tl_i.a_opcode == PutPartialData));
  assign rd_req  = a_ack & (tl_i.a_opcode == Get);

  assign we_o    = wr_req & ~err_internal;
  assign re_o    = rd_req & ~err_internal;
  assign wdata_o = tl_i.a_data;
  assign be_o    = tl_i.a_mask;

  if (REG_AW <= 2) begin : gen_only_one_reg
    assign addr_o  = '0;
  end else begin : gen_more_regs
    assign addr_o  = {tl_i.a_address[REG_AW-1:2], 2'b00}; // generate always word-align
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni)    outstanding_q <= 1'b0;
    else if (a_ack) outstanding_q <= 1'b1;
    else if (d_ack) outstanding_q <= 1'b0;
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      reqid_q <= '0;
      reqsz_q <= '0;
      rspop_q <= AccessAck;
    end else if (a_ack) begin
      reqid_q <= tl_i.a_source;
      reqsz_q <= tl_i.a_size;
      // Return AccessAckData regardless of error
      rspop_q <= (rd_req) ? AccessAckData : AccessAck ;
    end
  end

  if (ACCESS_LATENCY == 1) begin : gen_access_latency1
    logic a_ack_q, err_internal_q, wr_req_q;
    always_ff @(posedge clk_i or negedge rst_ni) begin
      if (!rst_ni) begin
        a_ack_q <= 1'b0;
        err_internal_q <= 1'b0;
        wr_req_q <= 1'b0;
        rdata_q  <= '0;
        error_q  <= 1'b0;
      end else begin
        a_ack_q <= a_ack;
        err_internal_q <= err_internal;
        wr_req_q <= wr_req;

        rdata_q  <= rdata;
        error_q  <= error;
      end
    end
    always_comb begin
      if (a_ack_q) begin
        rdata = (error_i || err_internal_q || wr_req_q) ? '1 : rdata_i;
        error = error_i || err_internal_q;
      end else begin
        rdata = rdata_q;
        error = error_q;
      end
    end
  end else begin : gen_access_latency0
    always_ff @(posedge clk_i or negedge rst_ni) begin
      if (!rst_ni) begin
        rdata_q <= '0;
        error_q <= 1'b0;
      end else if (a_ack) begin
        rdata_q <= (error_i || err_internal || wr_req) ? '1 : rdata_i;
        error_q <= error_i || err_internal;
      end
    end
    assign rdata = rdata_q;
    assign error = error_q;
  end

  tlul_pkg::tl_d2h_t tl_o_pre;
  assign tl_o_pre = '{
    a_ready:  ~(outstanding_q | busy_i),
    d_valid:  outstanding_q,
    d_opcode: rspop_q,
    d_param:  '0,
    d_size:   reqsz_q,
    d_source: reqid_q,
    d_sink:   '0,
    d_data:   rdata,
    d_user:   '0,
    d_error:  error
  };

  // outgoing integrity generation
  tlul_rsp_intg_gen #(
    .ENABLE_RSP_INTG_GEN(ENABLE_RSP_INTG_GEN),
    .ENABLE_DATA_INTG_GEN(ENABLE_DATA_INTG_GEN),
    .USER_IN_IS_ZERO(1'b1)
  ) u_rsp_intg_gen (
    .tl_i(tl_o_pre),
    .tl_o(tl_o)
  );

  if (CMD_INTG_CHECK) begin : gen_cmd_intg_check
    logic intg_error_q;
    tlul_cmd_intg_chk u_cmd_intg_chk (
      .tl_i(tl_i),
      .err_o(intg_error)
    );
    // permanently latch integrity error until reset
    always_ff @(posedge clk_i or negedge rst_ni) begin
      if (!rst_ni) begin
        intg_error_q <= 1'b0;
      end else if (intg_error) begin
        intg_error_q <= 1'b1;
      end
    end
    assign intg_error_o = intg_error_q;
  end else begin : gen_no_cmd_intg_check
    assign intg_error = 1'b0;
    assign intg_error_o = 1'b0;
  end

  ////////////////////
  // Error Handling //
  ////////////////////

  // An instruction type transaction is only valid if en_ifetch is enabled
  assign instr_error = prim_mubi_pkg::mubi4_test_true_strict(tl_i.a_user.instr_type) &
                       prim_mubi_pkg::mubi4_test_false_loose(en_ifetch_i);

  assign err_internal = addr_align_err | tl_err | instr_error | intg_error;

  // addr_align_err
  //    Raised if addr isn't aligned with the size
  //    Read size error is checked in tlul_assert.sv
  //    Here is it added due to the limitation of register interface.
  always_comb begin
    if (wr_req) begin
      // Only word-align is accepted based on comportability spec
      addr_align_err = |tl_i.a_address[1:0];
    end else begin
      // No request
      addr_align_err = 1'b0;
    end
  end

  // tl_err : separate checker
  tlul_err u_err (
    .clk_i,
    .rst_ni,
    .tl_i,
    .err_o (tl_err)
  );

  `OCAH_OT_ASSERT_INIT(MatchedWidth_A, REG_DW == top_pkg::TL_DW)

endmodule
