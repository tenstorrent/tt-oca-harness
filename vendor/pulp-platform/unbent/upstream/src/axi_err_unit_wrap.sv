// Copyright 2023 ETH Zurich and University of Bologna.
// Solderpad Hardware License, Version 0.51, see LICENSE for details.
// SPDX-License-Identifier: SHL-0.51

// Author: Michael Rogenmoser <michaero@iis.ee.ethz.ch>

/// AXI wrapper for the bus error unit
module axi_err_unit_wrap #(
  parameter int unsigned AddrWidth = 32,
  parameter int unsigned IdWidth   = 2,
  parameter int unsigned UserErrBits   = 0,
  parameter int unsigned UserErrBitsOffset = 0,
  parameter int unsigned NumOutstanding = 4,
  parameter int unsigned NumStoredErrors = 1,
  parameter bit          DropOldest        = 1'b0,
  parameter type axi_req_t = logic,
  parameter type axi_rsp_t = logic,
  parameter type reg_req_t = logic,
  parameter type reg_rsp_t = logic
) (
  input  logic clk_i,
  input  logic rst_ni,
  input  logic testmode_i,

  input axi_req_t axi_req_i,
  input axi_rsp_t axi_rsp_i,

  output logic [1:0] err_irq_o,

  input  reg_req_t reg_req_i,
  output reg_rsp_t reg_rsp_o
);

  logic [2**IdWidth-1:0] write_req_hs_valid, write_rsp_hs_valid, read_req_hs_valid, read_rsp_hs_valid, amo_r_req_hs_valid;
  logic [UserErrBits+2-1:0] write_err, read_err;
  reg_req_t [1:0] reg_req_internal;
  reg_rsp_t [1:0] reg_rsp_internal;

  for (genvar i = 0; i < 2**IdWidth; i++) begin
    assign write_req_hs_valid[i] = axi_req_i.aw_valid & axi_rsp_i.aw_ready & (axi_req_i.aw.id == i);
    assign write_rsp_hs_valid[i] = axi_rsp_i.b_valid  & axi_req_i.b_ready  & (axi_rsp_i.b.id == i);
    assign read_req_hs_valid[i]  = axi_req_i.ar_valid & axi_rsp_i.ar_ready & (axi_req_i.ar.id == i);
    assign read_rsp_hs_valid[i]  = axi_rsp_i.r_valid  & axi_req_i.r_ready  & (axi_rsp_i.r.id == i);
    // This is an atomic with an R response -> push read address from AW channel
    assign amo_r_req_hs_valid[i] = write_req_hs_valid[i] & axi_req_i.aw.atop[axi_pkg::ATOP_R_RESP];
  end

  assign write_err[1:0] = axi_rsp_i.b.resp[1] ? axi_rsp_i.b.resp : '0;
  assign read_err[1:0] = axi_rsp_i.r.resp[1] ? axi_rsp_i.r.resp : '0;

  if (UserErrBits > 0) begin
    assign write_err[UserErrBits+2-1:2] = axi_rsp_i.b.user[UserErrBits+UserErrBitsOffset-1:UserErrBitsOffset];
    assign read_err[UserErrBits+2-1:2] = axi_rsp_i.r.user[UserErrBits+UserErrBitsOffset-1:UserErrBitsOffset];
  end

  reg_demux #(
    .NoPorts    ( 2 ),
    .req_t      ( reg_req_t ),
    .rsp_t      ( reg_rsp_t )
  ) i_reg_demux (
    .clk_i,
    .rst_ni,
    .in_select_i(reg_req_i.addr[5]),
    .in_req_i   (reg_req_i),
    .in_rsp_o   (reg_rsp_o),
    .out_req_o  (reg_req_internal),
    .out_rsp_i  (reg_rsp_internal)
  );

  bus_err_unit #(
    .AddrWidth      (AddrWidth),
    .MetaDataWidth  (IdWidth),
    .ErrBits        (2 + UserErrBits),
    .NumOutstanding (NumOutstanding),
    .NumStoredErrors(NumStoredErrors),
    .NumReqPorts    (1),
    .NumChannels    (2**IdWidth),
    .DropOldest     (DropOldest),
    .reg_req_t      (reg_req_t),
    .reg_rsp_t      (reg_rsp_t)
  ) i_write_err_unit (
    .clk_i,
    .rst_ni,
    .testmode_i,

    .req_hs_valid_i   ( write_req_hs_valid ),
    .req_addr_i       ( axi_req_i.aw.addr  ),
    .req_meta_i       ( axi_req_i.aw.id    ),
    .rsp_hs_valid_i   ( write_rsp_hs_valid ),
    .rsp_burst_last_i ( write_rsp_hs_valid ),
    .rsp_err_i        ( write_err          ),

    .err_irq_o        ( err_irq_o[0]       ),

    .reg_req_i        (reg_req_internal[0]),
    .reg_rsp_o        (reg_rsp_internal[0])
  );

  bus_err_unit #(
    .AddrWidth      (AddrWidth),
    .MetaDataWidth  (IdWidth),
    .ErrBits        (2 + UserErrBits),
    .NumOutstanding (NumOutstanding),
    .NumStoredErrors(NumStoredErrors),
    .NumReqPorts    (2),
    .NumChannels    (2**IdWidth),
    .DropOldest     (DropOldest),
    .reg_req_t      (reg_req_t),
    .reg_rsp_t      (reg_rsp_t)

  ) i_read_err_unit (
    .clk_i,
    .rst_ni,
    .testmode_i,

    .req_hs_valid_i   ( {amo_r_req_hs_valid, read_req_hs_valid} ),
    .req_addr_i       ( {axi_req_i.aw.addr, axi_req_i.ar.addr} ),
    .req_meta_i       ( {axi_req_i.aw.id, axi_req_i.ar.id} ),
    .rsp_hs_valid_i   ( read_rsp_hs_valid  ),
    .rsp_burst_last_i ( read_rsp_hs_valid & {2**IdWidth{axi_rsp_i.r.last}} ),
    .rsp_err_i        ( read_err ),

    .err_irq_o        ( err_irq_o[1] ),

    .reg_req_i        (reg_req_internal[1]),
    .reg_rsp_o        (reg_rsp_internal[1])

  );

endmodule
