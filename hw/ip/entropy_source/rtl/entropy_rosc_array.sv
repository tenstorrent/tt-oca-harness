// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Ring oscillators of entropy_source: NRings noise rings and the shared sample-clock ring.
//
// sep_trng instantiates this module beside entropy_source, which drives its enables and
// detunes and samples its asynchronous outputs. It holds nothing but the rings, so a build
// may replace it under the same name: with a ring-oscillator hard macro, or with the
// loop-free stub/entropy_rosc_array.sv.
//
// Noise ring i runs on its tapped length while noise_detune_i[i] is low and on its full
// length while high. The shared ring is about 10x longer than the noise rings.

module entropy_rosc_array
  import entropy_source_pkg::NRings;
(
  input  logic [NRings-1:0] noise_enable_i,  // Bit i lets noise ring i oscillate.
  input  logic [NRings-1:0] noise_detune_i,  // Bit i selects noise ring i's full length.
  input  logic              shared_enable_i,  // Lets the shared ring oscillate.
  input  logic              shared_detune_i,  // Selects the shared ring's full length.
  output logic [NRings-1:0] noise_o,  // Noise ring outputs, asynchronous.
  output logic              shared_clk_o  // Shared ring output, asynchronous.
);

  /////////////////////
  // Local parameters
  /////////////////////

  // Full ring lengths, selected while a lane's detune is high.
  localparam int unsigned TotalLength0 = 5, TotalLength1 = 7;
  localparam int unsigned TotalLength2 = 11, TotalLength3 = 13;
  localparam int unsigned TotalLength4 = 17, TotalLength5 = 19;
  localparam int unsigned TotalLength6 = 6, TotalLength7 = 8;
  localparam int unsigned TotalLength8 = 12, TotalLength9 = 15;
  localparam int unsigned TotalLength10 = 18, TotalLength11 = 23;

  // Shorter tapped lengths (higher frequency), selected while a lane's detune is low.
  localparam int unsigned TappedLength0 = 3, TappedLength1 = 5;
  localparam int unsigned TappedLength2 = 9, TappedLength3 = 10;
  localparam int unsigned TappedLength4 = 14, TappedLength5 = 16;
  localparam int unsigned TappedLength6 = 4, TappedLength7 = 7;
  localparam int unsigned TappedLength8 = 11, TappedLength9 = 13;
  localparam int unsigned TappedLength10 = 15, TappedLength11 = 21;

  // Shared ring: the detuned length keeps the frequency ratio to the noise rings.
  localparam int unsigned SharedTotalLength = 109;
  localparam int unsigned SharedTappedLength = 53;

  //////////
  // Types
  //////////

  // Lookup functions used to parameterise the generate loop below
  function automatic int get_total_length(input int idx);
    unique case (idx)
      0:       return TotalLength0;
      1:       return TotalLength1;
      2:       return TotalLength2;
      3:       return TotalLength3;
      4:       return TotalLength4;
      5:       return TotalLength5;
      6:       return TotalLength6;
      7:       return TotalLength7;
      8:       return TotalLength8;
      9:       return TotalLength9;
      10:      return TotalLength10;
      11:      return TotalLength11;
      default: return 29;
    endcase
  endfunction

  function automatic int get_tapped_length(input int idx);
    unique case (idx)
      0:       return TappedLength0;
      1:       return TappedLength1;
      2:       return TappedLength2;
      3:       return TappedLength3;
      4:       return TappedLength4;
      5:       return TappedLength5;
      6:       return TappedLength6;
      7:       return TappedLength7;
      8:       return TappedLength8;
      9:       return TappedLength9;
      10:      return TappedLength10;
      11:      return TappedLength11;
      default: return 19;
    endcase
  endfunction

  /////////////////
  // Sub-instances
  /////////////////

  for (genvar i = 0; i < NRings; i++) begin : gen_noise_ro
    entropy_ring_oscillator #(
      .TOTAL_LENGTH  (get_total_length (i)),
      .TAPPED_LENGTH (get_tapped_length(i))
    ) u_ring_oscillator (
      .enable_i (noise_enable_i[i]),
      .detune_i (noise_detune_i[i]),
      .noise_o  (noise_o[i])
    );
  end : gen_noise_ro

  entropy_ring_oscillator #(
    .TOTAL_LENGTH  (SharedTotalLength),
    .TAPPED_LENGTH (SharedTappedLength)
  ) u_shared_ro (
    .enable_i (shared_enable_i),
    .detune_i (shared_detune_i),
    .noise_o  (shared_clk_o)
  );

endmodule
