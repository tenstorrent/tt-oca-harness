# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// RTL File List for Entropy Source
// Use $OCH_ROOT environment variable for portability

// ============================================================================
// Entropy source RTL
// ============================================================================

// Register package and RTL (must come first)
$OCH_ROOT/hw/ip/entropy_source/regs/gen/sv/entropy_source_reg_pkg.sv
$OCH_ROOT/hw/ip/entropy_source/regs/gen/sv/entropy_source_reg.sv

// Package
$OCH_ROOT/hw/ip/entropy_source/rtl/entropy_source_pkg.sv

// Generic cells (primitives)
$OCH_ROOT/hw/common/och_prim_generic/rtl/prim_clock_nand2.sv
$OCH_ROOT/hw/common/och_prim_generic/rtl/prim_dffrxq.sv
$OCH_ROOT/hw/common/och_prim_generic/rtl/prim_inv.sv
$OCH_ROOT/hw/common/och_prim_generic/rtl/prim_stdbuf.sv
$OCH_ROOT/hw/common/och_prim_generic/rtl/prim_stdmux2.sv

// RTL modules (in dependency order)
$OCH_ROOT/hw/ip/entropy_source/rtl/entropy_ring_stage_wrappers.sv
$OCH_ROOT/hw/ip/entropy_source/rtl/entropy_ring_oscillator.sv
$OCH_ROOT/hw/ip/entropy_source/rtl/entropy_rosc_tune_fsm.sv
$OCH_ROOT/hw/ip/entropy_source/rtl/entropy_noise_source.sv
$OCH_ROOT/hw/ip/entropy_source/rtl/entropy_sampler_clocks.sv
$OCH_ROOT/hw/ip/entropy_source/rtl/gf_muladd.sv
$OCH_ROOT/hw/ip/entropy_source/rtl/entropy_generator.sv
$OCH_ROOT/hw/ip/entropy_source/rtl/entropy_generator_complex.sv
$OCH_ROOT/hw/ip/entropy_source/rtl/entropy_decorrelator.sv
$OCH_ROOT/hw/ip/entropy_source/rtl/entropy_fifo.sv
$OCH_ROOT/hw/ip/entropy_source/rtl/entropy_repetition_test.sv
$OCH_ROOT/hw/ip/entropy_source/rtl/entropy_adaptive_proportion_test.sv
$OCH_ROOT/hw/ip/entropy_source/rtl/entropy_markov_test.sv
$OCH_ROOT/hw/ip/entropy_source/rtl/entropy_health_test.sv
$OCH_ROOT/hw/ip/entropy_source/rtl/entropy_debug_monitor.sv

// Top-level module (last)
$OCH_ROOT/hw/ip/entropy_source/rtl/entropy_source.sv
