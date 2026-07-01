// Cross Trigger Network RTL file list

// Include paths
+incdir+${OCH_ROOT}/vendor/pulp-platform/axi/upstream/include
+incdir+${OCH_ROOT}/vendor/pulp-platform/common_cells/upstream/include
+incdir+${OCH_ROOT}/hw/common/och_prim/rtl
+incdir+${OCH_ROOT}/vendor/opentitan/upstream/hw/ip/prim/rtl
+incdir+${OCH_ROOT}/vendor/opentitan/upstream/hw/ip/prim_generic/rtl

// AXI package and infrastructure
${OCH_ROOT}/vendor/pulp-platform/axi/upstream/src/axi_pkg.sv
${OCH_ROOT}/vendor/pulp-platform/axi/upstream/src/axi_lite_demux.sv
${OCH_ROOT}/vendor/pulp-platform/axi/upstream/src/axi_lite_mux.sv
${OCH_ROOT}/vendor/pulp-platform/axi/upstream/src/axi_lite_to_axi.sv
${OCH_ROOT}/vendor/pulp-platform/axi/upstream/src/axi_err_slv.sv
${OCH_ROOT}/vendor/pulp-platform/axi/upstream/src/axi_lite_xbar.sv

// Common modules
${OCH_ROOT}/vendor/pulp-platform/common_cells/upstream/src/cf_math_pkg.sv
${OCH_ROOT}/vendor/pulp-platform/common_cells/upstream/src/lzc.sv
${OCH_ROOT}/vendor/pulp-platform/common_cells/upstream/src/rr_arb_tree.sv
${OCH_ROOT}/vendor/pulp-platform/common_cells/upstream/src/spill_register_flushable.sv
${OCH_ROOT}/vendor/pulp-platform/common_cells/upstream/src/spill_register.sv
${OCH_ROOT}/vendor/pulp-platform/common_cells/upstream/src/addr_decode_dync.sv
${OCH_ROOT}/vendor/pulp-platform/common_cells/upstream/src/addr_decode_napot.sv
${OCH_ROOT}/vendor/pulp-platform/common_cells/upstream/src/addr_decode.sv
${OCH_ROOT}/vendor/pulp-platform/common_cells/upstream/src/fifo_v3.sv
${OCH_ROOT}/vendor/pulp-platform/common_cells/upstream/src/fall_through_register.sv
${OCH_ROOT}/vendor/pulp-platform/common_cells/upstream/src/delta_counter.sv
${OCH_ROOT}/vendor/pulp-platform/common_cells/upstream/src/counter.sv

// Primitive modules (required for CTP)
${OCH_ROOT}/vendor/opentitan/upstream/hw/ip/prim/rtl/prim_assert.sv
${OCH_ROOT}/vendor/opentitan/upstream/hw/ip/prim/rtl/prim_cdc_rand_delay.sv
${OCH_ROOT}/vendor/opentitan/upstream/hw/ip/prim/rtl/prim_edge_detector.sv
${OCH_ROOT}/vendor/opentitan/upstream/hw/ip/prim_generic/rtl/prim_flop.sv
${OCH_ROOT}/vendor/opentitan/upstream/hw/ip/prim_generic/rtl/prim_flop_2sync.sv

// Cross Trigger Port IP
${OCH_ROOT}/hw/ip/cross_trigger_port/rtl/cross_trigger_port_pkg.sv
${OCH_ROOT}/hw/ip/cross_trigger_port/regs/gen/sv/cross_trigger_port_reg_pkg.sv
${OCH_ROOT}/hw/ip/cross_trigger_port/regs/gen/sv/cross_trigger_port_reg.sv
${OCH_ROOT}/hw/ip/cross_trigger_port/rtl/ctp_synchronizer.sv
${OCH_ROOT}/hw/ip/cross_trigger_port/rtl/ctp_pulse_stretcher.sv
${OCH_ROOT}/hw/ip/cross_trigger_port/rtl/ctp_edge_detector.sv
${OCH_ROOT}/hw/ip/cross_trigger_port/rtl/ctp_handshake_ctrl.sv
${OCH_ROOT}/hw/ip/cross_trigger_port/rtl/cross_trigger_port_core.sv
${OCH_ROOT}/hw/ip/cross_trigger_port/rtl/cross_trigger_port.sv

// Cross Trigger Matrix IP
${OCH_ROOT}/hw/ip/cross_trigger_matrix/rtl/cross_trigger_matrix_pkg.sv
${OCH_ROOT}/hw/ip/cross_trigger_matrix/rtl/ctm_src_selector.sv
${OCH_ROOT}/hw/ip/cross_trigger_matrix/rtl/cross_trigger_matrix.sv

// Cross Trigger Network
${OCH_ROOT}/hw/ip/cross_trigger_network/rtl/cross_trigger_network_pkg.sv
${OCH_ROOT}/hw/ip/cross_trigger_network/rtl/ctn_clock_stop_ctrl.sv
${OCH_ROOT}/hw/ip/cross_trigger_network/rtl/cross_trigger_network.sv
