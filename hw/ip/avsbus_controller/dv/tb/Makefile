# This file is public domain, it can be freely copied without restrictions.
# SPDX-License-Identifier: CC0-1.0

# Makefile for AVSBus Testbench
#
# Usage:
#   make                    # Run with default simulator (Verilator)
#   make SIM=verilator      # Run with Verilator
#   make SIM=vcs            # Run with Synopsys VCS (FSDB enabled by default)
#   make SIM=vcs WAVES=1    # Run with VCS and generate VPD waveforms
#   make SIM=vcs FSDB=0     # Run with VCS and disable FSDB waveforms
#   make clean              # Clean build artifacts
SIM ?= verilator
TOPLEVEL_LANG ?= verilog

# VCS-specific settings
ifeq ($(SIM),vcs)
    # Set FSDB=1 by default for VCS (can be overridden by user)
    FSDB ?= 1

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

    # Enable waveform dumping for VCS
    ifeq ($(WAVES),1)
        COMPILE_ARGS += -debug_access+all
        PLUSARGS += +vpdfile+waves.vpd
    endif

    # Enable FSDB waveform dumping for VCS
    ifeq ($(FSDB),1)
        COMPILE_ARGS += -debug_access+all
        PLUSARGS += +waves
    endif
endif

COCOTB_HDL_TIMEUNIT = 1ns
COCOTB_HDL_TIMEPRECISION = 1ps

# Get the git root directory
# Try git first, fall back to OCH_ROOT, fail if neither available
_OCH_ROOT_GIT := $(shell git rev-parse --show-toplevel 2>/dev/null)
ifneq ($(_OCH_ROOT_GIT),)
  OCH_ROOT := $(_OCH_ROOT_GIT)
else ifndef OCH_ROOT
  $(error Not in a git repository and OCH_ROOT is not set)
endif

# APB4/AXI4-Lite package
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/apb/upstream/apb_pkg.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/axi/upstream/src/axi_pkg.sv

# Assertion macros
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim/rtl/prim_assert.sv

# Common cells dependencies for axi_lite_to_apb
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/common_cells/upstream/src/cf_math_pkg.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/common_cells/upstream/src/rr_arb_tree.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/common_cells/upstream/src/lzc.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/common_cells/upstream/src/addr_decode_dync.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/common_cells/upstream/src/addr_decode.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/common_cells/upstream/src/fifo_v3.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/common_cells/upstream/src/spill_register.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/common_cells/upstream/src/fall_through_register.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/common_cells/upstream/src/onehot_to_bin.sv

VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/axi/upstream/src/axi_lite_to_apb.sv

# Prim modules
VERILOG_SOURCES += $(OCH_ROOT)/vendor/opentitan/upstream/hw/ip/prim/rtl/prim_edge_detector.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/opentitan/upstream/hw/ip/prim_generic/rtl/prim_flop.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/opentitan/upstream/hw/ip/prim_generic/rtl/prim_flop_2sync.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim_generic/rtl/prim_flop_3sync.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim_generic/rtl/prim_flop_3sync_r.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim_generic/rtl/prim_flop_4sync_r.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim_generic/rtl/prim_flop_4sync_s.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/opentitan/upstream/hw/ip/prim_generic/rtl/prim_clock_inv.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim_generic/rtl/prim_dffrxq.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim_generic/rtl/prim_dffsxq.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim_generic/rtl/prim_clock_nand2.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim_generic/rtl/prim_stdmux2.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim_generic/rtl/prim_metastab_hardened_dffr.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim_generic/rtl/prim_clock_mux2.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim/rtl/prim_ag_clk_mux.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim/rtl/prim_prog_clk_div_posedge.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim_generic/rtl/prim_stdbuf.sv

# Tech library modules (for sync and clock gating)
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim/rtl/prim_fifo_async.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim/rtl/prim_sync_randomized_delay.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim/rtl/prim_sync3.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim/rtl/prim_sync3_pulse.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim/rtl/prim_sync_reset.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim_generic/rtl/prim_clkgater.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim/rtl/prim_rstbypass_stdmux2.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim/rtl/prim_sync_data_autohs.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim/rtl/prim_sync2r.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim/rtl/prim_sync3r.sv

