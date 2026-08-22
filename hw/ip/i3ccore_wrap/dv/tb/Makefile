# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# I3C Core Wrapper Testbench Makefile for Cocotb
# Standalone testbench for i3ccore_wrapper module

# Simulator to use - default to VCS
SIM ?= vcs

# Top level module and test module
TOPLEVEL = tb_i3ccore
MODULE ?= test_i3ccore

# All test modules (space-separated, in execution order)
ALL_TEST_MODULES = test_i3ccore i3c_immediate_write_sanity i3c_write_read_sanity i3c_long_write_sanity i3c_long_read_sanity i3c_direct_ccc_sanity i3c_ibi_sanity i3c_error_sanity \
    i3c_reg_reset_value_full i3c_full_ccc_matrix i3c_setnewda i3c_pp_timing_transfer i3c_od_pp_mode_switch \
    i3c_threshold_sweep i3c_max_length_transfer i3c_back_to_back i3c_broadcast_ccc i3c_ibi_payload_variants \
    i3c_ibi_nack_disabled i3c_hotjoin i3c_error_parity_inject i3c_error_target_abort i3c_multi_target_dat \
    i3c_multi_instance_indep i3c_axi_protocol i3c_recovery_reset_iface i3c_reset_mid_transaction \
    i3c_random_ccc_stress i3c_random_transfer_stress

# Optional cocotb X-resolution policy. cocotb raises on reading an X/Z bit by
# default (good — it surfaces real X-propagation bugs). Opt in to masking with
# e.g. `make MODULE=... RESOLVE_X=ZEROS` for tests that legitimately read
# reserved/unmapped registers. Leave unset to keep the strict (safe) default.
ifdef RESOLVE_X
    export COCOTB_RESOLVE_X = $(RESOLVE_X)
endif

# test_i3ccore deliberately reads un-written DAT/DCT SRAM and reset-X registers
# across the full address map; real SRAM powers up undefined, so resolve X->0 for
# this register-survey module by default (still overridable via RESOLVE_X).
ifeq ($(MODULE),test_i3ccore)
    export COCOTB_RESOLVE_X ?= ZEROS
endif

# Constrained-random seed (i3c_rand.py): export so the
# cocotb Python process sees it. `make MODULE=... SEED=0x1234` overrides the
# built-in default; alternatively pass +seed=<n> as a sim plusarg. Run several
# SEED values in regression and merge coverage to accumulate random bins.
ifdef SEED
    export SEED
endif

# Project root - go up to the repository root
PROJECT_ROOT := $(shell cd ../../../.. && pwd)

# Compilation arguments
# Include the filelist and testbench
# Pre-define register-interface assert macros (OPENSOURCE_REG_INTF_ASSERT) before
# any dependency RTL (e.g. i2c_core.sv) that uses them, to avoid an incdir-ordering
# collision between the common and register_interface prim_assert flavors.
COMPILE_ARGS += $(PROJECT_ROOT)/deps/register_interface/include/register_interface_prim_assert.sv
COMPILE_ARGS += -f $(PWD)/i3ccore_filelist.f
COMPILE_ARGS += $(PWD)/i3c_coverage_if.sv
COMPILE_ARGS += $(PWD)/tb_i3ccore.sv
COMPILE_ARGS += -debug_access+all

# Enable I3C functional coverage sampling (set I3C_COVERAGE=1 to turn on)
ifeq ($(I3C_COVERAGE),1)
    COMPILE_ARGS += +define+I3C_COVERAGE
    COMPILE_ARGS += -cm line+cond+fsm+tgl+branch
    SIM_ARGS += -cm line+cond+fsm+tgl+branch
endif

# Debug: use a simple write-forwarding behavioral DAT/DCT RAM instead of prim_ram
ifeq ($(I3C_BEHAV_DAT_MEM),1)
    COMPILE_ARGS += +define+I3C_BEHAV_DAT_MEM
endif

