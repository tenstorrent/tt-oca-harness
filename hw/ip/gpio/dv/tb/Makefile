# This file is public domain, it can be freely copied without restrictions.
# SPDX-License-Identifier: CC0-1.0

# Makefile
SIM ?= verilator
TOPLEVEL_LANG ?= verilog

COCOTB_HDL_TIMEUNIT = 1ns
COCOTB_HDL_TIMEPRECISION = 1ps

# COCOTB_TOPLEVEL is the name of the toplevel module in your Verilog or VHDL file
TOPLEVEL = tb_gpio

# COCOTB_TEST_MODULES is the basename of the Python test file(s)
MODULE = test_gpio

# Enable VCD dumping
EXTRA_ARGS += --trace --trace-structs
EXTRA_ARGS += --Wno-REDEFMACRO --Wno-WIDTHEXPAND --Wno-MULTIDRIVEN --Wno-IMPLICIT --Wno-WIDTHTRUNC --Wno-SYMRSVDWORD # TODO: Suppress certain warnings only

# Extract include directories from the filelist
FLIST_INCDIRS := $(shell if [ -f gpio.f ]; then grep '^+incdir+' gpio.f | sed 's/^+incdir+/-I/g'; fi)
EXTRA_ARGS += $(FLIST_INCDIRS)

# Manual source files - only Verilator-compatible files in correct order
# Packages first
VERILOG_SOURCES += ../../../../vendor/pulp-platform/axi/upstream/src/axi_pkg.sv
VERILOG_SOURCES += ../../../../vendor/pulp-platform/apb/upstream/apb_pkg.sv
VERILOG_SOURCES += ../../../../vendor/pulp-platform/common_cells/upstream/src/cf_math_pkg.sv
VERILOG_SOURCES += ../../../../vendor/pulp-platform/common_cells/upstream/src/addr_decode_dync.sv
VERILOG_SOURCES += ../../../../vendor/pulp-platform/common_cells/upstream/src/addr_decode.sv
VERILOG_SOURCES += ../../../../vendor/pulp-platform/common_cells/upstream/src/rr_arb_tree.sv
VERILOG_SOURCES += ../../../../vendor/pulp-platform/common_cells/upstream/src/fall_through_register.sv
VERILOG_SOURCES += ../../../../vendor/pulp-platform/common_cells/upstream/src/fifo_v3.sv
VERILOG_SOURCES += ../../../../vendor/pulp-platform/common_cells/upstream/src/delta_counter.sv
VERILOG_SOURCES += ../../../../vendor/pulp-platform/common_cells/upstream/src/spill_register_flushable.sv
VERILOG_SOURCES += ../../../../vendor/pulp-platform/common_cells/upstream/src/spill_register.sv
VERILOG_SOURCES += ../../../../vendor/pulp-platform/common_cells/upstream/src/counter.sv
VERILOG_SOURCES += ../../../../vendor/pulp-platform/axi/upstream/src/axi_lite_to_axi.sv
VERILOG_SOURCES += ../../../../vendor/pulp-platform/axi/upstream/src/axi_err_slv.sv
VERILOG_SOURCES += ../../../../vendor/pulp-platform/axi/upstream/src/axi_lite_to_apb.sv
VERILOG_SOURCES += ../../../../vendor/pulp-platform/axi/upstream/src/axi_lite_demux.sv
VERILOG_SOURCES += ../../../../vendor/pulp-platform/apb/upstream/apb_demux.sv
# Prim primitives
VERILOG_SOURCES += ../../../../hw/common/och_prim/rtl/prim_assert.sv
VERILOG_SOURCES += ../../../../hw/common/och_prim_generic/rtl/prim_sync_randomized_delay.sv
VERILOG_SOURCES += ../../../../hw/common/och_prim_generic/rtl/prim_flop_3sync_r.sv
VERILOG_SOURCES += ../../../../hw/common/och_prim/rtl/prim_sync3r.sv
VERILOG_SOURCES += ../../../../hw/common/och_prim/rtl/prim_axil_err_slv.sv
VERILOG_SOURCES += ../../../../hw/common/och_prim_generic/rtl/prim_latch_n.sv
# GPIO modules
VERILOG_SOURCES += ../rtl/gpio_shim_pkg.sv
VERILOG_SOURCES += ../rtl/gpio_pkg.sv
VERILOG_SOURCES += ../data/registers/rtl/gpio_intf_reg_pkg.sv
VERILOG_SOURCES += ../data/registers/rtl/gpio_ctrl_reg_pkg.sv
VERILOG_SOURCES += ../data/registers/rtl/gpio_intf_reg.sv
VERILOG_SOURCES += ../data/registers/rtl/gpio_ctrl_reg.sv
VERILOG_SOURCES += ../rtl/gpio_filter.sv
VERILOG_SOURCES += ../rtl/gpio_shim.sv
VERILOG_SOURCES += ../models/gpio_model.sv
VERILOG_SOURCES += ../rtl/gpio.sv
VERILOG_SOURCES += $(PWD)/tb_gpio.sv

STRESS ?= 0

ifeq ($(STRESS), 1)
    PLUSARGS += +stress
endif

# include cocotb's make rules to take care of the simulator setup
include $(shell cocotb-config --makefiles)/Makefile.sim

# Generate filelist if it doesn't exist
gpio.f:
	bender script flist-plus -t common_cells_rtl -t apb_rtl -t axi_rtl -t peripheral -t gpio > gpio.f

.PHONY: filelist lint wave
clean:: # cocotb's own `clean` uses double colon
	rm -rf __pycache__ *.f

filelist: gpio.f

lint:
	svlint -v ../rtl/gpio.sv

wave:
	surfer -s gpio.surfer dump.vcd
