// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC clock-domain functional coverage: which blocks were seen advancing in
// the domain the clock chapter assigns them to. Each point samples an
// observable of the block on the clock the spec names, so a hit means the
// block moved while that clock was running.
//
// smc_clk_fcov carries the domain-ratio and clock-gating points.
//
// One instance in the shared tb_top serves both flows. Every port is a
// smc_tb_signal_list.svh signal or a smc_wrapper boundary port.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use.

`include "ocah_fcov_macros.svh"

module smc_clk_domain_fcov (
  input wire clk_ref_i,
  input wire clk_smc_i,
  input wire clk_periph_i,
  input wire rst_cold_ni,

  // SMC domain: hart 0 retirement.
  input wire cpu_trace_valid_i,

  // Reference domain: the OCTS system timer count.
  input wire [63:0] timer_count_i,

  // Peripheral domain: pad-side activity of the AVSBus and UART0 blocks.
  input wire avs_clk_i,
  input wire uart0_tx_i
);

  wire in_reset = (rst_cold_ni !== 1'b1);

  wire cpu_retires_on_clk_smc_e = (cpu_trace_valid_i === 1'b1);
  `OCAH_FCOV_COVER(c_cpu_retires_on_clk_smc, cpu_retires_on_clk_smc_e, clk_smc_i, in_reset)

  logic [63:0] timer_count_q;
  always_ff @(posedge clk_ref_i) timer_count_q <= timer_count_i;
  wire octs_tick_on_clk_ref_e = (timer_count_i !== timer_count_q) && (^timer_count_q !== 1'bx);
  `OCAH_FCOV_COVER(c_octs_tick_on_clk_ref, octs_tick_on_clk_ref_e, clk_ref_i, in_reset)

  logic avs_clk_q, uart0_tx_q;
  always_ff @(posedge clk_periph_i) begin
    avs_clk_q <= avs_clk_i;
    uart0_tx_q <= uart0_tx_i;
  end
  wire avsbus_on_clk_periph_e = (avs_clk_i !== avs_clk_q) && (avs_clk_q !== 1'bx);
  wire uart_on_clk_periph_e = (uart0_tx_i !== uart0_tx_q) && (uart0_tx_q !== 1'bx);
  `OCAH_FCOV_COVER(c_avsbus_on_clk_periph, avsbus_on_clk_periph_e, clk_periph_i, in_reset)
  `OCAH_FCOV_COVER(c_uart_on_clk_periph, uart_on_clk_periph_e, clk_periph_i, in_reset)

endmodule : smc_clk_domain_fcov
