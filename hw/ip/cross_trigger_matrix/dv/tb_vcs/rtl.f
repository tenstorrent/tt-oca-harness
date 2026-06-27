// RTL File List for Cross Trigger Matrix
// Use $OCH_ROOT environment variable for portability

// AXI package (must come first, before typedef macros)
$OCH_ROOT/vendor/pulp-platform/axi/upstream/src/axi_pkg.sv

// Register package and RTL (must come first)
$OCH_ROOT/hw/ip/cross_trigger_matrix/data/registers/rtl/cross_trigger_matrix_reg_pkg.sv
$OCH_ROOT/hw/ip/cross_trigger_matrix/data/registers/rtl/cross_trigger_matrix_reg.sv

// Package
$OCH_ROOT/hw/ip/cross_trigger_matrix/rtl/cross_trigger_matrix_pkg.sv

// RTL modules (in dependency order)
$OCH_ROOT/hw/ip/cross_trigger_matrix/rtl/ctm_src_selector.sv

// Top-level module (last)
$OCH_ROOT/hw/ip/cross_trigger_matrix/rtl/cross_trigger_matrix.sv