# VCS-specific options
ifeq ($(SIM),vcs)
    # -Mupdate enables incremental compilation - VCS checks file timestamps
    # and only recompiles changed files
    COMPILE_ARGS += -Mupdate
    COMPILE_ARGS += -j0
    COMPILE_ARGS += -lca +rad -kdb +nospecify
    COMPILE_ARGS += -debug_access+r+w+cbk -debug_access+thread+class+cbkd+dmpt+dmpf+idents_db
    COMPILE_ARGS += -l vcs.log
    COMPILE_ARGS += +define+SIM +define+VCS +define+COMMON_CELLS_ASSERTS_OFF +define+I3C_USE_AXI_LITE
    COMPILE_ARGS += +lint=PCWM +warn=noCWUC +warn=noUII-L -error:IWNF:1 +lint=TFIPC-L
    COMPILE_ARGS += +incdir+$(PWD)

    # FSDB waveform dumping support
    ifdef WAVES
        ifdef VERDI_HOME
            COMPILE_ARGS += -P $(VERDI_HOME)/share/PLI/VCS/LINUX64/novas.tab $(VERDI_HOME)/share/PLI/VCS/LINUX64/pli.a
            SIM_ARGS += +fsdb+delta +vcs+dumparrays
        else
            $(warning VERDI_HOME not set - FSDB dumping may not work)
            VERDI_HOME_CANDIDATE := $(shell which verdi 2>/dev/null | xargs dirname | xargs dirname 2>/dev/null || echo "")
            ifneq ($(VERDI_HOME_CANDIDATE),)
                VERDI_HOME := $(VERDI_HOME_CANDIDATE)
                $(info Found Verdi at: $(VERDI_HOME))
                COMPILE_ARGS += -P $(VERDI_HOME)/share/PLI/VCS/LINUX64/novas.tab $(VERDI_HOME)/share/PLI/VCS/LINUX64/pli.a
                SIM_ARGS += +fsdb+delta +vcs+dumparrays
            endif
        endif
    endif
endif

# Cocotb configuration
export COCOTB_REDUCED_LOG_FMT=1
export PYTHONPATH := $(PWD):$(PROJECT_ROOT)/vendor/chipsalliance/i3c-core/upstream/third_party/cocotbext-i3c/src:$(PYTHONPATH)

