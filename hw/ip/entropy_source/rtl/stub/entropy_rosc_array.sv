// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Loop-free stand-in for entropy_rosc_array, for a build that does not use the ring
// oscillators.
//
// It keeps the ports of entropy_rosc_array and drives every output from its own controls,
// so synthesis keeps the samplers, dividers and health tests behind it. The outputs are
// deterministic: the health tests fail on them, so this module must not be the only entropy
// source of a chip.

module entropy_rosc_array
  import entropy_source_pkg::NRings;
(
  input  logic [NRings-1:0] noise_enable_i,  // Bit i lets noise ring i oscillate.
  input  logic [NRings-1:0] noise_detune_i,  // Bit i selects noise ring i's full length.
  input  logic              shared_enable_i,  // Lets the shared ring oscillate.
  input  logic              shared_detune_i,  // Selects the shared ring's full length.
  output logic [NRings-1:0] noise_o,  // noise_enable_i ^ noise_detune_i.
  output logic              shared_clk_o  // shared_enable_i ^ shared_detune_i.
);

  assign noise_o      = noise_enable_i ^ noise_detune_i;
  assign shared_clk_o = shared_enable_i ^ shared_detune_i;

endmodule
