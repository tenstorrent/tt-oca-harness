// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Open-drain (wired-OR) bus model for pad-level testbenches.
//
// The wire rests at pull_i while no driver is enabled. An enabled driver
// whose data differs from pull_i pulls the wire to that level, and any
// number of drivers may pull at once. An open-drain driver cannot move the
// wire towards its pull, so an enabled driver whose data equals pull_i
// leaves the wire alone and is reported on mismatch_o.

module ocah_open_drain_bus #(
  parameter int unsigned NumDrivers = 2
) (
  input  logic                  pull_i,
  input  logic [NumDrivers-1:0] dout_i,
  input  logic [NumDrivers-1:0] dout_en_i,
  output logic                  wire_o,
  output logic                  mismatch_o
);

  logic [NumDrivers-1:0] pulling;
  logic [NumDrivers-1:0] mismatching;

  assign pulling     = dout_en_i & (dout_i ^ {NumDrivers{pull_i}});
  assign mismatching = dout_en_i & ~(dout_i ^ {NumDrivers{pull_i}});
  assign wire_o      = pull_i ^ (|pulling);
  assign mismatch_o  = |mismatching;

endmodule : ocah_open_drain_bus
