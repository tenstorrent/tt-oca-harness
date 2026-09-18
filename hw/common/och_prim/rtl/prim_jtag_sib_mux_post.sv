// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// JTAG SIB with MUX After SR Register
//
//--------------------------------------------------
module prim_jtag_sib_mux_post
  import prim_jtag_pkg::*;
#(
  parameter bit  LOCKUP = 0,       // Adds a lockup latch to the output of the scan register
  parameter bit  SAFE_SELECT = 0,  // Adds an additional flop stage to the SIB enable output to avoid a race on the host update_en.

  parameter type jtag_scan_ctrl_t = prim_jtag_pkg::jtag_scan_ctrl_t
) (
  input  jtag_scan_ctrl_t  client_scan_ctrl_i,
  input  logic             client_scan_in_i,
  output logic             client_scan_out_o,
  input  logic             security_disable_i,

  output jtag_scan_ctrl_t  host_scan_ctrl_o,
  input  logic             host_scan_in_i,
  output logic             host_scan_out_o
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
