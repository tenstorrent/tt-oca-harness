// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Implement the IEEE 1149.1-2013 §17 IC_RESET TDR.
//
// Present the override controls to consumers with conventional polarity.
//
// Per reset port the TDR stores reset_enable and reset_control, plus a single reset_hold
// bit nearest TDO. reset_hold resets to 1 only on tap_ctrl_i.trst_n; while it is 0 the
// scan-control reset does not clear reset_enable and reset_control:
//
// - Despite its name, reset_enable is active-low: POR/TRST default 1 means JTAG override
//   disabled so the normal reset path passes through; writing 0 enables override for
//   that port.
// - reset_control is the active-low reset value driven when override is enabled.
//
// Outputs:
//
// - ic_reset_ovrd_o[i] = !reset_enable[i] (active-high, 1 means JTAG is overriding).
// - ic_reset_ctrl_n_o[i] = reset_control[i].
//
// Downstream jtag_ptap forwards ic_reset_ovrd_o into the .ovrd member of per-slice reset
// structs that select a reset multiplexer for SMC, SEP, or external consumers.
//
// Program reset_control and reset_enable for a port in separate Update-DR operations,
// reset_control first.
// Consumers mux with prim_rst_mux2_hf_n, which is hazard-free only while the select moves
// alone; both fields moving in one update can pulse a reset neither source is asserting.

module jtag_ic_reset_reg
  import prim_jtag_pkg::*;
