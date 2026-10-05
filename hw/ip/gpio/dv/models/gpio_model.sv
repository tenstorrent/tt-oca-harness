// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// General purpose IO model
//
//-----------------------------------------------------------------------------

module gpio_model #(
  parameter type ctrl_t = logic,
  parameter type status_t = logic
) (
  input  wire             core2pad_i,
  input  wire             core2pad_en_i,

  output wire             pad2core_o,
  input  wire             pad2core_en_i,

  inout  wire             gpio_pad_io,

  input  ctrl_t           gpio_ctrl_i,
  output status_t         gpio_status_o
);

  // Internal signals
  logic pad_drive;
  logic pad_value;

  // Drive logic: core to pad
  assign gpio_pad_io = core2pad_en_i ? core2pad_i : 1'bz;

  // Receive logic: pad to core
  assign pad2core_o = pad2core_en_i ? gpio_pad_io : 1'b0;

  assign gpio_status_o = status_t'('0); // the pad model has no status source

endmodule
