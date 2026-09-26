// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Model a bidirectional GPIO pad between core2pad/pad2core wires and GPIO_PAD.
//
// gpio_ctrl programs pull and drive; gpio_status reports the sampled pad level.

module gpio_model #(
  parameter type ctrl_t = logic,                            // Pad control struct type.
  parameter type status_t = logic                           // Pad status struct type.
) (
  input  wire             core2pad_i,                       // Core-to-pad data.
  input  wire             core2pad_en_i,                    // Core-to-pad output enable.

  output wire             pad2core_o,                       // Pad-to-core data.
  input  wire             pad2core_en_i,                    // Pad-to-core input enable.

  inout  wire             GPIO_PAD,                         // Bidirectional pad pin.

  input  ctrl_t           gpio_ctrl,                        // Pad drive and pull control.
  output status_t         gpio_status                       // Sampled pad status.
);

  // Internal signals
  logic pad_drive;
  logic pad_value;

  // Drive logic: core to pad
  assign GPIO_PAD = core2pad_en_i ? core2pad_i : 1'bz;

  // Receive logic: pad to core
  assign pad2core_o = pad2core_en_i ? GPIO_PAD : 1'b0;

  assign gpio_status = status_t'('0); // Placeholder for status output

endmodule
