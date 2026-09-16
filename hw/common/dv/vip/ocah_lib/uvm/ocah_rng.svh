// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Seeded random helpers shared by sequences and configuration objects:
// seed salting per label (so two helpers seeded from one scenario seed draw
// different streams), width masks, and the directed pattern set every
// data-path scan starts from. The random draws use the calling process's
// RNG, which the scenario body seeds first (ocah_sequence::seed_scenario_rng).
// The cocotb twin is ocah_lib.OcahRng with the same pattern set.

class ocah_rng;

  // Deterministic salt: the same label always perturbs the seed the same way.
  static function int unsigned salted_seed(int unsigned seed, string label);
    int unsigned salt = 0;
    foreach (label[i]) salt += (i + 1) * int'(label[i]);
    return seed ^ salt;
  endfunction

  static function bit [63:0] bit_mask(int unsigned width);
    return (width == 0) ? '0 : (width >= 64) ? '1 : ((64'h1 << width) - 1);
  endfunction

  // One random pattern of `width` bits from the caller's seeded process RNG.
  static function bit [63:0] random_pattern(int unsigned width);
    return {$urandom, $urandom} & bit_mask(width);
  endfunction

  // Edge, alternating, walking-one/zero, and `random_count` seeded random
  // patterns, deduplicated in insertion order.
  static function void directed_patterns(int unsigned width, int unsigned random_count,
                                         ref bit [63:0] patterns[$]);
    bit [63:0] mask = bit_mask(width);
    bit [63:0] fixed[$];
    int unsigned bit_positions[$];
    bit seen[bit [63:0]];
    patterns.delete();
    fixed.push_back('0);
    fixed.push_back(mask);
    fixed.push_back(64'hAAAA_AAAA_AAAA_AAAA & mask);
    fixed.push_back(64'h5555_5555_5555_5555 & mask);
    fixed.push_back(64'hA5A5_5A5A_C3C3_3C3C & mask);
    fixed.push_back(64'h0123_4567_89AB_CDEF & mask);
    bit_positions = {0, width / 4, width / 2, (3 * width) / 4, width - 1};
    bit_positions.sort();
    foreach (bit_positions[i]) begin
      if (i > 0 && bit_positions[i] == bit_positions[i-1]) continue;
      fixed.push_back(64'h1 << bit_positions[i]);
      fixed.push_back(mask ^ (64'h1 << bit_positions[i]));
    end
    for (int unsigned r = 0; r < random_count; r++) fixed.push_back(random_pattern(width));
    foreach (fixed[i]) begin
      if (!seen.exists(fixed[i])) begin
        seen[fixed[i]] = 1'b1;
        patterns.push_back(fixed[i]);
      end
    end
  endfunction

endclass : ocah_rng
