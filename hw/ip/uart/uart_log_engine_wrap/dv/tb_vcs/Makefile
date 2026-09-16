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

VERILOG_SOURCES += $(PWD)/tb_uart_log_engine_wrap.sv

DUT      = tb_uart_log_engine_wrap
TOPLEVEL = $(DUT)
MODULE   = test_uart_log_engine_wrap

COMPILE_ARGS += -lca +rad -kdb +nospecify
COMPILE_ARGS += -debug_access+r+w+cbk -debug_access+thread+class+cbkd+dmpt+dmpf+idents_db
COMPILE_ARGS += -l vcs.log
COMPILE_ARGS += +define+VCS -assert svaext
COMPILE_ARGS += +lint=TFIPC-L +lint=PCWM
COMPILE_ARGS += -f $(OCH_ROOT)/hw/periph/uart_log_engine_wrap/tb_vcs/uart_log_engine_wrap.f
COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/periph/uart_log_engine_wrap/data/registers/svh

SIM_ARGS += -assert nopostproc +vcs+dumparrays +vcs+lic+wait +embedded_skipper_debug +initRandMem=1

STRESS ?= 0

ifeq ($(STRESS), 1)
    PLUSARGS += +stress
endif

ifeq ($(WAVES), 1)
    SIM_ARGS += +waves +fsdb+delta +vcs+dumparrays
endif

ifeq ($(DEBUG), 0)
    COMPILE_ARGS += -debug_access-memcbk
endif

# include cocotb's make rules to take care of the simulator setup
include $(shell cocotb-config --makefiles)/Makefile.sim

clean:: # cocotb's own `clean` uses double colon
	rm -rf __pycache__

filelist:
	bender script flist-plus -t common_cells_rtl -t apb_rtl -t axi_rtl -t peripheral > uart_log_engine_wrap.f
