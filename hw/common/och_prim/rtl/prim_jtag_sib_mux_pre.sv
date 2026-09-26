// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Insert a JTAG SIB that muxes the host chain before the local scan register.
//
// security_disable_i forces the SIB closed.
// SAFE_SELECT adds a flop on SIB enable to avoid a race on the host update_en.
// LOCKUP passes through to the nested scan register.

module prim_jtag_sib_mux_pre
  import prim_jtag_pkg::*;
#(
  parameter bit  LOCKUP = 0,  // Adds a lockup latch on the nested scan-register output.
  parameter bit  SAFE_SELECT = 0,  // Flops SIB enable to avoid a race on the host update_en.

  parameter type jtag_scan_ctrl_t = prim_jtag_pkg::jtag_scan_ctrl_t  // Scan-control struct type.
) (
  input  jtag_scan_ctrl_t  client_scan_ctrl_i,  // Client-side scan control.
  input  logic             client_scan_in_i,  // Client serial scan in.
  output logic             client_scan_out_o,  // Client serial scan out.
  input  logic             security_disable_i,  // Forces the SIB closed when high.

  output jtag_scan_ctrl_t  host_scan_ctrl_o,  // Host-side scan control.
  input  logic             host_scan_in_i,  // Host serial scan in.
  output logic             host_scan_out_o  // Host serial scan out.
);

  jtag_scan_ctrl_t scan_reg_scan_ctrl;
  logic scan_register_scan_in, sib_en, sib_en_masked, sib_en_out;

  assign sib_en_masked = security_disable_i ? 1'b0 : sib_en;
  assign scan_register_scan_in = sib_en_masked ? host_scan_in_i : client_scan_in_i;

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
    .scan_in_i     (scan_register_scan_in),
    .scan_out_o    (client_scan_out_o),
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
  assign host_scan_out_o = security_disable_i ? 1'b0 : client_scan_in_i;

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