# Python shared library workaround
ifndef LIBPYTHON_LOC
    PYTHON_VERSION := $(shell python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PYTHON_PREFIX := $(shell python -c 'import sys; print(sys.prefix)')
    PYTHON_BASE_DIR := $(shell dirname $(PYTHON_PREFIX))

    LIBPYTHON_CANDIDATE := $(shell find $(PYTHON_PREFIX)/lib $(PYTHON_PREFIX)/lib64 -name "libpython$(PYTHON_VERSION).so*" -type f 2>/dev/null | head -1 || echo "")

    ifeq ($(LIBPYTHON_CANDIDATE),)
        LIBPYTHON_CANDIDATE := $(shell find $(PYTHON_BASE_DIR)/python-$(PYTHON_VERSION)*/lib $(PYTHON_BASE_DIR)/python-$(PYTHON_VERSION)*/lib64 -name "libpython$(PYTHON_VERSION).so*" -type f 2>/dev/null | head -1 || echo "")
    endif

    ifeq ($(LIBPYTHON_CANDIDATE),)
        LIBPYTHON_CANDIDATE := $(shell ldconfig -p 2>/dev/null | grep "libpython$(PYTHON_VERSION)\.so" | head -1 | awk '{print $$NF}' || echo "")
    endif

    ifneq ($(LIBPYTHON_CANDIDATE),)
        LIBPYTHON_LOC := $(LIBPYTHON_CANDIDATE)
        $(info Using libpython: $(LIBPYTHON_LOC))
    endif
endif

# Only include cocotb makefiles for non-meta targets
META_TARGETS = clean clean_all help filelist all_tests run
ifeq ($(filter $(META_TARGETS),$(MAKECMDGOALS)),)
    ifdef LIBPYTHON_LOC
        export LIBPYTHON_LOC
    endif
    include $(shell cocotb-config --makefiles)/Makefile.sim

    # Force rebuild when RTL files change
    # Extract actual file paths from filelist (filter out +incdir, +define, etc.)
    RTL_FILES := $(shell grep -v '^\s*[+-]' i3ccore_filelist.f 2>/dev/null | grep -v '^\s*$$' | grep -v '^\s*//')

    # Add testbench as dependency too
    RTL_FILES += $(PWD)/tb_i3ccore.sv

    # Make the simulator depend on all RTL files
    # This ensures Make triggers a rebuild when any source file changes
    $(SIM_BUILD)/simv: $(RTL_FILES)
else
    clean:
	@rm -rf __pycache__ results.xml sim_build *.log *.vcd *.fst *.wlf work transcript
endif

# Clean all target
clean_all: clean
	@rm -rf __pycache__ results.xml sim_build *.log *.vcd *.fst *.wlf work transcript *.fsdb

# Run all tests (each module in separate simulation for proper isolation)
all_tests:
	@echo "========================================"
	@echo "Running all I3C tests"
	@echo "========================================"
	@passed=0; failed=0; total=0; \
	failed_modules=""; \
	for mod in $(ALL_TEST_MODULES); do \
		total=$$((total + 1)); \
		echo ""; \
		echo "----------------------------------------"; \
		echo "[$$total] Running: $$mod"; \
		echo "----------------------------------------"; \
		set -o pipefail; \
		$(MAKE) MODULE=$$mod 2>&1 | tee /tmp/i3c_test_$$mod.log | tail -20; \
		make_exit=$$?; \
		set +o pipefail; \
		if [ $$make_exit -eq 0 ]; then \
			summary=$$(grep -oE "TESTS=[0-9]+ PASS=[0-9]+ FAIL=[0-9]+ SKIP=[0-9]+" /tmp/i3c_test_$$mod.log 2>/dev/null | tail -1); \
			nfail=$$(echo "$$summary" | sed -nE 's/.*FAIL=([0-9]+).*/\1/p'); \
			npass=$$(echo "$$summary" | sed -nE 's/.*PASS=([0-9]+).*/\1/p'); \
			if [ -n "$$summary" ] && [ "$$nfail" = "0" ] && [ "$${npass:-0}" -ge 1 ]; then \
				echo "[PASS] $$mod ($$summary)"; \
				passed=$$((passed + 1)); \
			else \
				echo "[FAIL] $$mod ($${summary:-no cocotb summary})"; \
				failed=$$((failed + 1)); \
				failed_modules="$$failed_modules $$mod"; \
			fi; \
		else \
			echo "[FAIL] $$mod - Make returned exit code $$make_exit"; \
			failed=$$((failed + 1)); \
			failed_modules="$$failed_modules $$mod"; \
		fi; \
	done; \
	echo ""; \
	echo "========================================"; \
	echo "TEST SUMMARY"; \
	echo "========================================"; \
	echo "Total:  $$total"; \
	echo "Passed: $$passed"; \
	echo "Failed: $$failed"; \
	if [ $$failed -gt 0 ]; then \
		echo "Failed modules:$$failed_modules"; \
		exit 1; \
	fi

# ---------------------------------------------------------------------------
# `run`: run one MODULE (optionally one TESTCASE) and collect artifacts into a
# per-run directory named  <RESULTS_DIR>/<MODULE>[_<TESTCASE>].<YYYYMMDD_HHMMSS>/
# containing:
#   - sim.log     (full simulation output, tee'd live to the terminal too)
#   - results.xml (cocotb pass/fail result)
#   - waves.fsdb  (only when WAVES=1)
# Reuses the already-built simv (no recompile when RTL is unchanged).
#
#   make run MODULE=i3c_setnewda
#   make run MODULE=i3c_error_sanity TESTCASE=i3c_fifo_overflow
#   make run MODULE=i3c_setnewda SEED=0x1234 WAVES=1
#   make run MODULE=i3c_setnewda RESULTS_DIR=/tmp/i3c_runs
# ---------------------------------------------------------------------------
RESULTS_DIR ?= $(PWD)/runs

run:
	@name="$(MODULE)$(if $(TESTCASE),_$(TESTCASE),)"; \
	ts=`date +%Y%m%d_%H%M%S`; \
	rundir="$(RESULTS_DIR)/$$name.$$ts"; \
	mkdir -p "$$rundir"; \
	echo "========================================"; \
	echo "[run] MODULE=$(MODULE)$(if $(TESTCASE), TESTCASE=$(TESTCASE),)$(if $(SEED), SEED=$(SEED),)$(if $(WAVES), WAVES=$(WAVES),)"; \
	echo "[run] dir : $$rundir"; \
	echo "========================================"; \
	( $(MAKE) sim MODULE=$(MODULE) \
		$(if $(TESTCASE),TESTCASE=$(TESTCASE),) \
		$(if $(SEED),SEED=$(SEED),) \
		$(if $(WAVES),WAVES=$(WAVES) WAVE_FILE=$$rundir/waves.fsdb,) ; \
	  echo $$? > "$$rundir/.rc" ) 2>&1 | tee "$$rundir/sim.log"; \
	cp -f results.xml "$$rundir/" 2>/dev/null || true; \
	rc=`cat "$$rundir/.rc" 2>/dev/null || echo 1`; rm -f "$$rundir/.rc"; \
	echo "[run] artifacts -> $$rundir"; \
	exit $$rc

# Waveform dumping
WAVE_FILE ?= test.fsdb
ifdef WAVES
    PLUSARGS += +waves
    PLUSARGS += +WAVE_FILE=$(WAVE_FILE)
endif

# Generate filelist using bender
# Uses the main project's Bender.yml with smc target which includes i3c-core files
# Filters out original i3c.sv and i3c_wrapper.sv from i3c-core (replaced by i3ccore_wrap versions)
filelist:
	@echo "Generating i3ccore_filelist.f from project root..."
	@cd $(PROJECT_ROOT) && source bin/setup_env.sh >/dev/null 2>&1 && \
		bender script flist-plus \
			-t smc \
			-t axi_rtl \
			-t apb_rtl \
			-t common_cells_rtl \
			-t common_cell_sync_shim \
		| grep -v 'vendor/chipsalliance/i3c-core/upstream/src/i3c\.sv' \
		| grep -v 'vendor/chipsalliance/i3c-core/upstream/src/i3c_wrapper\.sv' \
		> $(PWD)/i3ccore_filelist.f
	@echo "Generated i3ccore_filelist.f ($$(wc -l < $(PWD)/i3ccore_filelist.f) lines)"

# Open Verdi with waveforms
verdi:
	@echo "Opening Verdi with waveforms..."
	@if command -v verdi >/dev/null 2>&1; then \
		VERDI_CMD=verdi; \
	elif [ -n "$$VERDI_HOME" ] && [ -f "$$VERDI_HOME/bin/verdi" ]; then \
		VERDI_CMD="$$VERDI_HOME/bin/verdi"; \
	else \
		echo "ERROR: Verdi not found. Please set VERDI_HOME or ensure verdi is in PATH."; \
		exit 1; \
	fi; \
	if [ -f "$(WAVE_FILE)" ]; then \
		FSDB_FILE="$(WAVE_FILE)"; \
	elif [ -f "sim_build/$(WAVE_FILE)" ]; then \
		FSDB_FILE="sim_build/$(WAVE_FILE)"; \
	else \
		echo "ERROR: Waveform file '$(WAVE_FILE)' not found."; \
		echo "       Run 'make WAVES=1' first to generate waveforms."; \
		exit 1; \
	fi; \
	if [ -d "sim_build/simv.daidir" ]; then \
		$$VERDI_CMD -dbdir sim_build/simv.daidir -ssf $$FSDB_FILE -top $(TOPLEVEL) & \
	else \
		$$VERDI_CMD -ssf $$FSDB_FILE -top $(TOPLEVEL) & \
	fi; \
	echo "Verdi launched in background."

# Help
help:
	@echo "I3C Core Wrapper Testbench Makefile"
	@echo ""
	@echo "Setup (run once):"
	@echo "  cd $(PROJECT_ROOT) && source bin/setup_env.sh"
	@echo ""
	@echo "Targets:"
	@echo "  make                       - Run default tests (test_i3ccore) with VCS"
	@echo "  make run MODULE=<m>        - Run a module and save sim.log/results.xml(/waves) to a timestamped dir"
	@echo "  make all_tests             - Run ALL tests from all modules"
	@echo "  make test_module_separate  - Run all tests in MODULE separately (one sim per test)"
	@echo "  make filelist              - Generate i3ccore_filelist.f using bender"
	@echo "  make WAVES=1               - Run with waveform dumping"
	@echo "  make verdi                 - Open Verdi with waveforms"
	@echo "  make clean                 - Clean generated files"
	@echo "  make help                  - Show this help"
	@echo ""
	@echo "Variables:"
	@echo "  SIM            - Simulator (vcs)"
	@echo "  MODULE         - Test module (default: test_i3ccore)"
	@echo "  WAVES          - Enable waveform dumping (WAVES=1)"
	@echo "  WAVE_FILE      - Waveform filename (default: test.fsdb)"
	@echo "  RESULTS_DIR    - Base dir for 'make run' per-run folders (default: ./runs)"
	@echo "  SEED           - Constrained-random seed (e.g. SEED=0x1234); default in framework"
	@echo "  RESOLVE_X      - Resolve X reads (ZEROS/ONES) for reg-survey tests"
	@echo ""
	@echo "Examples:"
	@echo "  make MODULE=i3c_random_transfer_stress SEED=0x1   # constrained-random, fixed seed"
	@echo "  for s in 1 2 3 4 5; do make MODULE=i3c_random_transfer_stress SEED=\$$s; done  # multi-seed regression"
	@echo "  make filelist                                    # Generate filelist first"
	@echo "  make                                             # Run default tests (test_i3ccore)"
	@echo "  make all_tests                                   # Run ALL tests from all modules"
	@echo "  make all_tests WAVES=1                           # Run all tests with waveforms"
	@echo "  make MODULE=i3c_ibi_sanity                       # Run specific test module (all tests together)"
	@echo "  make test_module_separate MODULE=i3c_error_sanity WAVES=1  # Run each test separately"
	@echo "  make MODULE=i3c_error_sanity TESTCASE=i3c_fifo_overflow    # Run one specific test"
	@echo "  make verdi                                       # View waveforms"

# NOTE: For some reason this isn't working.
test_module_separate:
	@if [ -z "$(MODULE)" ]; then \
		echo "ERROR: MODULE not specified"; \
		echo "Usage: make test_module_separate MODULE=<module_name> [WAVES=1]"; \
		exit 1; \
	fi; \
	echo "========================================"; \
	echo "Running all tests in $(MODULE) separately"; \
	echo "========================================"; \
	echo ""; \
	grep -E "^(async def|def) [a-z_]+.*\(dut\)" $(MODULE).py | grep -B1 "@cocotb.test" | grep "^async def\|^def" | sed 's/.*def \([a-z_][a-z0-9_]*\).*/\1/' > /tmp/tests_$$$$.txt; \
	passed=0; failed=0; total=0; failed_tests=""; \
	while read test; do \
		[ -z "$$test" ] && continue; \
		total=$$((total + 1)); \
		echo ""; \
		echo "========================================"; \
		echo "[$$total] Running: $(MODULE).$$test"; \
		echo "========================================"; \
		rm -rf sim_build __pycache__ results.xml 2>/dev/null; \
		if $(MAKE) MODULE=$(MODULE) TESTCASE=$$test $(if $(WAVES),WAVES=$(WAVES)) 2>&1 | tee /tmp/test_$$test.log | tail -20; then \
			if grep -qE "passed.*FAIL=0|All tests passed|1 tests passed" /tmp/test_$$test.log 2>/dev/null && \
			   ! grep -qE "FAIL=[1-9]|failed|ERROR:" /tmp/test_$$test.log 2>/dev/null; then \
				echo "[PASS] $(MODULE).$$test"; \
				passed=$$((passed + 1)); \
			else \
				echo "[FAIL] $(MODULE).$$test - Check log for details"; \
				failed=$$((failed + 1)); \
				failed_tests="$$failed_tests $$test"; \
			fi; \
		else \
			echo "[FAIL] $(MODULE).$$test - Make returned error"; \
			failed=$$((failed + 1)); \
			failed_tests="$$failed_tests $$test"; \
		fi; \
	done < /tmp/tests_$$$$.txt; \
	rm -f /tmp/tests_$$$$.txt /tmp/test_*.log; \
	echo ""; \
	echo "========================================"; \
	echo "TEST SUMMARY - $(MODULE)"; \
	echo "========================================"; \
	echo "Total:  $$total"; \
	echo "Passed: $$passed"; \
	echo "Failed: $$failed"; \
	if [ $$failed -gt 0 ]; then \
		echo "Failed tests:$$failed_tests"; \
		exit 1; \
	fi

.PHONY: clean clean_all help filelist verdi all_tests test_module_separate run
