# This file is public domain, it can be freely copied without restrictions.
# SPDX-License-Identifier: CC0-1.0

# Makefile for System Timer OCTS Testbench
#
# Usage:
#   make                    # Run with default simulator (Verilator)
#   make SIM=verilator      # Run with Verilator
#   make SIM=vcs            # Run with VCS (generates FSDB waves by default)
#   make SIM=vcs WAVES=1    # Run with VCS and generate VPD waveforms instead
#   make SIM=vcs NOWAVES=1  # Run with VCS without waveforms
#   make clean              # Clean build artifacts
SIM ?= verilator
TOPLEVEL_LANG ?= verilog

# VCS-specific settings
ifeq ($(SIM),vcs)
    COMPILE_ARGS += -sverilog
    COMPILE_ARGS += -ntb_opts uvm-1.2
    COMPILE_ARGS += -timescale=1ns/1ps
    COMPILE_ARGS += -debug_access+all
    COMPILE_ARGS += -kdb
    COMPILE_ARGS += +vcs+lic+wait
    COMPILE_ARGS += -full64
    COMPILE_ARGS += -LDFLAGS -Wl,--no-as-needed

    # VCS runtime arguments
    PLUSARGS += +vcs+lic+wait
    PLUSARGS += +ntb_random_seed_automatic

    # Generate FSDB waves by default for VCS
    # Override with WAVES=1 for VPD format, or NOWAVES=1 to disable
    ifeq ($(WAVES),1)
        # VPD waveform format
        COMPILE_ARGS += -debug_access+all
        PLUSARGS += +vpdfile+waves.vpd
    else ifeq ($(NOWAVES),1)
        # No waveforms
    else
        # Default: FSDB waveform format
        COMPILE_ARGS += -debug_access+all
        PLUSARGS += +waves
    endif
endif

COCOTB_HDL_TIMEUNIT = 1ns
COCOTB_HDL_TIMEPRECISION = 1ps

# Get the repository root directory - try git first, fall back to OCH_ROOT, fail if neither available
_OCH_ROOT_GIT := $(shell git rev-parse --show-toplevel 2>/dev/null)
ifneq ($(_OCH_ROOT_GIT),)
  OCH_ROOT := $(_OCH_ROOT_GIT)
else ifndef OCH_ROOT
  $(error Not in a git repository and OCH_ROOT is not set)
endif

# APB4/AXI4-Lite package
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/apb/upstream/apb_pkg.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/axi/upstream/src/axi_pkg.sv

# Prim modules
VERILOG_SOURCES += $(OCH_ROOT)/vendor/opentitan/upstream/hw/ip/prim/rtl/prim_edge_detector.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/opentitan/upstream/hw/ip/prim_generic/rtl/prim_flop.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/opentitan/upstream/hw/ip/prim_generic/rtl/prim_flop_2sync.sv

# Timer register packages and modules
VERILOG_SOURCES += $(OCH_ROOT)/hw/ip/system_timer_octs/data/registers/rtl/system_timer_octs_reg_pkg.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/ip/system_timer_octs/data/registers/rtl/system_timer_octs_reg.sv


# Timer core modules
VERILOG_SOURCES += $(OCH_ROOT)/hw/ip/system_timer_octs/rtl/system_timer_octs_pkg.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/ip/system_timer_octs/rtl/system_timer_octs_core.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/ip/system_timer_octs/rtl/system_timer_octs.sv

# Testbench
VERILOG_SOURCES += $(OCH_ROOT)/hw/ip/system_timer_octs/tb/tb_system_timer_octs.sv

# COCOTB_TOPLEVEL is the name of the toplevel module in your Verilog or VHDL file
TOPLEVEL = tb_system_timer_octs

# COCOTB_TEST_MODULES is the basename of the Python test file(s)
MODULE = tb_system_timer_octs

# Simulator-specific arguments
ifeq ($(SIM),verilator)
    # Verilator-specific arguments
    EXTRA_ARGS += --trace --trace-structs
    EXTRA_ARGS += --Wno-REDEFMACRO --Wno-WIDTHEXPAND --Wno-MULTIDRIVEN --Wno-PINMISSING --Wno-LATCH --Wno-UNOPTFLAT
    EXTRA_ARGS += --timing
    # Verilator include paths
    EXTRA_ARGS += -I$(OCH_ROOT)/hw/ip/system_timer_octs/tb/
    EXTRA_ARGS += -I$(OCH_ROOT)/hw/ip/system_timer_octs/data/registers/rtl/
    EXTRA_ARGS += -I$(OCH_ROOT)/hw/ip/system_timer_octs/rtl/
    EXTRA_ARGS += -I$(OCH_ROOT)/hw/common/
    EXTRA_ARGS += -I$(OCH_ROOT)/hw/common/och_prim/rtl/
    EXTRA_ARGS += -I$(OCH_ROOT)/vendor/pulp-platform/apb/upstream/include/
    EXTRA_ARGS += -I$(OCH_ROOT)/vendor/pulp-platform/axi/upstream/include/
endif

# VCS-specific include paths (using +incdir+ syntax)
ifeq ($(SIM),vcs)
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/ip/system_timer_octs/tb/
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/ip/system_timer_octs/data/registers/rtl/
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/ip/system_timer_octs/rtl/
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/common/
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/common/och_prim/rtl/
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/vendor/pulp-platform/apb/upstream/include/
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/vendor/pulp-platform/axi/upstream/include/
endif

# include cocotb's make rules to take care of the simulator setup
include $(shell cocotb-config --makefiles)/Makefile.sim

clean:: # cocotb's own `clean` uses double colon
	rm -rf __pycache__
	rm -rf simv simv.daidir csrc ucli.key vc_hdrs.h
	rm -rf *.vpd *.vcd *.fsdb
	rm -rf DVEfiles inter.vpd .vlogansetup.env .vlogansetup.args
	rm -rf work.lib++ .synopsys_vss.setup