#(
  parameter int unsigned NUM_IC_RESET_PORTS = 3  // Number of IC reset ports.
) (
  input  jtag_scan_ctrl_t  scan_ctrl_i,  // JTAG DR/IR scan control.
  input  logic             scan_in_i,   // Scan data in (TDI).
  output logic             scan_out_o,  // Scan data out (TDO).

  /* verilator lint_off UNUSEDSIGNAL */
  input  jtag_tap_ctrl_t   tap_ctrl_i,  // JTAG TAP control; only trst_n is used, as the reset of
                                        // reset_hold.
  /* verilator lint_on UNUSEDSIGNAL */

  output logic [NUM_IC_RESET_PORTS-1:0]  ic_reset_ovrd_o,  // 1 ⇒ JTAG overriding this port (==
                                                           // !reset_enable).
  output logic [NUM_IC_RESET_PORTS-1:0]  ic_reset_ctrl_n_o  // Active-low reset value (==
                                                            // reset_control TDR field).
);
  logic unused_tap_ctrl;
  assign unused_tap_ctrl = tap_ctrl_i.tms;

  //--------------------------------------------------------------------------
  // Local Parameters
  //--------------------------------------------------------------------------
  localparam int unsigned RESET_ENABLE_CONTROL_WIDTH = 2 * NUM_IC_RESET_PORTS;

  //--------------------------------------------------------------------------
  // Internal Signals
  //--------------------------------------------------------------------------

  // Scan control signals
  jtag_scan_ctrl_t reset_hold_scan_ctrl, reset_enable_control_scan_ctrl;

  // Reset hold register signals
  logic             reset_hold_scan_out;
  logic             reset_hold;
  logic             reset_hold_n;

  // Reset enable/control register signals
  logic                                  reset_enable_control_scan_out;
  logic                                  rst_n_gate;
  logic [RESET_ENABLE_CONTROL_WIDTH-1:0] reset_enable_control_data;

  // Extracted control bits
  logic [NUM_IC_RESET_PORTS-1:0] reset_enable;
  logic [NUM_IC_RESET_PORTS-1:0] reset_control;

  //--------------------------------------------------------------------------
  // Scan Control for Reset Hold Register
  //--------------------------------------------------------------------------
  // Reset hold register uses TRST for reset (not scan_ctrl_i.rst_n)
  always_comb begin
    reset_hold_scan_ctrl = scan_ctrl_i;
    reset_hold_scan_ctrl.rst_n = tap_ctrl_i.trst_n;
  end

  //--------------------------------------------------------------------------
  // Scan Control for Reset Enable/Control Register
  //--------------------------------------------------------------------------
  // Hold=0 blocks TLR so the enable/control scan reg is not asynchronously
  // cleared. Primitive gates keep the async reset path a known cell.
  prim_inv u_reset_hold_inv (
    .in_i  (reset_hold),
    .out_o (reset_hold_n)
  );

  prim_or2 u_rst_n_or (
    .in0_i (scan_ctrl_i.rst_n),
    .in1_i (reset_hold_n),
    .out_o (rst_n_gate)
  );

  always_comb begin
    reset_enable_control_scan_ctrl       = scan_ctrl_i;
    reset_enable_control_scan_ctrl.rst_n = rst_n_gate;
  end

  //--------------------------------------------------------------------------
  // Reset Enable/Control Register (2*NUM_IC_RESET_PORTS bits)
  //--------------------------------------------------------------------------
  // This register uses scan_ctrl_i.rst_n but reset is blocked when reset_hold=0
  // This comes first in the scan chain (closest to TDI)
  prim_jtag_scan_reg #(
    .WIDTH(RESET_ENABLE_CONTROL_WIDTH),
    .RESET_VAL({RESET_ENABLE_CONTROL_WIDTH{1'b1}}),
    .jtag_scan_ctrl_t(jtag_scan_ctrl_t)
  ) u_reset_enable_control_scan_reg (
    .scan_ctrl_i   (reset_enable_control_scan_ctrl),
    .scan_in_i     (scan_in_i),  // TDI input
    .scan_out_o    (reset_enable_control_scan_out),
    .data_in_i     (reset_enable_control_data),
    .data_out_o    (reset_enable_control_data)
  );

  //--------------------------------------------------------------------------
  // Reset Hold Register (1 bit, closest to TDO)
  //--------------------------------------------------------------------------
  // This register is only reset by TRST, never by TLR
  // This comes last in the scan chain (closest to TDO)
  prim_jtag_scan_reg #(
    .WIDTH(1),
    .RESET_VAL(1'b1),
    .jtag_scan_ctrl_t(jtag_scan_ctrl_t)
  ) u_reset_hold_scan_reg (
    .scan_ctrl_i   (reset_hold_scan_ctrl),
    .scan_in_i     (reset_enable_control_scan_out),
    .scan_out_o    (reset_hold_scan_out),
    .data_in_i     (reset_hold),
    .data_out_o    (reset_hold)
  );

  //--------------------------------------------------------------------------
  // TDO Output
  //--------------------------------------------------------------------------
  // TDO comes from reset_hold register (closest to TDO)
  assign scan_out_o = reset_hold_scan_out;

  //--------------------------------------------------------------------------
  // Extract Control Bits from Registers
  //--------------------------------------------------------------------------
  for (genvar i = 0; i < NUM_IC_RESET_PORTS; i++) begin : gen_reset_control
    // Bit ordering in reset_enable_control_data:
    // - Bit [2*i]: reset_enable[i] (closer to TDO)
    // - Bit [2*i + 1]: reset_control[i] (further from TDO)
    localparam int unsigned RESET_ENABLE_BIT = 2 * i;
    localparam int unsigned RESET_CONTROL_BIT = 2 * i + 1;

    assign reset_enable[i]  = reset_enable_control_data[RESET_ENABLE_BIT];
    assign reset_control[i] = reset_enable_control_data[RESET_CONTROL_BIT];

    // Convert the IEEE §17 active-low `reset_enable` TDR field into
    // the natural active-high override signal expected by downstream
    // struct consumers: ic_reset_ovrd_o == 1 ⇔ JTAG is overriding.
    // See the module header for a full explanation of the polarity.
    assign ic_reset_ovrd_o[i]    = !reset_enable[i];
    // `reset_control` is already active-low (match consumer `_n` resets).
    assign ic_reset_ctrl_n_o[i]  = reset_control[i];
  end

endmodule : jtag_ic_reset_reg
