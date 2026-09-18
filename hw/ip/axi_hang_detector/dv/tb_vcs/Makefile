# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Try git first, fall back to OCH_ROOT, fail if neither available
_OCH_ROOT_GIT := $(shell git rev-parse --show-toplevel 2>/dev/null)
ifneq ($(_OCH_ROOT_GIT),)
  OCH_ROOT := $(_OCH_ROOT_GIT)
else ifndef OCH_ROOT
  $(error Not in a git repository and OCH_ROOT is not set)
endif

TOPLEVEL_LANG = verilog

SIM ?= vcs
WAVES ?= 1
DEBUG ?= 0

COCOTB_HDL_TIMEUNIT = 1ns
COCOTB_HDL_TIMEPRECISION = 1ps

# Sources, in dependency order. The IP has no CSR block of its own (config lives
# in cpu_ctrl at the SMC level), so the dependency set is just prim_axi_snoop +
# the IP + this tb wrapper. Listed directly rather than via the Bender filelist.
HANG := $(OCH_ROOT)/hw/ip/axi_hang_detector
VERILOG_SOURCES += $(OCH_ROOT)/hw/common/och_prim/rtl/prim_axi_snoop.sv
VERILOG_SOURCES += $(HANG)/rtl/axi_hang_detector.sv
VERILOG_SOURCES += $(PWD)/tb_axi_hang_detector.sv

DUT      = tb_axi_hang_detector
TOPLEVEL = $(DUT)
# Timeout-counter datapath unit tests (helpers.py drives config wires + snoop).
MODULE   = test_timeout

# Include paths for prim_assert.sv (axi_hang_detector / prim_axi_snoop) and the
# assert macro headers it pulls in (prim_assert_sec_cm.svh, prim_flop_macros.sv).
COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/common/assert
COMPILE_ARGS += +incdir+$(OCH_ROOT)/vendor/lowRISC/opentitan/upstream/hw/ip/prim/rtl
COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/common/och_prim/rtl
COMPILE_ARGS += +incdir+$(OCH_ROOT)/vendor/pulp-platform/register_interface/upstream/include

COMPILE_ARGS += -lca +rad -kdb +nospecify
COMPILE_ARGS += -debug_access+r+w+cbk -debug_access+thread+class+cbkd+dmpt+dmpf+idents_db
COMPILE_ARGS += -l vcs.log
COMPILE_ARGS += +define+VCS -assert svaext
COMPILE_ARGS += +lint=TFIPC-L +lint=PCWM

SIM_ARGS += -assert nopostproc +vcs+dumparrays +vcs+lic+wait +initRandMem=1

ifeq ($(WAVES), 1)
    SIM_ARGS += +waves +fsdb+delta +vcs+dumparrays
endif

ifeq ($(DEBUG), 0)
    COMPILE_ARGS += -debug_access-memcbk
endif

# include cocotb's make rules to take care of the simulator setup
include $(shell cocotb-config --makefiles)/Makefile.sim

clean:: # cocotb's own `clean` uses double colon
	rm -rf __pycache__ *.f
