// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Bridge a secondary TAP link with optional pipeline and lockup stages.
//
// A SIB on the client scan chain gives access to a 3-bit 3DCR scan register holding
// {tms_hold, stap_sel, config_hold}. TCK and TRST always pass to the host side; while
// stap_sel is set, host TMS follows the client and host_tdi_i replaces the client scan data
// at the SIB input, splicing the secondary TAP into the chain; otherwise host TMS is held at
// tms_hold. config_hold keeps the 3DCR from being reset by the scan reset, leaving only
// TRST. security_disable_i high forces the STAP deselected, drives host_tdo_o low and blocks
// 3DCR updates.
// Host TDO always leaves through a TCK falling-edge lockup flop. SCAN_IN_PIPE adds a
// pipeline stage on the client scan input; TDI_LOCKUP and SCAN_OUT_LOCKUP add lockup
// latches on TDI and scan out.

module jtag_stap #(
  parameter bit  SCAN_IN_PIPE = 0,      // Adds a TCK pipeline stage on the client scan input for
                                        // timing closure.
  parameter bit  TDI_LOCKUP = 0,        // Adds a lockup stage, clocked on the falling edge of TCK,
                                        // on host_tdi_i. Use it where the host TDI crosses a die
                                        // boundary.
  parameter bit  SCAN_OUT_LOCKUP = 0,   // Adds a lockup latch on the client scan output for
                                        // extended scan-chain timing.

  parameter type jtag_scan_ctrl_t = prim_jtag_pkg::jtag_scan_ctrl_t,  // JTAG scan-control struct type.
  parameter type jtag_tap_ctrl_t = prim_jtag_pkg::jtag_tap_ctrl_t  // JTAG TAP-control struct type.
) (
  input  jtag_scan_ctrl_t  client_scan_ctrl_i,  // Client scan-control bundle: clock, resets,
                                                // selection, capture, shift, and update.
  input  logic             client_scan_in_i,  // Client scan data; forwarded to host_tdo_o and,
                                              // while the STAP is deselected, fed to the SIB input.
  output logic             client_scan_out_o,  // Scan output of the STAP's SIB, back onto the
                                               // client chain.

  input  jtag_tap_ctrl_t  client_tap_ctrl_i,  // Client TAP-control bundle: TCK, TMS, and active-low
                                              // TRST.
  input  logic            security_disable_i,  // Active-high disable of this STAP: forces it
                                               // deselected, drives host_tdo_o low and blocks 3DCR
                                               // updates.

  output jtag_tap_ctrl_t  host_tap_ctrl_o,  // Host TAP-control bundle: TCK and TRST pass through;
                                            // TMS follows the client while selected and is
                                            // otherwise the 3DCR tms_hold bit.
  output logic            host_tdo_oen_o,  // Host TDO output enable, active-high while this STAP is
                                           // selected and shifting.
  output logic            host_tdo_o,   // Client scan data through the TCK falling-edge lockup
                                        // flop, toward the secondary TAP's TDI; low while
                                        // security_disable_i is high.
  input  logic            host_tdi_i    // Serial data from the secondary TAP's TDO; replaces the
                                        // client scan data at the SIB input while the STAP is
                                        // selected.
);

  logic stap_scan_in, sib_client_scan_in;
  logic stap_tdi, host_tdo_int;

  jtag_scan_ctrl_t host_sib_scan_ctrl, client_reg_scan_ctrl;
  logic host_sib_scan_in, host_sib_scan_out;
  logic client_reg_scan_in, client_reg_scan_out;
  logic stap_sel, tms_hold, config_hold, stap_sel_int;
  logic config_hold_sticky;
  logic rst_n_or_out, rst_n_gate;

  // Optional client interface scan input pipeline stage
  if (SCAN_IN_PIPE) begin : gen_scan_in_pipe
    prim_flop #(
      .Width(1),
      .ResetValue('0)
    ) u_scan_in_pipe_flop (
      .clk_i  (client_scan_ctrl_i.tck),
      .rst_ni (client_scan_ctrl_i.rst_n),
      .d_i    (client_scan_ctrl_i.shift_en ? client_scan_in_i : stap_scan_in),
      .q_o    (stap_scan_in)
    );
  end else begin : gen_no_scan_in_pipe
    assign stap_scan_in = client_scan_in_i;
  end

  // TDO output lockup latch
  prim_flop #(
    .Width(1),
    .ResetValue('0),
    .Negedge(1'b1)
  ) u_tdo_lockup_flop (
    .clk_i  (client_scan_ctrl_i.tck),
    .rst_ni (client_scan_ctrl_i.rst_n),
    .d_i    (stap_scan_in),
    .q_o    (host_tdo_int)
  );

  // Optional TDI input lockup latch
  if (TDI_LOCKUP) begin : gen_tdi_lockup_latch
    prim_flop #(
      .Width(1),
      .ResetValue('0),
      .Negedge(1'b1)
    ) u_tdi_lockup_flop (
      .clk_i  (client_scan_ctrl_i.tck),
      .rst_ni (client_scan_ctrl_i.rst_n),
      .d_i    (host_tdi_i),
      .q_o    (stap_tdi)
    );
  end else begin : gen_no_tdi_lockup_latch
    assign stap_tdi = host_tdi_i;
  end

  assign sib_client_scan_in = stap_sel ? stap_tdi : stap_scan_in;

  // SIB for the 3DCR, and optional support for a lockup latch on the client interface scan out (the SIB output)
  prim_jtag_sib_mux_pre #(
    .LOCKUP(SCAN_OUT_LOCKUP),
    .jtag_scan_ctrl_t(jtag_scan_ctrl_t)
  ) u_sib_mux_pre (
    .client_scan_ctrl_i  (client_scan_ctrl_i),
    .client_scan_in_i    (sib_client_scan_in),
    .client_scan_out_o   (client_scan_out_o),
    .security_disable_i  (1'b0),

    .host_scan_ctrl_o    (host_sib_scan_ctrl),
    .host_scan_in_i      (host_sib_scan_in),
    .host_scan_out_o     (host_sib_scan_out)
  );

  // Shadow flop: breaks the combinational loop through u_3dcr_scan_reg's
  // async reset pin.  Resets only on trst_n (hard reset), lags config_hold by
  // one TCK cycle.  The one-cycle gap is safe: host_sib_scan_ctrl.rst_n cannot
  // assert within one TCK of an Update-DR write without multiple intermediate
  // TAP state transitions.
  prim_flop #(
    .Width     (1),
    .ResetValue(1'b0),
    .Negedge   (1'b1)
  ) u_config_hold_sticky_flop (
    .clk_i  (client_scan_ctrl_i.tck),
    .rst_ni (client_tap_ctrl_i.trst_n),
    .d_i    (config_hold),
    .q_o    (config_hold_sticky)
  );

  // 3DCR reset control — primitive gates ensure glitch-free reset path
  prim_or2 u_rst_n_or (
    .in0_i (config_hold_sticky),
    .in1_i (host_sib_scan_ctrl.rst_n),
    .out_o (rst_n_or_out)
  );

  prim_and2 #(
    .Width(1)
  ) u_rst_n_and (
    .in0_i (client_tap_ctrl_i.trst_n),
    .in1_i (rst_n_or_out),
    .out_o (rst_n_gate)
  );

  always_comb begin
    client_reg_scan_ctrl           = host_sib_scan_ctrl;
    client_reg_scan_ctrl.update_en = host_sib_scan_ctrl.update_en && !security_disable_i;
    client_reg_scan_ctrl.rst_n     = rst_n_gate;
  end

  assign client_reg_scan_in = host_sib_scan_out;
  assign host_sib_scan_in = client_reg_scan_out;
  assign stap_sel = security_disable_i ? 1'b0 : stap_sel_int;
  assign host_tdo_o = security_disable_i ? 1'b0 : host_tdo_int;

  // STAP 3DCR control register
  prim_jtag_scan_reg #(
    .WIDTH(3),
    .RESET_VAL('0),
    .jtag_scan_ctrl_t(jtag_scan_ctrl_t)
  ) u_3dcr_scan_reg (
    .scan_ctrl_i   (client_reg_scan_ctrl),
    .scan_in_i     (client_reg_scan_in),
    .scan_out_o    (client_reg_scan_out),
    .data_in_i     ({tms_hold, stap_sel, config_hold}),
    .data_out_o    ({tms_hold, stap_sel_int, config_hold})
  );

  // Host TAP control output assignments
  always_comb begin
    host_tap_ctrl_o = client_tap_ctrl_i;
    host_tap_ctrl_o.tms = stap_sel ? client_tap_ctrl_i.tms : tms_hold;
  end

  assign host_tdo_oen_o = stap_sel && client_scan_ctrl_i.shift_en;

endmodule
