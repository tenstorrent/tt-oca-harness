// RTL File List for Cross Trigger Port
// Use $OCH_ROOT environment variable for portability

// AXI package (must come first, before typedef macros)
$OCH_ROOT/vendor/pulp-platform/axi/upstream/src/axi_pkg.sv

// Register package and RTL (must come first)
$OCH_ROOT/hw/ip/cross_trigger_port/data/registers/rtl/cross_trigger_port_reg_pkg.sv
$OCH_ROOT/hw/ip/cross_trigger_port/data/registers/rtl/cross_trigger_port_reg.sv

// Package
$OCH_ROOT/hw/ip/cross_trigger_port/rtl/cross_trigger_port_pkg.sv

// Common primitives (prim_pkg must come first)
$OCH_ROOT/vendor/opentitan/upstream/hw/ip/prim_generic/rtl/prim_pkg.sv
$OCH_ROOT/vendor/opentitan/upstream/hw/ip/prim_generic/rtl/prim_flop.sv
$OCH_ROOT/vendor/opentitan/upstream/hw/ip/prim_generic/rtl/prim_flop_2sync.sv
$OCH_ROOT/vendor/opentitan/upstream/hw/ip/prim/rtl/prim_edge_detector.sv

// Generic primitive implementations
$OCH_ROOT/vendor/opentitan/upstream/hw/ip/prim_generic/rtl/prim_flop.sv
$OCH_ROOT/vendor/opentitan/upstream/hw/ip/prim_generic/rtl/prim_flop_2sync.sv

// RTL modules (in dependency order)
$OCH_ROOT/hw/ip/cross_trigger_port/rtl/ctp_synchronizer.sv
$OCH_ROOT/hw/ip/cross_trigger_port/rtl/ctp_pulse_stretcher.sv
$OCH_ROOT/hw/ip/cross_trigger_port/rtl/ctp_edge_detector.sv
$OCH_ROOT/hw/ip/cross_trigger_port/rtl/ctp_handshake_ctrl.sv

// Core module (without CSRs)
$OCH_ROOT/hw/ip/cross_trigger_port/rtl/cross_trigger_port_core.sv

// Top-level module (last)
$OCH_ROOT/hw/ip/cross_trigger_port/rtl/cross_trigger_port.sv
