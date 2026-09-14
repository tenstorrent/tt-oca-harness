// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// AXI Hang Detector Testbench
//
// Thin SystemVerilog wrapper around axi_hang_detector for cocotb-driven unit
// tests of the timeout-counter datapath. The IP has no CSR block of its own
// (its config fields live in cpu_ctrl at the SMC level), so this wrapper just
// exposes the configuration as plain wires alongside the snoop probes and the
// interrupt / bus-active outputs.
//
// Copyright 2026 Tenstorrent Inc.
//-----------------------------------------------------------------------------

module tb_axi_hang_detector #(
  parameter int unsigned OutstandingTx = 6
) (
  // Global Interface
  input  logic                       clk_i,
  input  logic                       rst_ni,

  // AXI snoop inputs (monitored bus)
  input  logic                       snoop_aw_valid_i,
  input  logic                       snoop_aw_ready_i,
  input  logic                       snoop_w_valid_i,
  input  logic                       snoop_b_valid_i,
  input  logic                       snoop_b_ready_i,
  input  logic                       snoop_ar_valid_i,
  input  logic                       snoop_ar_ready_i,
  input  logic                       snoop_r_valid_i,
  input  logic                       snoop_r_ready_i,
  input  logic                       snoop_r_last_i,

  // Configuration (mirrors the cpu_ctrl register fields)
  input  logic                       enable_i,
  input  logic                       irq_en_i,
  input  logic                       irq_test_i,
  input  logic [19:0]                threshold_i,

  // Status / interrupt
  output logic                       bus_active_o,
  output logic                       irq_o
);

  axi_hang_detector #(
    .OutstandingTx(OutstandingTx)
  ) u_axi_hang_detector (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),

    .snoop_aw_valid_i(snoop_aw_valid_i),
    .snoop_aw_ready_i(snoop_aw_ready_i),
    .snoop_w_valid_i (snoop_w_valid_i),
    .snoop_b_valid_i (snoop_b_valid_i),
    .snoop_b_ready_i (snoop_b_ready_i),
    .snoop_ar_valid_i(snoop_ar_valid_i),
    .snoop_ar_ready_i(snoop_ar_ready_i),
    .snoop_r_valid_i (snoop_r_valid_i),
    .snoop_r_ready_i (snoop_r_ready_i),
    .snoop_r_last_i  (snoop_r_last_i),

    .enable_i        (enable_i),
    .irq_en_i        (irq_en_i),
    .irq_test_i      (irq_test_i),
    .threshold_i     (threshold_i),

    .bus_active_o    (bus_active_o),
    .irq_o           (irq_o)
  );

  //////////////////////
  // Waveform Dumping //
  //////////////////////

`ifndef VERILATOR
  initial begin
    if ($test$plusargs("waves")) begin
      $fsdbDumpfile("test.fsdb");
      $fsdbDumpvars(0, tb_axi_hang_detector);
      $fsdbDumpvars("+all");
    end
  end
`endif

endmodule
