// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Open-path environment for the dtp formal top: the reset model that a licensed backend expresses
// with its clock and reset commands. Bound to dtp by the statement at the end of this file and
// read only by the sby task file.
//
// With explicit clock modelling every step is a time point and the asynchronous resets are free
// inputs, so a reset that changes at a tck sampling edge, or between two edges, lands in the state
// register without the sampled `disable iff` seeing it. The environment therefore asserts every
// reset up to the first tck posedge, so that every clock domain starts from its reset state, and
// releases all of them there for the rest of the trace.

`include "ocah_fv_macros.svh"

module dtp_sby_env (
  input logic tck_i,
  input logic trst_ni,
  input logic pwr_on_rst_ni,
  input logic rst_ni,
  input logic scan_rst_ni
);

`ifdef FORMAL
  logic released_q = 1'b0;
  always_ff @(posedge tck_i) released_q <= 1'b1;

  always_comb begin
    asm_env_resets_asserted : assume (released_q || !(trst_ni || pwr_on_rst_ni || rst_ni));
    asm_env_resets_released : assume (!released_q || (trst_ni && pwr_on_rst_ni && rst_ni));
    asm_env_scan_reset_inactive : assume (scan_rst_ni);
  end
`endif

endmodule : dtp_sby_env

bind dtp dtp_sby_env u_dtp_sby_env (
  .tck_i         (jtag_ptap_client_tap_ctrl_i.tck),
  .trst_ni       (jtag_ptap_client_tap_ctrl_i.trst_n),
  .pwr_on_rst_ni (pwr_on_rst_ni),
  .rst_ni        (rst_n_i),
  .scan_rst_ni   (scan_rst_ni)
);
