// Copyright 2023 ETH Zurich and University of Bologna.
// Solderpad Hardware License, Version 0.51, see LICENSE for details.
// SPDX-License-Identifier: SHL-0.51

// Author: Michael Rogenmoser <michaero@iis.ee.ethz.ch>

/// Baseline bus error unit
module bus_err_unit #(
  parameter int unsigned AddrWidth       = 48,
  parameter int unsigned MetaDataWidth   = 1,
  parameter int unsigned ErrBits         = 3,
  parameter int unsigned NumOutstanding  = 4,
  parameter int unsigned NumStoredErrors = 4,
  parameter int unsigned NumReqPorts     = 1,
  parameter int unsigned NumChannels     = 1, // Channels are one-hot!
  parameter bit          DropOldest      = 1'b0,
  parameter type         reg_req_t       = logic,
  parameter type         reg_rsp_t       = logic
) (
  input  logic                                      clk_i,
  input  logic                                      rst_ni,
  input  logic                                      testmode_i,

  input  logic [NumReqPorts-1:0][  NumChannels-1:0] req_hs_valid_i,
  input  logic [NumReqPorts-1:0][    AddrWidth-1:0] req_addr_i,
  input  logic [NumReqPorts-1:0][MetaDataWidth-1:0] req_meta_i,
  input  logic                  [  NumChannels-1:0] rsp_hs_valid_i,
  input  logic                  [  NumChannels-1:0] rsp_burst_last_i,
  input  logic                  [      ErrBits-1:0] rsp_err_i,

  output logic                                      err_irq_o,

  input  reg_req_t                                  reg_req_i,
  output reg_rsp_t                                  reg_rsp_o

);

  logic [    AddrWidth-1:0] read_err_addr;
  logic [MetaDataWidth-1:0] read_err_meta;
  logic [      ErrBits-1:0] read_err_err;
  logic                     read_err_overflow;

  bus_err_unit_reg_pkg::bus_err_unit_reg2hw_t reg2hw;
  bus_err_unit_reg_pkg::bus_err_unit_hw2reg_t hw2reg;

  assign hw2reg.err_addr.d = read_err_addr[31:0];
  if (AddrWidth > 32) begin
    always_comb begin
      hw2reg.err_addr_top.d = '0;
      hw2reg.err_addr_top.d[AddrWidth-32-1:0] = read_err_addr[AddrWidth-1:32];
    end
  end else begin
    assign hw2reg.err_addr_top.d = '0;
  end
  always_comb begin : proc_err_code
    hw2reg.err_code.d = '0;
    hw2reg.err_code.d[ErrBits-1:0] = read_err_err;
    hw2reg.err_code.d[31] = read_err_overflow;
  end
  always_comb begin
    hw2reg.meta.d = '0;
    hw2reg.meta.d[MetaDataWidth-1:0] = read_err_meta;
  end

  bus_err_unit_reg_top #(
    .reg_req_t ( reg_req_t ),
    .reg_rsp_t ( reg_rsp_t )
  ) i_regs (
    .clk_i,
    .rst_ni,
    .reg_req_i,
    .reg_rsp_o,
    .reg2hw (reg2hw),
    .hw2reg (hw2reg),
    .devmode_i ('0)
  );

  bus_err_unit_bare #(
    .AddrWidth      ( AddrWidth       ),
    .MetaDataWidth  ( MetaDataWidth   ),
    .ErrBits        ( ErrBits         ),
    .NumOutstanding ( NumOutstanding  ),
    .NumStoredErrors( NumStoredErrors ),
    .NumReqPorts    ( NumReqPorts     ),
    .NumChannels    ( NumChannels     ),
    .DropOldest     ( DropOldest      )
  ) i_err_unit_bare (
    .clk_i,
    .rst_ni,
    .testmode_i,

    .req_hs_valid_i,
    .req_addr_i,
    .req_meta_i,
    .rsp_hs_valid_i,
    .rsp_burst_last_i,
    .rsp_err_i,

    .err_irq_o,

    .err_fifo_pop_i  ( reg2hw.err_code.re ),
    .err_code_o      ( read_err_err       ),
    .err_addr_o      ( read_err_addr      ),
    .err_meta_o      ( read_err_meta      ),
    .err_fifo_overflow_o( read_err_overflow )
  );

endmodule
