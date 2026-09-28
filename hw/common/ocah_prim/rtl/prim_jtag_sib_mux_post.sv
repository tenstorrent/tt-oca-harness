// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Insert a JTAG SIB that muxes the host chain after the local scan register.
//
// The chain runs from client_scan_in_i through the one-bit SIB register, then, while the SIB
// is open, out on host_scan_out_o and back on host_scan_in_i to client_scan_out_o.
// security_disable_i forces the SIB closed, blocks updates of the SIB bit, and gates the
// host capture, shift and update enables.
// SAFE_SELECT adds a falling-edge TCK flop, reset by rst_n, on SIB enable to avoid a race on
// the host update_en.
// LOCKUP passes through to the nested scan register.

module prim_jtag_sib_mux_post
  import prim_jtag_pkg::*;
#(
  parameter bit  LOCKUP = 0,  // Adds a falling-edge TCK lockup flop on the SIB register's scan
                              // output.
  parameter bit  SAFE_SELECT = 0,  // Flops SIB enable to avoid a race on the host update_en.

  parameter type jtag_scan_ctrl_t = prim_jtag_pkg::jtag_scan_ctrl_t  // Scan-control struct type.
) (
  input  jtag_scan_ctrl_t  client_scan_ctrl_i,  // Client-side scan control.
  input  logic             client_scan_in_i,  // Client serial scan in; feeds the SIB register.
  output logic             client_scan_out_o,  // host_scan_in_i while the SIB is open, else the SIB
                                               // bit.
  input  logic             security_disable_i,  // Forces the SIB closed when high.

  output jtag_scan_ctrl_t  host_scan_ctrl_o,  // Client control with capture, shift and update gated
                                              // by the client select and security_disable_i, and
                                              // select also gated by the SIB enable.
  input  logic             host_scan_in_i,  // Serial return from the host segment.
  output logic             host_scan_out_o  // SIB bit toward the host segment; low while
                                            // security_disable_i is high.
);

  jtag_scan_ctrl_t scan_reg_scan_ctrl;
  logic scan_reg_scan_out, sib_en, sib_en_masked, sib_en_out;

  assign sib_en_masked = security_disable_i ? 1'b0 : sib_en;

  always_comb begin
    scan_reg_scan_ctrl = client_scan_ctrl_i;
    scan_reg_scan_ctrl.update_en = client_scan_ctrl_i.update_en && !security_disable_i;
  end

  prim_jtag_scan_reg #(
    .LOCKUP(LOCKUP),
    .WIDTH(1),
    .RESET_VAL('0),
    .jtag_scan_ctrl_t(jtag_scan_ctrl_t)
  ) u_scan_reg (
    .scan_ctrl_i   (scan_reg_scan_ctrl),
    .scan_in_i     (client_scan_in_i),
    .scan_out_o    (scan_reg_scan_out),
    .data_in_i     (sib_en_masked),
    .data_out_o    (sib_en)
  );

  if (SAFE_SELECT) begin : gen_safe_select
    prim_flop #(
      .Width(1),
      .ResetValue('0),
      .Negedge(1'b1)
    ) u_sib_en_flop (
      .clk_i  (client_scan_ctrl_i.tck),
      .rst_ni (client_scan_ctrl_i.rst_n),
      .d_i    (sib_en_masked),
      .q_o    (sib_en_out)
    );
  end else begin : gen_no_safe_select
    assign sib_en_out = sib_en_masked;
  end

  // Output assignments
  assign host_scan_out_o = security_disable_i ? 1'b0 : scan_reg_scan_out;
  assign client_scan_out_o = sib_en_masked ? host_scan_in_i : scan_reg_scan_out;

  always_comb begin
    host_scan_ctrl_o = client_scan_ctrl_i;
    host_scan_ctrl_o.capture_en = client_scan_ctrl_i.capture_en && client_scan_ctrl_i.select &&
                                      !security_disable_i;
    host_scan_ctrl_o.shift_en = client_scan_ctrl_i.shift_en && client_scan_ctrl_i.select &&
                                    !security_disable_i;
    host_scan_ctrl_o.update_en = client_scan_ctrl_i.update_en && client_scan_ctrl_i.select &&
                                     !security_disable_i;
    host_scan_ctrl_o.select = client_scan_ctrl_i.select && sib_en_out;
  end

endmodule
