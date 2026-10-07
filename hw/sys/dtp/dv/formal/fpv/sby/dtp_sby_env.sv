// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Open-path environment for the dtp formal top: the reset model that a licensed backend expresses
// with its clock and reset commands, and the far ends of the external scan chains. Bound to dtp by
// the statement at the end of this file and read only by the sby task file.
//
// With explicit clock modelling every step is a time point and the asynchronous resets are free
// inputs, so a reset that changes at a tck sampling edge, or between two edges, lands in the state
// register without the sampled `disable iff` seeing it. The environment therefore asserts the
// resets up to the first tck posedge and releases all of them there for the rest of the trace.
// TRST and the power-on reset each reset the TAP alone, so before that edge they take any values
// with at least one of them low, and the system reset is low. Every flop then starts from its
// reset state except the dbg_disable_i synchronizers, which the power-on reset alone clears and
// which start from any value when TRST alone is low.
//
// The external scan chains and the downstream TAPs are JTAG slaves whose return data changes on
// the falling edge of tck (IEEE 1149.1 §4.5.1), so the value each return input presents at a
// rising edge holds through the high phase; the DTP passes a selected return through to TDO.

`include "ocah_fv_macros.svh"

module dtp_sby_env #(
  parameter int unsigned NUM_EXTRA_STAP = 1
) (
  input logic tck_i,
  input logic trst_ni,
  input logic pwr_on_rst_ni,
  input logic rst_ni,
  input logic scan_rst_ni,
  input logic test_en_i,
  // Return data of the external scan chains and of the downstream TAPs
  input logic stap_scan_in_i,
  input logic bsr_scan_in_i,
  input logic dfd_scan_in_i,
  input logic dft_scan_in_i,
  input logic dft_secure_scan_in_i,
  input logic stap_io_tdi_i,
  input logic stap_smc_tdi_i,
  input logic stap_sep_tdi_i,
  input logic stap_extra_tdi_i [NUM_EXTRA_STAP-1:0]
);

  localparam int unsigned NumReturns = 8 + NUM_EXTRA_STAP;

`ifdef FORMAL
  logic released_q = 1'b0;
  always_ff @(posedge tck_i) released_q <= 1'b1;

  always_comb begin
    asm_env_resets_asserted : assume (released_q || !((trst_ni && pwr_on_rst_ni) || rst_ni));
    asm_env_resets_released : assume (!released_q || (trst_ni && pwr_on_rst_ni && rst_ni));
    // The RTL leaves the scan reset unconnected.
    asm_env_scan_reset_inactive : assume (scan_rst_ni);
    // Functional operation holds DFT test mode off.
    asm_env_test_mode_inactive : assume (!test_en_i);
  end

  logic [NumReturns-1:0] returns, returns_at_posedge_q;
  always_comb begin
    returns[7:0] = {
      stap_scan_in_i,
      bsr_scan_in_i,
      dfd_scan_in_i,
      dft_scan_in_i,
      dft_secure_scan_in_i,
      stap_io_tdi_i,
      stap_smc_tdi_i,
      stap_sep_tdi_i
    };
    for (int unsigned i = 0; i < NUM_EXTRA_STAP; i++) returns[8+i] = stap_extra_tdi_i[i];
  end

  // The trace's first high phase has no rising edge before it.
  logic posedge_seen_q = 1'b0;
  always_ff @(posedge tck_i) begin
    posedge_seen_q       <= 1'b1;
    returns_at_posedge_q <= returns;
  end

  always_comb begin
    if (tck_i && posedge_seen_q) begin
      `OCAH_FV_ASSUME_I(asm_env_scan_returns_hold_while_tck_high, returns == returns_at_posedge_q)
    end
  end
`endif

endmodule : dtp_sby_env

bind dtp dtp_sby_env #(
  .NUM_EXTRA_STAP(JtagNumExtraStapPorts)
) u_dtp_sby_env (
  .tck_i                (jtag_ptap_client_tap_ctrl_i.tck),
  .trst_ni              (jtag_ptap_client_tap_ctrl_i.trst_n),
  .pwr_on_rst_ni        (pwr_on_rst_ni),
  .rst_ni               (rst_n_i),
  .scan_rst_ni          (scan_rst_ni),
  .test_en_i            (test_en_i),
  .stap_scan_in_i       (jtag_stap_host_scan_in_i),
  .bsr_scan_in_i        (jtag_bsr_host_scan_in_i),
  .dfd_scan_in_i        (jtag_dfd_host_scan_in_i),
  .dft_scan_in_i        (jtag_dft_host_scan_in_i),
  .dft_secure_scan_in_i (jtag_dft_secure_host_scan_in_i),
  .stap_io_tdi_i        (jtag_stap_io_host_tdi_i),
  .stap_smc_tdi_i       (jtag_stap_smc_host_tdi_i),
  .stap_sep_tdi_i       (jtag_stap_sep_host_tdi_i),
  .stap_extra_tdi_i     (jtag_stap_extra_host_tdi_i)
);
