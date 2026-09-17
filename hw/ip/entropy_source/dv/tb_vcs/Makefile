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

TOPLEVEL_LANG = verilog
SIM ?= vcs
WAVES ?= 1
DEBUG ?= 0
COV ?= 0

COCOTB_HDL_TIMEUNIT = 1ns
COCOTB_HDL_TIMEPRECISION = 1ps

# Handle 'x' and 'z' values in simulation (resolve to 0)
export COCOTB_RESOLVE_X ?= ZEROS

# Make test and VIP importable by Python
# Add tb_vcs directory so 'from test.test_base' works, and apb_vip for APB master
export PYTHONPATH := $(abspath .):$(abspath apb_vip):$(PYTHONPATH)

# DUT wrapper and cocotb module
TOPLEVEL = tb_entropy_top
TEST ?= test_smoke
MODULE ?= test.$(TEST)
export MODULE

# Build/output locations and cocotb logs
# Organize logs and waveforms by testcase in sim/logs/<testname>/
# Use separate build directories for waves/no-waves to avoid recompilation issues
# If TESTCASE is specified, use separate subdirectory for each testcase
ifdef TESTCASE
TEST_LOG_DIR := $(abspath sim/logs/$(TEST)/$(TESTCASE))
export COCOTB_RESULTS_FILE := $(TEST_LOG_DIR)/results_$(TESTCASE).xml
export COCOTB_LOG_FILE := $(TEST_LOG_DIR)/cocotb_$(TESTCASE).log
else
TEST_LOG_DIR := $(abspath sim/logs/$(TEST))
export COCOTB_RESULTS_FILE := $(TEST_LOG_DIR)/results_$(TEST).xml
export COCOTB_LOG_FILE := $(TEST_LOG_DIR)/cocotb_$(TEST).log
endif
ifeq ($(WAVES), 1)
SIM_BUILD ?= $(abspath sim/build/$(TEST)_waves)
else
SIM_BUILD ?= $(abspath sim/build/$(TEST))
endif
export COCOTB_LOG_LEVEL := INFO

# Coverage output directory (same as test log directory for organization)
COV_DIR := $(TEST_LOG_DIR)/coverage

# Create test log directory
$(shell mkdir -p $(TEST_LOG_DIR))

# Compile args and filelist
COMPILE_ARGS += -l $(TEST_LOG_DIR)/vcs.log
COMPILE_ARGS += -sverilog
COMPILE_ARGS += -timescale=1ns/1ps
COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/comp/entropy_source/tb_vcs
COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/comp/entropy_source/tb_vcs/models/compressor
COMPILE_ARGS += -f $(OCH_ROOT)/hw/comp/entropy_source/tb_vcs/rtl.f
COMPILE_ARGS += -f $(OCH_ROOT)/hw/comp/entropy_source/tb_vcs/tb.f

# Optional extras similar to other components
COMPILE_ARGS += -lca +rad -kdb +nospecify
ifeq ($(DEBUG), 0)
	COMPILE_ARGS += -debug_access-memcbk -debug_region+cell
else
	COMPILE_ARGS += -debug_access+all -debug_region+cell
endif

# Code Coverage support
ifeq ($(COV), 1)
	# Enable all coverage types: line, condition, FSM, toggle, branch
	COMPILE_ARGS += -cm line+cond+fsm+tgl+branch
	COMPILE_ARGS += -cm_dir $(COV_DIR)/simv.vdb
	# Runtime coverage collection arguments
	SIM_ARGS += -cm line+cond+fsm+tgl+branch
	SIM_ARGS += -cm_dir $(COV_DIR)/simv.vdb
	SIM_ARGS += -cm_name $(TEST)
	# Enable coverage logging
	SIM_ARGS += -cm_log $(COV_DIR)/coverage.log
endif

# Waves
ifeq ($(WAVES), 1)
	# Enable FSDB dump similar to other components
	# Output FSDB to test-specific log directory
	# +fsdb+struct=on: Enable structure member dumping
	# +mda: Enable multi-dimensional array dumping
	SIM_ARGS += +waves +fsdb+delta +fsdb+struct=on +mda +vcs+dumparrays
	SIM_ARGS += +FSDB_FILE=$(TEST_LOG_DIR)/tb_entropy_top.fsdb
	COMPILE_ARGS += +define+FSDB_DUMP
endif
# WAVES=0 leaves FSDB_DUMP undefined; the _waves build directory keeps the two
# compiles apart.

# Include cocotb's make rules
include $(shell cocotb-config --makefiles)/Makefile.sim

.PHONY: run
run: sim

# Run simulation without recompilation (when simv is up-to-date)
.PHONY: run_no_compile
run_no_compile:
	@echo "==================================================================="
	@echo "Running simulation without recompilation (simv is up-to-date)"
	@echo "==================================================================="
	cd $(SIM_BUILD) && \
	./simv $(SIM_ARGS) +COCOTB_LOG_LEVEL=$(COCOTB_LOG_LEVEL)
ifeq ($(COV), 1)
	@$(MAKE) cov_report
endif

# Generate coverage reports using urg (Unified Report Generator)
.PHONY: cov_report
cov_report:
	@echo "==================================================================="
	@echo "Generating coverage reports..."
	@echo "==================================================================="
	@if [ -d "$(COV_DIR)/simv.vdb" ]; then \
		mkdir -p $(COV_DIR)/reports; \
		urg -dir $(COV_DIR)/simv.vdb \
		    -report $(COV_DIR)/reports \
		    -format both \
		    -elfile $(OCH_ROOT)/hw/comp/entropy_source/tb_vcs/coverage.el 2>/dev/null || \
		urg -dir $(COV_DIR)/simv.vdb \
		    -report $(COV_DIR)/reports \
		    -format both; \
		echo "Coverage reports generated in: $(COV_DIR)/reports"; \
		echo "View HTML report: $(COV_DIR)/reports/hierarchy.html"; \
	else \
		echo "ERROR: Coverage database not found at $(COV_DIR)/simv.vdb"; \
		echo "       Run simulation with COV=1 first"; \
		exit 1; \
	fi

clean:: # cocotb's own `clean` uses double colon
	rm -rf __pycache__ sim/vcs.log
	rm -rf sim/logs/*/coverage sim/logs/*/*/coverage
