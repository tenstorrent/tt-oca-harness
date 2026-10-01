// Copyright lowRISC contributors (OpenTitan project).
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

// Convert a host req/gnt/rvalid bus into TL-UL.
//
// Requests and responses pass combinationally. When MAX_REQS > 1 a counter assigns
// a_source IDs 0 to MAX_REQS-1 in rotation; when MAX_REQS == 1 a_source is always 0. The
// host must not have more requests in flight than MAX_REQS. d_ready is tied high, so the
// host must accept every response in the cycle it arrives.
//
// The adapter does not reorder responses when MAX_REQS > 1. The host must either target an
// address space that returns in order or not depend on order.
//
// The outgoing address is always word aligned and the access size is always the TL word
// size (TL_DW). The A-channel opcode and mask follow the access:
//
// - Full-lane writes use PutFullData.
// - Other writes use PutPartialData, with the mask generated from be_i.
// - Reads enable every lane in the mask as required by TL-UL.
//
// Integrity handling is optional:
//
// - When ENABLE_DATA_INTG_GEN is set, compute data integrity on host write data; otherwise
//   send wdata_intg_i.
// - Response integrity is always checked. When ENABLE_RSP_DATA_INTG_CHECK is set, also check
//   integrity on returned read data.

module tlul_adapter_host
  import tlul_pkg::*;

  `include "prim_assert.sv"
  import prim_mubi_pkg::mubi4_t;
#(
  parameter int unsigned MAX_REQS = 2,              // Maximum outstanding host requests.
  parameter bit ENABLE_DATA_INTG_GEN = 0,           // Compute data integrity on write data.
  parameter bit ENABLE_RSP_DATA_INTG_CHECK = 0      // Check integrity on returned read data.
) (
  input clk_i,                                      // System clock.
  input rst_ni,                                     // Active-low reset.

  input                              req_i,         // Host request valid.
  output logic                       gnt_o,         // Host request grant.
  input  logic [top_pkg::TL_AW-1:0]  addr_i,        // Host byte address; word-aligned on tl_o.
  input  logic                       we_i,          // Host write enable.
  input  logic [top_pkg::TL_DW-1:0]  wdata_i,       // Host write data.
  input  logic [DATA_INTG_WIDTH-1:0] wdata_intg_i,  // Integrity bits sent with wdata_i when
                                                    // ENABLE_DATA_INTG_GEN is clear.
  input  logic [top_pkg::TL_DBW-1:0] be_i,          // Host byte enables; form the TL-UL mask.
  input  mubi4_t                     instr_type_i,  // MuBi4 instruction-type user bit.
  input  logic [RSVD_WIDTH-1:0]      user_rsvd_i,   // Reserved A-channel user bits.

  output logic                       valid_o,       // Host response valid.
  output logic [top_pkg::TL_DW-1:0]  rdata_o,       // Host read data.
  output logic [DATA_INTG_WIDTH-1:0] rdata_intg_o,  // Integrity bits with rdata_o.
  output logic                       err_o,         // d_error or an integrity failure on this
                                                    // response.
  output logic                       intg_err_o,    // Integrity failure; sticky until reset.

  output tl_h2d_t                    tl_o,          // TL-UL host-to-device toward the fabric.
  input  tl_d2h_t                    tl_i           // TL-UL device-to-host from the fabric.
);
  localparam int unsigned WordSize = $clog2(top_pkg::TL_DBW);

  logic [top_pkg::TL_AIW-1:0] tl_source;
  logic [top_pkg::TL_DBW-1:0] tl_be;
  tl_h2d_t                    tl_out;

  if (MAX_REQS == 1) begin : gen_single_req
    assign tl_source = '0;
  end else begin : gen_multiple_reqs
    localparam int ReqNumW  = $clog2(MAX_REQS);
    localparam int unsigned MaxSource = MAX_REQS - 1;
    localparam logic [ReqNumW-1:0] ReqNumOne = ReqNumW'(1'b1);

    logic [ReqNumW-1:0] source_d;
    logic [ReqNumW-1:0] source_q;

    always_ff @(posedge clk_i or negedge rst_ni) begin
      if (!rst_ni) begin
        source_q <= '0;
      end else begin
        source_q <= source_d;
      end
    end

    always_comb begin
      source_d = source_q;

      if (req_i && gnt_o) begin
        if (source_q == MaxSource[ReqNumW-1:0]) begin
          source_d = '0;
        end else  begin
          source_d = source_q + ReqNumOne;
        end
      end
    end

    assign tl_source = top_pkg::TL_AIW'(source_q);
  end

  // For TL-UL Get opcode all active bytes must have their mask bit set, so all reads get all tl_be
  // bits set. For writes the supplied be_i is used as the mask.
  assign tl_be = ~we_i ? {top_pkg::TL_DBW{1'b1}} : be_i;

  assign tl_out = '{
    a_valid:   req_i,
    a_opcode:  (~we_i) ? Get           :
               (&be_i) ? PutFullData   :
                         PutPartialData,
    a_param:   3'h0,
    a_size:    top_pkg::TL_SZW'(WordSize),
    a_mask:    tl_be,
    a_source:  tl_source,
    a_address: {addr_i[31:WordSize], {WordSize{1'b0}}},
    a_data:    wdata_i,
    a_user:    '{default: '0, data_intg: wdata_intg_i, instr_type: instr_type_i, rsvd: user_rsvd_i},
    d_ready:   1'b1
  };

  tlul_cmd_intg_gen #(.ENABLE_DATA_INTG_GEN (ENABLE_DATA_INTG_GEN)) u_cmd_intg_gen (
    .tl_i(tl_out),
    .tl_o(tl_o)
  );

  assign gnt_o        = tl_i.a_ready;

  assign valid_o      = tl_i.d_valid;
  assign rdata_o      = tl_i.d_data;
  assign rdata_intg_o = tl_i.d_user.data_intg;

  logic intg_err;
  tlul_rsp_intg_chk #(
    .ENABLE_RSP_DATA_INTG_CHECK(ENABLE_RSP_DATA_INTG_CHECK)
  ) u_rsp_chk (
    .tl_i,
    .err_o(intg_err)
  );

  logic intg_err_q;
  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      intg_err_q <= '0;
    end else if (intg_err) begin
      intg_err_q <= 1'b1;
    end
  end

  // err_o is transactional.  This allows the host to continue
  // debug without receiving an endless stream of errors.
  assign err_o   = tl_i.d_error | intg_err;

  // intg_err_o is permanent once detected, and should be used
  // to trigger alerts
  assign intg_err_o = intg_err_q | intg_err;

  // Addresses are assumed to be word-aligned, and the bottom bits are ignored
  logic unused_addr_bottom_bits;
  assign unused_addr_bottom_bits = ^addr_i[WordSize-1:0];

  // Explicitly ignore unused fields of tl_i
  logic unused_tl_i_fields;
  assign unused_tl_i_fields = ^{tl_i.d_opcode, tl_i.d_param,
                                tl_i.d_size, tl_i.d_source, tl_i.d_sink,
                                tl_i.d_user};

`ifdef OCAH_OT_INC_ASSERT
  //VCS coverage off
  // pragma coverage off
  localparam int OutstandingReqCntW =
    (MAX_REQS == 2 ** $clog2(MAX_REQS)) ? $clog2(MAX_REQS) + 1 : $clog2(MAX_REQS);
  localparam logic [OutstandingReqCntW-1:0] OutstandingReqCntOne = OutstandingReqCntW'(1'b1);

  logic [OutstandingReqCntW-1:0] outstanding_reqs_q;
  logic [OutstandingReqCntW-1:0] outstanding_reqs_d;

  always_comb begin
    outstanding_reqs_d = outstanding_reqs_q;

    if ((req_i && gnt_o) && !valid_o) begin
      outstanding_reqs_d = outstanding_reqs_q + OutstandingReqCntOne;
    end else if (!(req_i && gnt_o) && valid_o) begin
      outstanding_reqs_d = outstanding_reqs_q - OutstandingReqCntOne;
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      outstanding_reqs_q <= '0;
    end else begin
      outstanding_reqs_q <= outstanding_reqs_d;
    end
  end
  //VCS coverage on
  // pragma coverage on

  `OCAH_OT_ASSERT(DontExceeedMaxReqs, req_i |-> outstanding_reqs_d <= MAX_REQS)
`endif
endmodule
