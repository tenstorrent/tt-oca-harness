// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Model a bidirectional GPIO pad between core2pad/pad2core wires and GPIO_PAD.
//
// The pad is driven while core2pad_en_i is high and floats otherwise; pad2core_o reads the
// pad while pad2core_en_i is high and is low otherwise. gpio_ctrl is unused and gpio_status
// is tied to zero, so no pull or drive-strength behaviour is modelled.

module gpio_model #(
  parameter type ctrl_t = logic,                            // Pad control struct type.
  parameter type status_t = logic                           // Pad status struct type.
) (
  input  wire             core2pad_i,                       // Core-to-pad data.
  input  wire             core2pad_en_i,                    // Core-to-pad output enable; the pad
                                                            // floats while low.

  output wire             pad2core_o,                       // Pad level while pad2core_en_i is
                                                            // high; low otherwise.
  input  wire             pad2core_en_i,                    // Pad-to-core input enable.

  inout  wire             GPIO_PAD,                         // Bidirectional pad pin.

  input  ctrl_t           gpio_ctrl,                        // Pad drive and pull control; unused.
  output status_t         gpio_status                       // Pad status, tied to zero.
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
