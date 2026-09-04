// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// Entropy Sourfce Testbench
//
//-----------------------------------------------------------------------------

module tb_entropy_source (
  // Global Interface
  input  logic                          clk_i,
  input  logic                          rst_ni,

  // APB4 Register Interface
  input  entropy_source_pkg::reg_addr_t paddr_i,
  input  logic [2:0]                    pprot_i,
  input  logic                          psel_i,
  input  logic                          penable_i,
  input  logic                          pwrite_i,
  input  entropy_source_pkg::reg_data_t pwdata_i,
  input  entropy_source_pkg::reg_strb_t pstrb_i,
  output logic                          pready_o,
  output entropy_source_pkg::reg_data_t prdata_o,
  output logic                          pslverr_o,

  output logic                          signal_monitor_o,
  input  logic                          rosc_sample_clk_i,

  output logic [31:0]                   entropy_stream_data_o,
  output logic                          entropy_stream_vld_o,
  output logic                          irq_o
);

  entropy_source entropy_source (
    // Global Interface
    .clk_i,
    .rst_ni,

    // APB4 Register Interface
    .paddr_i,
    .pprot_i,
    .psel_i,
    .penable_i,
    .pwrite_i,
    .pwdata_i,
    .pstrb_i,
    .pready_o,
    .prdata_o,
    .pslverr_o,

    .signal_monitor_o,
    .rosc_sample_clk_i,

    .entropy_stream_data_o,
    .entropy_stream_vld_o,
    .irq_o
  );

`ifndef VERILATOR
  initial begin
    if ($test$plusargs("waves")) begin
      $fsdbDumpfile("test.fsdb");
      $fsdbDumpvars(0, tb_entropy_source);
      $fsdbDumpvars("+all");
    end
  end
`endif

endmodule
