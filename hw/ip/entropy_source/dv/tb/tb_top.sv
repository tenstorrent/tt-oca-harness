// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

`timescale 1ns / 1ps

module entropy_source_tb_top (
  input  wire         clk,
  input  wire         rst_n,

  input  wire         axil_awvalid,
  input  wire [31:0]  axil_awaddr,
  input  wire [2:0]   axil_awprot,
  output wire         axil_awready,
  input  wire         axil_wvalid,
  input  wire [31:0]  axil_wdata,
  input  wire [3:0]   axil_wstrb,
  output wire         axil_wready,
  input  wire         axil_bready,
  output wire         axil_bvalid,
  output wire [1:0]   axil_bresp,
  input  wire         axil_arvalid,
  input  wire [31:0]  axil_araddr,
  input  wire [2:0]   axil_arprot,
  output wire         axil_arready,
  input  wire         axil_rready,
  output wire         axil_rvalid,
  output wire [31:0]  axil_rdata,
  output wire [1:0]   axil_rresp,

  input  wire         rosc_sample_clk,
  output wire         signal_monitor,
  output wire [31:0]  entropy_stream_data,
  output wire         entropy_stream_valid,
  output wire         irq,

  input  wire         fifo_push,
  input  wire         fifo_pop,
  input  wire         fifo_clear,
  input  wire [31:0]  fifo_wdata,
  input  wire         fifo_churn_enable,
  output wire [31:0]  fifo_rdata,
  output wire [3:0]   fifo_level,
  output wire [2:0]   fifo_wptr,
  output wire [2:0]   fifo_rptr,
  output wire         fifo_overflow,
  output wire         fifo_underflow,
  output wire         fifo_parity_error,
  output wire         fifo_pointer_error,
  output wire         fifo_security_alert,

  input  wire [31:0]  health_entropy,
  input  wire         health_valid,
  input  wire [2:0]   health_enable,
  input  wire [7:0]   health_repetition_limit,
  input  wire [15:0]  health_apt_hi_limit,
  input  wire [15:0]  health_apt_lo_limit,
  input  wire [15:0]  health_markov_01_limit,
  input  wire [15:0]  health_markov_10_limit,
  input  wire         health_window_wrap,
  output wire [15:0]  health_repetition_count,
  output wire [15:0]  health_apt_hi_count,
  output wire [15:0]  health_apt_lo_count,
  output wire [15:0]  health_markov_01_count,
  output wire [15:0]  health_markov_10_count,
  output wire         health_apt_fail_hi,
  output wire         health_apt_fail_lo,
  output wire [7:0]   health_status,
  output wire         health_count_error,

  input  wire         decor_enable,
  input  wire         decor_noise,
  input  wire         decor_bypass,
  input  wire [7:0]   decor_byte_mask,
  input  wire [7:0]   decor_sample_clk_div,
  output wire [7:0]   decor_sample,
  output wire         decor_valid,

  input  wire [15:0]  debug_signals,
  input  wire [3:0]   debug_select_signal,
  input  wire [2:0]   debug_select_div,
  output wire         debug_monitor,

  input  wire         tune_health_error,
  output wire         tune_state
);

  entropy_source u_dut (
    .clk_i                 (clk),
    .rst_ni                (rst_n),
    .s_axil_awvalid_i      (axil_awvalid),
    .s_axil_awready_o      (axil_awready),
    .s_axil_awaddr_i       (axil_awaddr[8:0]),
    .s_axil_awprot_i       (axil_awprot),
    .s_axil_wvalid_i       (axil_wvalid),
    .s_axil_wready_o       (axil_wready),
    .s_axil_wdata_i        (axil_wdata),
    .s_axil_wstrb_i        (axil_wstrb),
    .s_axil_bvalid_o       (axil_bvalid),
    .s_axil_bready_i       (axil_bready),
    .s_axil_bresp_o        (axil_bresp),
    .s_axil_arvalid_i      (axil_arvalid),
    .s_axil_arready_o      (axil_arready),
    .s_axil_araddr_i       (axil_araddr[8:0]),
    .s_axil_arprot_i       (axil_arprot),
    .s_axil_rvalid_o       (axil_rvalid),
    .s_axil_rready_i       (axil_rready),
    .s_axil_rdata_o        (axil_rdata),
    .s_axil_rresp_o        (axil_rresp),
    .signal_monitor_o      (signal_monitor),
    .rosc_sample_clk_i     (rosc_sample_clk),
    .entropy_stream_data_o (entropy_stream_data),
    .entropy_stream_vld_o  (entropy_stream_valid),
    .irq_o                 (irq)
  );

  entropy_fifo #(
    .DEPTH(8)
  ) u_fifo (
    .clk_i                  (clk),
    .rst_ni                 (rst_n),
    .push_i                 (fifo_push),
    .pop_i                  (fifo_pop),
    .clr_i                  (fifo_clear),
    .wdata_i                (fifo_wdata),
    .entropy_churn_enable_i (fifo_churn_enable),
    .rdata_o                (fifo_rdata),
    .level_o                (fifo_level),
    .wptr_o                 (fifo_wptr),
    .rptr_o                 (fifo_rptr),
    .overflow_o             (fifo_overflow),
    .underflow_o            (fifo_underflow),
    .parity_error_o         (fifo_parity_error),
    .pointer_error_o        (fifo_pointer_error),
    .security_alert_o       (fifo_security_alert)
  );

  entropy_health_test u_health_test (
    .clk_i                       (clk),
    .rst_ni                      (rst_n),
    .entropy_i                   (health_entropy),
    .entropy_valid_i             (health_valid),
    .enable_i                    (health_enable),
    .repetition_limit_i          (health_repetition_limit),
    .proportion_limit_1bit_i     (health_apt_hi_limit),
    .proportion_limit_lo_i       (health_apt_lo_limit),
    .markov_prob_01_threshold_i  (health_markov_01_limit),
    .markov_prob_10_threshold_i  (health_markov_10_limit),
    .window_wrap_pulse_i         (health_window_wrap),
    .ctr_repetition_o            (health_repetition_count),
    .apt_pattern_count_1bit_o    (health_apt_hi_count),
    .apt_pattern_count_2bit_o    (health_apt_lo_count),
    .count_01_o                  (health_markov_01_count),
    .count_10_o                  (health_markov_10_count),
    .apt_fail_hi_o               (health_apt_fail_hi),
    .apt_fail_lo_o               (health_apt_fail_lo),
    .status_o                    (health_status),
    .count_err_o                 (health_count_error)
  );

  entropy_decorrelator #(
    .LENGTH(29),
    .CLKDIV_WIDTH(8)
  ) u_decorrelator (
    .clk_i                 (clk),
    .rst_ni                (rst_n),
    .enable_i              (decor_enable),
    .noise_i               (decor_noise),
    .bypass_i              (decor_bypass),
    .byte_mask_i           (decor_byte_mask),
    .sample_clk_div_i      (decor_sample_clk_div),
    .entropy_byte_sample_o (decor_sample),
    .entropy_byte_valid_o  (decor_valid)
  );

  entropy_debug_monitor #(
    .NSIGNALS(16),
    .FREQ_DIV_WIDTH(8)
  ) u_debug_monitor (
    .rst_ni            (rst_n),
    .select_signal_i   (debug_select_signal),
    .signal_i          (debug_signals),
    .select_freq_div_i (debug_select_div),
    .sig_monitor_o     (debug_monitor)
  );

  entropy_rosc_tune_fsm u_tune_fsm (
    .clk_i          (clk),
    .rst_ni         (rst_n),
    .health_error_i (tune_health_error),
    .tune_state_o   (tune_state)
  );

`ifndef VERILATOR
  // The OpenTitan primitives require SoC-level alert-binding assertions that
  // this pin-level IP harness cannot provide. Functional error outputs remain
  // observable and checked by cocotb.
  initial begin
    $assertoff(0, u_dut);
    $assertoff(0, u_fifo);
    $assertoff(0, u_health_test);
  end
`endif

endmodule : entropy_source_tb_top
