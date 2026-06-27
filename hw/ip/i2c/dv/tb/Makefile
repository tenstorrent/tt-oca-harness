# This file is public domain, it can be freely copied without restrictions.
# SPDX-License-Identifier: CC0-1.0

# Makefile
SIM ?= verilator
TOPLEVEL_LANG ?= verilog

COCOTB_HDL_TIMEUNIT = 1ns
COCOTB_HDL_TIMEPRECISION = 1ps

VERILOG_SOURCES += $(PWD)/tb_i2c.sv

# COCOTB_TOPLEVEL is the name of the toplevel module in your Verilog or VHDL file
TOPLEVEL = tb_i2c

# COCOTB_TEST_MODULES is the basename of the Python test file(s)
MODULE = test_i2c

# Enable VCD dumping
EXTRA_ARGS += --trace --trace-structs
EXTRA_ARGS += --Wno-REDEFMACRO --Wno-WIDTHEXPAND --Wno-MULTIDRIVEN # TODO: Suppress certain warnings only
EXTRA_ARGS += $(OCH_ROOT)/hw/comp/i2c/tb_cocotb/i2c.f

STRESS ?= 0

ifeq ($(STRESS), 1)
    PLUSARGS += +stress
endif

# include cocotb's make rules to take care of the simulator setup
include $(shell cocotb-config --makefiles)/Makefile.sim

clean:: # cocotb's own `clean` uses double colon
	rm -rf __pycache__

filelist:
	bender script flist-plus -t common_cells_rtl -t apb_rtl -t axi_rtl -t component > i2c.f

lint:
	svlint -v ../rtl/i2c.sv

wave:
	surfer -s i2c.surfer dump.vcd
