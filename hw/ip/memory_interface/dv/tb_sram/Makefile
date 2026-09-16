# This file is public domain, it can be freely copied without restrictions.
# SPDX-License-Identifier: CC0-1.0

# Makefile for SRAM Wrapper Testbench
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

# Get the repository root directory - try git first, fall back to OCH_ROOT, fail if neither available
_OCH_ROOT_GIT := $(shell git rev-parse --show-toplevel 2>/dev/null)
ifneq ($(_OCH_ROOT_GIT),)
  OCH_ROOT := $(_OCH_ROOT_GIT)
else ifndef OCH_ROOT
  $(error Not in a git repository and OCH_ROOT is not set)
endif

# AXI/AXI-Lite packages
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/axi/upstream/src/axi_pkg.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/apb/upstream/apb_pkg.sv

# Assertion macros
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim/rtl/prim_assert.sv

# Prim packages (must come first)
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim/rtl/prim_util_pkg.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim/rtl/prim_mubi_pkg.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/opentitan/upstream/hw/ip/prim/rtl/prim_secded_pkg.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/opentitan/upstream/hw/ip/prim_generic/rtl/prim_ram_1p_pkg.sv

# Prim modules for SRAM
VERILOG_SOURCES += $(OCH_ROOT)/vendor/opentitan/upstream/hw/ip/prim/rtl/prim_secded_inv_39_32_enc.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/opentitan/upstream/hw/ip/prim/rtl/prim_secded_inv_39_32_dec.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/opentitan/upstream/hw/ip/prim/rtl/prim_ram_1p_adv.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/opentitan/upstream/hw/ip/prim_generic/rtl/prim_ram_1p.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/opentitan/upstream/hw/ip/prim_generic/rtl/prim_flop.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/opentitan/upstream/hw/ip/prim_generic/rtl/prim_flop_en.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/opentitan/upstream/hw/ip/prim_generic/rtl/prim_buf.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/opentitan/upstream/hw/ip/prim_generic/rtl/prim_and2.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/opentitan/upstream/hw/ip/prim_generic/rtl/prim_xor2.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/opentitan/upstream/hw/ip/prim_generic/rtl/prim_xnor2.sv

# Common cells dependencies (must come before AXI modules)
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/common_cells/upstream/src/cf_math_pkg.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/common_cells/upstream/src/lzc.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/common_cells/upstream/src/rr_arb_tree.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/common_cells/upstream/src/spill_register_flushable.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/common_cells/upstream/src/spill_register.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/common_cells/upstream/src/fifo_v3.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/common_cells/upstream/src/stream_register.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/common_cells/upstream/src/stream_fifo.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/common_cells/upstream/src/stream_mux.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/common_cells/upstream/src/stream_fork.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/common_cells/upstream/src/stream_fork_dynamic.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/common_cells/upstream/src/stream_join.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/common_cells/upstream/src/stream_join_dynamic.sv

# AXI infrastructure
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/axi/upstream/src/axi_lite_to_axi.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/axi/upstream/src/axi_to_detailed_mem.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/axi/upstream/src/axi_to_mem.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/axi/upstream/src/axi_lite_demux.sv
VERILOG_SOURCES += $(OCH_ROOT)/vendor/pulp-platform/axi/upstream/src/axi_demux_simple.sv

# SRAM register packages and modules
VERILOG_SOURCES += $(OCH_ROOT)/hw/periph/memory_interface/data/registers/rtl/sram_example/example_sram_macro_csr_reg_pkg.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/periph/memory_interface/data/registers/rtl/sram_example/example_sram_macro_csr_reg.sv

# SRAM core modules
VERILOG_SOURCES += $(OCH_ROOT)/hw/periph/memory_interface/rtl/examples/sram/example_sram_pkg.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/periph/memory_interface/rtl/memory_interface.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/periph/memory_interface/rtl/examples/sram/example_sram_interface_shim.sv
VERILOG_SOURCES += $(OCH_ROOT)/hw/periph/memory_interface/rtl/examples/sram/example_sram_wrapper.sv

# Testbench
VERILOG_SOURCES += $(OCH_ROOT)/hw/periph/memory_interface/tb_sram/tb_sram.sv

# COCOTB_TOPLEVEL is the name of the toplevel module in your Verilog or VHDL file
TOPLEVEL = tb_sram

# COCOTB_TEST_MODULES is the basename of the Python test file(s)
MODULE = tb_sram

# Simulator-specific arguments
ifeq ($(SIM),verilator)
    # Verilator-specific arguments
    EXTRA_ARGS += --trace --trace-structs
    EXTRA_ARGS += --Wno-REDEFMACRO --Wno-WIDTHEXPAND --Wno-MULTIDRIVEN --Wno-PINMISSING --Wno-LATCH --Wno-UNOPTFLAT --Wno-WIDTHTRUNC
    EXTRA_ARGS += --timing
    # Verilator include paths
    EXTRA_ARGS += -I$(OCH_ROOT)/hw/periph/memory_interface/tb_sram/
    EXTRA_ARGS += -I$(OCH_ROOT)/hw/periph/memory_interface/data/registers/rtl/sram_example/
    EXTRA_ARGS += -I$(OCH_ROOT)/hw/periph/memory_interface/data/registers/svh/sram_example/
    EXTRA_ARGS += -I$(OCH_ROOT)/hw/periph/memory_interface/rtl/
    EXTRA_ARGS += -I$(OCH_ROOT)/hw/common/
    EXTRA_ARGS += -I$(OCH_ROOT)/hw/common/och_prim/rtl/
    EXTRA_ARGS += -I$(OCH_ROOT)/vendor/opentitan/upstream/hw/ip/prim/rtl/
    EXTRA_ARGS += -I$(OCH_ROOT)/vendor/pulp-platform/axi/upstream/include/
    EXTRA_ARGS += -I$(OCH_ROOT)/vendor/pulp-platform/apb/upstream/include/
    EXTRA_ARGS += -I$(OCH_ROOT)/vendor/pulp-platform/common_cells/upstream/include/
    EXTRA_ARGS += -I$(OCH_ROOT)/hw/common/assert/
endif

# VCS-specific include paths (using +incdir+ syntax)
ifeq ($(SIM),vcs)
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/periph/memory_interface/tb_sram/
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/periph/memory_interface/data/registers/rtl/sram_example/
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/periph/memory_interface/data/registers/svh/sram_example/
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/periph/memory_interface/rtl/
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/common/
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/common/och_prim/rtl/
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/vendor/opentitan/upstream/hw/ip/prim/rtl/
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/vendor/pulp-platform/axi/upstream/include/
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/vendor/pulp-platform/apb/upstream/include/
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/vendor/pulp-platform/common_cells/upstream/include/
    COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/common/assert/
endif

# include cocotb's make rules to take care of the simulator setup
include $(shell cocotb-config --makefiles)/Makefile.sim

clean:: # cocotb's own `clean` uses double colon
	rm -rf __pycache__ *.f
	rm -rf simv simv.daidir csrc ucli.key vc_hdrs.h
	rm -rf *.vpd *.vcd *.fsdb
	rm -rf DVEfiles inter.vpd .vlogansetup.env .vlogansetup.args
	rm -rf work.lib++ .synopsys_vss.setup
