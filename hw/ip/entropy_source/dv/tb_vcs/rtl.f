// RTL File List for Entropy Source
// Use $OCH_ROOT environment variable for portability

// ============================================================================
// REAL RTL MODE - Full entropy source implementation
// ============================================================================

// Register package and RTL (must come first)
//$OCH_ROOT/hw/comp/entropy_source/data/registers/rtl/entropy_source_reg_pkg.sv
//$OCH_ROOT/hw/comp/entropy_source/data/registers/rtl/entropy_source_reg.sv
$OCH_ROOT/hw/comp/entropy_source/rtl/entropy_source_reg_pkg.sv
$OCH_ROOT/hw/comp/entropy_source/rtl/entropy_source_reg.sv

// Package
$OCH_ROOT/hw/comp/entropy_source/rtl/entropy_source_pkg.sv

// Generic cells (primitives)
$OCH_ROOT/hw/comp/entropy_source/rtl/gcells.sv

// RTL modules (in dependency order)
$OCH_ROOT/hw/comp/entropy_source/rtl/entropy_ring_oscillator.sv
$OCH_ROOT/hw/comp/entropy_source/rtl/entropy_rosc_tune_fsm.sv
$OCH_ROOT/hw/comp/entropy_source/rtl/entropy_noise_source.sv
$OCH_ROOT/hw/comp/entropy_source/rtl/entropy_sampler_clocks.sv
$OCH_ROOT/hw/comp/entropy_source/rtl/gf_muladd.sv
$OCH_ROOT/hw/comp/entropy_source/rtl/entropy_generator.sv
$OCH_ROOT/hw/comp/entropy_source/rtl/entropy_generator_complex.sv
$OCH_ROOT/hw/comp/entropy_source/rtl/entropy_decorrelator.sv
$OCH_ROOT/hw/comp/entropy_source/rtl/entropy_fifo.sv
$OCH_ROOT/hw/comp/entropy_source/rtl/entropy_repetition_test.sv
$OCH_ROOT/hw/comp/entropy_source/rtl/entropy_adaptive_proportion_test.sv
$OCH_ROOT/hw/comp/entropy_source/rtl/entropy_markov_test.sv
$OCH_ROOT/hw/comp/entropy_source/rtl/entropy_health_test.sv
$OCH_ROOT/hw/comp/entropy_source/rtl/entropy_debug_monitor.sv

// Top-level module (last)
$OCH_ROOT/hw/comp/entropy_source/rtl/entropy_source.sv

// ============================================================================
// BLACK BOX MODE (disabled - for reference only)
// Simple APB slave with 4KB memory for initial APB protocol testing
// ============================================================================
// $OCH_ROOT/hw/comp/entropy_source/tb_vcs/entropy_top_bb.sv
