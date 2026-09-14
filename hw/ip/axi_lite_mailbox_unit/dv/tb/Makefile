# This file is public domain, it can be freely copied without restrictions.
# SPDX-License-Identifier: CC0-1.0

# Makefile
SIM ?= verilator
TOPLEVEL_LANG ?= verilog

COCOTB_HDL_TIMEUNIT = 1ns
COCOTB_HDL_TIMEPRECISION = 1ps

VERILOG_SOURCES += $(PWD)/tb_axil_mailbox.sv

# COCOTB_TOPLEVEL is the name of the toplevel module in your Verilog or VHDL file
TOPLEVEL = tb_axil_mailbox

# COCOTB_TEST_MODULES is the basename of the Python test file(s)
MODULE = test_axil_mailbox

# No --trace: Verilator segfaults when tracing this design.
EXTRA_ARGS += -Wno-REDEFMACRO -Wno-WIDTHEXPAND -Wno-MULTIDRIVEN -Wno-fatal
EXTRA_ARGS += -f $(PWD)/axil_mailbox.f

STRESS ?= 0

ifeq ($(STRESS), 1)
    PLUSARGS += +stress
endif

# include cocotb's make rules to take care of the simulator setup
include $(shell cocotb-config --makefiles)/Makefile.sim

clean:: # cocotb's own `clean` uses double colon
	rm -rf __pycache__ *.f

# Files to exclude from the filelist (Verilator incompatible)
EXCLUDE_FILES := pad_functional.sv hw/sep/ el2_param.vh el2_pkg

# Generate the filelist without problematic files
filelist:
	bender script flist-plus -t common_cells_rtl -t apb_rtl -t axi_rtl -t axil_mailbox -t rtl | \
	$(foreach exclude,$(EXCLUDE_FILES),grep -v "$(exclude)" |) \
	cat > $(PWD)/axil_mailbox.f

lint:
	svlint -v ../rtl/axi_lite_mailbox_unit.sv

wave:
	surfer -s axil_mailbox.surfer dump.vcd
