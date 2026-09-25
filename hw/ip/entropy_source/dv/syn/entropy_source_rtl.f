// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Entropy Source RTL File List for Logic Synthesis
//------------------------------------------------------------------------------
// This file lists all RTL files required for synthesizing the entropy_source
// component. Files are listed in dependency order.
//
// Usage with synthesis tools:
//   - Synopsys Design Compiler: read -f entropy_source_rtl.f
//   - Cadence Genus: read -f entropy_source_rtl.f
//   - Use relative paths from syn/ directory
//
// Prerequisites:
//   - Register files must be generated first: cd ../rtl && make build
//   - Register files are generated from SystemRDL in ../regs/
//
// Note: All paths are relative to the syn/ directory
//------------------------------------------------------------------------------
// Register package and register block (must come first)
// These are auto-generated from SystemRDL by `make -f ocah.mk ocah-regen-regs`.
../regs/gen/sv/entropy_source_reg_pkg.sv
../regs/gen/sv/entropy_source_reg.sv

// Component package
../rtl/entropy_source_pkg.sv

// Generic cells and primitives
// Note: Ring oscillators use asynchronous logic - requires special synthesis constraints
+incdir+../../../../../vendor/lowRISC/opentitan/upstream/hw/ip/prim/rtl
../../../../common/ocah_prim_generic/rtl/prim_clock_nand2.sv
../../../../common/ocah_prim_generic/rtl/prim_stdmux2.sv
../../../../../vendor/lowRISC/opentitan/upstream/hw/ip/prim_generic/rtl/prim_buf.sv
../../../../../vendor/lowRISC/opentitan/upstream/hw/ip/prim_generic/rtl/prim_clock_gating.sv
../../../../../vendor/lowRISC/opentitan/upstream/hw/ip/prim_generic/rtl/prim_flop.sv
../../../../../vendor/lowRISC/opentitan/upstream/hw/ip/prim_generic/rtl/prim_inv.sv

// Clock manipulation utilities
// Note: Ripple dividers use asynchronous ripple chains - requires special synthesis constraints
../rtl/entropy_ripple_divider.sv

// Entropy generation modules (in dependency order)
../rtl/entropy_ring_stage_wrappers.sv
../rtl/entropy_ring_oscillator.sv
../rtl/entropy_rosc_tune_fsm.sv
../rtl/entropy_noise_source.sv
../rtl/entropy_sampler_clocks.sv

// Cryptographic utilities
../rtl/gf_muladd.sv

// Entropy processing pipeline
../rtl/entropy_generator.sv
../rtl/entropy_generator_complex.sv
../rtl/entropy_decorrelator.sv
../rtl/entropy_fifo.sv

// Health test modules
../rtl/entropy_repetition_test.sv
../rtl/entropy_adaptive_proportion_test.sv
../rtl/entropy_markov_test.sv
../rtl/entropy_health_test.sv

// Debug and monitoring
../rtl/entropy_debug_monitor.sv

// Top-level module (must be last)
../rtl/entropy_source.sv

//------------------------------------------------------------------------------
// SYNTHESIS NOTES
//------------------------------------------------------------------------------      
// Clock Domains:
//   - clk_i: Main system clock (synchronous logic)
//   - Ring oscillators: Asynchronous free-running clocks (see SDC constraints)
//
// Special Handling Required:
//   1. Ring Oscillators (entropy_ring_oscillator.sv):
//      - Contains asynchronous feedback loops (NAND/inverter chains)
//      - Must not be optimized by synthesis tool
//      - Use set_dont_touch on ring oscillator cells
//      - Use set_false_path for timing analysis
//      - See entropy_source.sdc for detailed constraints
//
//   2. Ripple Dividers (entropy_ripple_divider.sv):
//      - Contains asynchronous ripple chains (toggle flip-flop cascade)
//      - Combinational feedback loops (D→QB for toggle)
//      - Must not be optimized by synthesis tool
//      - Use set_dont_touch on ripple divider instances
//      - Use set_false_path for ripple chain and feedback paths
//      - Total: 13 instances (1 debug + 12 generators)
//      - See the RIPPLE DIVIDER CONSTRAINTS section of entropy_source.sdc
//
//   3. Metastability:
//      - Sampler flip-flops operate in the metastable region (the entropy mechanism)
//      - See entropy_sampler_clocks.sv for dual-rank synchronizers
//
//   4. Security-Critical Paths:
//      - Entropy generation and health test modules
//      - Sample clock dividers affect entropy quality
//      - Avoid optimization that may reduce entropy quality
//      - Consider using set_dont_touch selectively
//
// Timing Constraints:
//   - See entropy_source.sdc for complete timing constraints
//   - False paths defined for ring oscillator crossings
//   - False paths defined for ripple divider chains and feedback
//   - Multi-cycle paths for health test statistics
//------------------------------------------------------------------------------            
