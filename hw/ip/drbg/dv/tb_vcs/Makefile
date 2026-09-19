# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Try git first, fall back to OCH_ROOT, fail if neither available
_OCH_ROOT_GIT := $(shell git rev-parse --show-toplevel 2>/dev/null)
ifneq ($(_OCH_ROOT_GIT),)
  OCH_ROOT := $(_OCH_ROOT_GIT)
else ifndef OCH_ROOT
  $(error Not in a git repository and OCH_ROOT is not set)
endif
export OCH_ROOT

SIM ?= vcs
WAVES ?= 0
DEBUG ?= 0
TOPLEVEL_LANG = verilog
TOPLEVEL = tb_drbg
MODULE = test_drbg
TESTCASE ?=
COCOTB_HDL_TIMEUNIT = 1ns
COCOTB_HDL_TIMEPRECISION = 1ps
export COCOTB_RESOLVE_X ?= ZEROS
export PYTHONPATH := $(abspath .):$(PYTHONPATH)

TB_DIR := $(CURDIR)
VERILOG_SOURCES += $(TB_DIR)/tb_drbg.sv

FILELIST := $(TB_DIR)/drbg.f
VCS_PARAM_OVERRIDES ?=
VERILATOR_PARAM_OVERRIDES ?=

ifeq ($(TESTCASE),)
else
  export COCOTB_TESTCASE := $(TESTCASE)
endif

ifeq ($(SIM),vcs)
  COMPILE_ARGS += -f $(FILELIST)
  COMPILE_ARGS += -sverilog -timescale=1ns/1ps -full64 +vcs+lic+wait
  COMPILE_ARGS += -lca +rad -kdb +nospecify
  ifeq ($(DEBUG),0)
    COMPILE_ARGS += -debug_access-memcbk
  else
    COMPILE_ARGS += -debug_access+all
  endif
  ifneq ($(strip $(VCS_PARAM_OVERRIDES)),)
    COMPILE_ARGS += $(VCS_PARAM_OVERRIDES)
  endif
  SIM_ARGS += +ntb_random_seed_automatic +vcs+lic+wait
  ifeq ($(WAVES),1)
    SIM_ARGS += +waves
  endif
else ifeq ($(SIM),verilator)
  EXTRA_ARGS += -f $(FILELIST)
  EXTRA_ARGS += --timing --trace --trace-structs
  EXTRA_ARGS += --Wno-UNUSEDSIGNAL --Wno-WIDTH --Wno-PINCONNECTEMPTY --Wno-CASEINCOMPLETE
  ifneq ($(strip $(VERILATOR_PARAM_OVERRIDES)),)
    EXTRA_ARGS += $(VERILATOR_PARAM_OVERRIDES)
  endif
endif

include $(shell cocotb-config --makefiles)/Makefile.sim

.PHONY: filelist
filelist:
	bender script flist-plus -t drbg > $(FILELIST)

.PHONY: build-verilator
build-verilator: filelist
	$(MAKE) SIM=verilator compile

.PHONY: sim-vcs
sim-vcs: filelist
	$(MAKE) SIM=vcs

.PHONY: sim-verilator
sim-verilator: filelist
	$(MAKE) SIM=verilator

.PHONY: smoke-nondefault-vcs
smoke-nondefault-vcs: filelist
	$(MAKE) SIM=vcs VCS_PARAM_OVERRIDES="-pvalue+tb_drbg.INGRESS_FIFO_DEPTH=4 -pvalue+tb_drbg.SEED_FIFO_DEPTH=2 -pvalue+tb_drbg.EDN_ENDPOINT_COUNT=2 -pvalue+tb_drbg.ENDPOINT_FIFO_DEPTH=4"

.PHONY: smoke-nondefault-verilator
smoke-nondefault-verilator: filelist
	$(MAKE) SIM=verilator VERILATOR_PARAM_OVERRIDES="-GINGRESS_FIFO_DEPTH=4 -GSEED_FIFO_DEPTH=2 -GEDN_ENDPOINT_COUNT=2 -GENDPOINT_FIFO_DEPTH=4"

.PHONY: clean
clean::
	rm -rf __pycache__ sim_build simv simv.daidir csrc ucli.key vc_hdrs.h
	rm -rf *.vcd *.vpd *.fst *.fsdb $(FILELIST)
