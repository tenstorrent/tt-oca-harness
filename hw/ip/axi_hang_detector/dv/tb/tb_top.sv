// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// AXI Hang Detector IP-level testbench top for the cocotb flow.
//
// Pin-level shape: every DUT connection is an ANSI port so cocotb drives the
// inputs and samples the outputs directly (same convention as the DTP and
// cross-trigger tb_tops). The IP has no CSR block of its own — its config
// fields live in cpu_ctrl at the SMC level — so the configuration surface is
// plain wires alongside the snoop probes, and the bench needs no bus VIP.
// Clock and reset are driven from cocotb.

`timescale 1ns / 1ps

module axi_hang_detector_tb_top #(
  parameter int unsigned OUTSTANDING_TX = 6
) (
  input  logic        clk,
  input  logic        rst_n,

  // AXI snoop inputs (monitored bus)
  input  logic        snoop_aw_valid_i,
  input  logic        snoop_aw_ready_i,
  input  logic        snoop_w_valid_i,
  input  logic        snoop_b_valid_i,
  input  logic        snoop_b_ready_i,
  input  logic        snoop_ar_valid_i,
  input  logic        snoop_ar_ready_i,
  input  logic        snoop_r_valid_i,
  input  logic        snoop_r_ready_i,
  input  logic        snoop_r_last_i,

  // Configuration (mirrors the cpu_ctrl register fields)
  input  logic        enable_i,
  input  logic        irq_en_i,
  input  logic        irq_test_i,
  input  logic [19:0] threshold_i,

  // Status / interrupt
  output logic        bus_active_o,
  output logic        irq_o
);

  axi_hang_detector #(
    .OUTSTANDING_TX(OUTSTANDING_TX)
  ) u_axi_hang_detector (
    .clk_i           (clk),
    .rst_ni          (rst_n),

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

endmodule