# AVSBus register packages and modules
VERILOG_SOURCES += $(OCH_ROOT)/hw/ip/avsbus_controller/data/registers/rtl/avsbus_controller_reg_pkg.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/ip/avsbus_controller/data/registers/rtl/avsbus_controller_reg.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/ip/avsbus_controller/data/registers/svh/avsbus_controller_reg.svh

# AVSBus core modules
VERILOG_SOURCES += $(OCH_ROOT)/hw/ip/avsbus_controller/rtl/avsbus_controller_pkg.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/ip/avsbus_controller/rtl/submodules/avsbus_crc3.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/ip/avsbus_controller/rtl/avsbus_controller.sv

# Testbench
VERILOG_SOURCES += $(OCH_ROOT)/hw/ip/avsbus_controller/tb/tb_avsbus_controller.sv

# COCOTB_TOPLEVEL is the name of the toplevel module in your Verilog or VHDL file
TOPLEVEL = tb_avsbus_controller

# COCOTB_TEST_MODULES is the basename of the Python test file(s)
MODULE = tb_avs_wrap

# Simulator-specific arguments
ifeq ($(SIM),verilator)
    # Verilator-specific arguments
    EXTRA_ARGS += --trace --trace-structs
    EXTRA_ARGS += --Wno-REDEFMACRO --Wno-WIDTHEXPAND --Wno-MULTIDRIVEN --Wno-PINMISSING --Wno-LATCH --Wno-UNOPTFLAT
    EXTRA_ARGS += --Wno-WIDTHTRUNC --Wno-UNSIGNED --Wno-IMPLICIT
    EXTRA_ARGS += --timing
    # Verilator include paths
    EXTRA_ARGS += -I$(OCH_ROOT)/hw/ip/avsbus_controller/tb/
    EXTRA_ARGS += -I$(OCH_ROOT)/hw/ip/avsbus_controller/data/registers/rtl/
    EXTRA_ARGS += -I$(OCH_ROOT)/hw/ip/avsbus_controller/data/registers/svh/
    EXTRA_ARGS += -I$(OCH_ROOT)/hw/ip/avsbus_controller/rtl/
    EXTRA_ARGS += -I$(OCH_ROOT)/hw/ip/avsbus_controller/rtl/submodules/
    EXTRA_ARGS += -I$(OCH_ROOT)/hw/common/
    EXTRA_ARGS += -I$(OCH_ROOT)/hw/common/och_prim/rtl/
    EXTRA_ARGS += -I$(OCH_ROOT)/vendor/opentitan/upstream/hw/ip/prim/rtl/
    EXTRA_ARGS += -I$(OCH_ROOT)/vendor/pulp-platform/apb/upstream/include/
    EXTRA_ARGS += -I$(OCH_ROOT)/vendor/pulp-platform/axi/upstream/include/
    EXTRA_ARGS += -I$(OCH_ROOT)/vendor/pulp-platform/common_cells/upstream/include/
endif

# VCS-specific include paths (using +incdir+ syntax)
ifeq ($(SIM),vcs)
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/ip/avsbus_controller/tb/
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/ip/avsbus_controller/data/registers/rtl/
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/ip/avsbus_controller/data/registers/svh/
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/ip/avsbus_controller/rtl/
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/ip/avsbus_controller/rtl/submodules/
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/common/
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/common/och_prim/rtl/
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/vendor/opentitan/upstream/hw/ip/prim/rtl/
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/vendor/pulp-platform/apb/upstream/include/
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/vendor/pulp-platform/axi/upstream/include/
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/vendor/pulp-platform/common_cells/upstream/include/
endif

# include cocotb's make rules to take care of the simulator setup
include $(shell cocotb-config --makefiles)/Makefile.sim

clean:: # cocotb's own `clean` uses double colon
	rm -rf __pycache__
	rm -rf simv simv.daidir csrc ucli.key vc_hdrs.h
	rm -rf *.vpd *.vcd *.fsdb
	rm -rf DVEfiles inter.vpd .vlogansetup.env .vlogansetup.args
	rm -rf work.lib++ .synopsys_vss.setup
