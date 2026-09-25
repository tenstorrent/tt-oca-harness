# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# Key Manager standalone cocotb/VCS testbench.
#
# Design RTL is gathered from Bender (see bender-targets.mk); the testbench top
# tb_key_manager.sv is added below. Firmware images are built by the shared
# DV firmware dispatcher (`make -f ocah.mk ocah-dv-fw-tests TARGET=key_manager`)
# which emits per-test ROM/VROM hex under hw/ip/key_manager/dv/fw/build/tests/.

# Try git first, fall back to OCH_ROOT, fail if neither available
_OCH_ROOT_GIT := $(shell git rev-parse --show-toplevel 2>/dev/null)
ifneq ($(_OCH_ROOT_GIT),)
  OCH_ROOT := $(_OCH_ROOT_GIT)
else ifndef OCH_ROOT
  $(error Not in a git repository and OCH_ROOT is not set)
endif
export OCH_ROOT
# cocotb's Makefile.inc resets SHELL to bash once it is included; .SHELLFLAGS
# stays at its default so that reassignment keeps every later shell call valid.
SHELL := bash

KM_ROOT := $(OCH_ROOT)/hw/ip/key_manager
FW_BUILD_TESTS := $(KM_ROOT)/dv/fw/build/tests

TOPLEVEL_LANG = verilog
SIM ?= vcs
WAVES ?= 0
FSDB ?= 0
DEBUG ?= 0
VUART_PRINT ?= 0

COCOTB_HDL_TIMEUNIT = 1ns
COCOTB_HDL_TIMEPRECISION = 1ps

# Handle 'x' and 'z' values in simulation (resolve to 0)
export COCOTB_RESOLVE_X ?= ZEROS

# Make test importable by Python
export PYTHONPATH := $(abspath .):$(PYTHONPATH)

# DUT wrapper and cocotb module
TOPLEVEL = tb_key_manager
TEST ?= test_rom_interface
MODULE ?= $(TEST)
# This testbench uses a single cocotb entrypoint.
TESTCASE ?= test_firmware_generic
export MODULE
export TESTCASE

# Build/output locations and cocotb logs
ifeq ($(FW_TEST),)
  LOG_TEST_NAME := $(TEST)
else
  LOG_TEST_NAME := $(FW_TEST)
endif
TEST_LOG_DIR := $(abspath sim/logs/$(LOG_TEST_NAME))
CYCLE_COUNT_DIR := $(abspath cycle_counts)
ifeq ($(WAVES), 1)
SIM_BUILD ?= $(abspath sim/build/$(TEST)_waves)
else
SIM_BUILD ?= $(abspath sim/build/$(TEST))
endif
export COCOTB_RESULTS_FILE := $(TEST_LOG_DIR)/results_$(LOG_TEST_NAME).xml
export COCOTB_LOG_FILE := $(TEST_LOG_DIR)/cocotb_$(LOG_TEST_NAME).log
export COCOTB_LOG_LEVEL := INFO
SIM_OUTPUT_LOG := $(TEST_LOG_DIR)/sim_output_$(LOG_TEST_NAME).log

$(TEST_LOG_DIR):
	@mkdir -p "$@"

$(CYCLE_COUNT_DIR):
	@mkdir -p "$@"

# Compile args and filelist
COMPILE_ARGS += -l $(TEST_LOG_DIR)/vcs.log
COMPILE_ARGS += -sverilog
COMPILE_ARGS += -timescale=1ns/1ps
ifeq ($(SIM),vcs)
  COMPILE_ARGS += -full64
endif
COMPILE_ARGS += +incdir+$(KM_ROOT)/dv/tb
COMPILE_ARGS += +incdir+$(KM_ROOT)/rtl
COMPILE_ARGS += +incdir+$(KM_ROOT)/regs/gen/svh
COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/common/ocah_prim/rtl
COMPILE_ARGS += +incdir+$(OCH_ROOT)/vendor/lowRISC/opentitan/upstream/hw/ip/prim/rtl
COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/common/assert
COMPILE_ARGS += +incdir+$(OCH_ROOT)/vendor/pulp-platform/axi/upstream/include
COMPILE_ARGS += +incdir+$(OCH_ROOT)/vendor/pulp-platform/common_cells/upstream/include
COMPILE_ARGS += -f $(TB_FILELIST)

# Optional extras
COMPILE_ARGS += -lca +rad -kdb +nospecify
ifeq ($(DEBUG), 0)
	COMPILE_ARGS += -debug_access-memcbk -debug_region+cell
else
	COMPILE_ARGS += -debug_access+all -debug_region+cell
endif

# Waves: VCD by default when WAVES=1; set FSDB=1 for FSDB output instead.
ifeq ($(WAVES), 1)
	COMPILE_ARGS += +vcs+dumparrays
	COMPILE_ARGS += -debug_access+all
	SIM_ARGS += +waves
ifdef VCD_START_NS
	SIM_ARGS += +vcd_start_ns=$(VCD_START_NS)
endif
ifdef VCD_END_NS
	SIM_ARGS += +vcd_end_ns=$(VCD_END_NS)
endif
	ifeq ($(FSDB), 1)
		COMPILE_ARGS += +fsdbfile+$(TEST_LOG_DIR)/tb_key_manager.fsdb
		COMPILE_ARGS += +fsdb+delta
		COMPILE_ARGS += +define+FSDB_DUMP
	else
		COMPILE_ARGS += +define+VCD_DUMP
		COMPILE_ARGS += +define+VCD_FILE=\"$(TEST_LOG_DIR)/tb_key_manager.vcd\"
	endif
endif

# Testbench directory (this Makefile's directory)
TB_DIR := $(abspath $(dir $(firstword $(MAKEFILE_LIST))))

# Include Bender targets (must be after TB_DIR is set)
include $(TB_DIR)/bender-targets.mk

# Filelist paths
RTL_FILELIST := $(TB_DIR)/rtl.f
TB_FILELIST := $(TB_DIR)/tb.f
RTL_FILELIST_SOURCES := $(shell [ -f "$(RTL_FILELIST)" ] && sed -n 's@^\(/[^/].*\)$$@\1@p' "$(RTL_FILELIST)")
BENDER_LOCKFILE := $(wildcard $(OCH_ROOT)/Bender.lock)

# Discover all key_manager RTL so any change triggers a filelist/sim rebuild.
KM_RTL_DIR := $(KM_ROOT)/rtl
KM_REG_RTL_DIR := $(KM_ROOT)/regs/gen/sv
KM_REG_SVH_DIR := $(KM_ROOT)/regs/gen/svh
KM_TB_DIR := $(KM_ROOT)/dv/tb
ALL_RTL_SOURCES := $(wildcard $(KM_RTL_DIR)/*.v $(KM_RTL_DIR)/*.sv) \
                   $(wildcard $(KM_REG_RTL_DIR)/*.v $(KM_REG_RTL_DIR)/*.sv) \
                   $(wildcard $(KM_REG_SVH_DIR)/*.svh) \
                   $(wildcard $(KM_TB_DIR)/*.v $(KM_TB_DIR)/*.sv)

# Testbench top file
TB_SV_FILE := $(KM_TB_DIR)/tb_key_manager.sv

# Python test file (try multiple locations)
PYTHON_TEST_FILE := $(TB_DIR)/$(MODULE).py
ifneq ($(wildcard $(PYTHON_TEST_FILE)),)
  # Found at expected location
else ifneq ($(wildcard $(TB_DIR)/test_$(MODULE).py),)
  PYTHON_TEST_FILE := $(TB_DIR)/test_$(MODULE).py
endif

# Custom compile dependencies for cocotb (set BEFORE including Makefile.sim)
CUSTOM_COMPILE_DEPS += $(TB_FILELIST) $(RTL_FILELIST)
CUSTOM_COMPILE_DEPS += $(ALL_RTL_SOURCES)
CUSTOM_COMPILE_DEPS += $(BENDER_LOCKFILE) $(RTL_FILELIST_SOURCES)
ifneq ($(wildcard $(PYTHON_TEST_FILE)),)
  CUSTOM_COMPILE_DEPS += $(PYTHON_TEST_FILE)
endif

# Include cocotb's make rules (after CUSTOM_COMPILE_DEPS is set). Cocotb also
# defines a `regression` target; keep this Makefile's firmware regression instead.
ifeq ($(filter help regression,$(MAKECMDGOALS)),)
include $(shell cocotb-config --makefiles)/Makefile.sim
endif

# Generate filelists from Bender if they don't exist.
.PHONY: filelist
filelist: $(RTL_FILELIST) $(TB_FILELIST)

# RTL filelist depends on local RTL sources and Bender manifests.
$(RTL_FILELIST): $(ALL_RTL_SOURCES) $(OCH_ROOT)/Bender.yml $(BENDER_LOCKFILE)
	@echo "Generating RTL filelist from Bender..."
	@cd $(OCH_ROOT) && $(MAKE) -f $(TB_DIR)/bender-targets.mk cocotb_simulation_filelist FILE_LIST=$(RTL_FILELIST)
	@if [ ! -f $(RTL_FILELIST) ]; then \
		echo "ERROR: RTL filelist generation failed!"; \
		exit 1; \
	fi
	@echo "RTL filelist ready: $(RTL_FILELIST)"

# Testbench filelist: Bender RTL flist + testbench top.
$(TB_FILELIST): $(RTL_FILELIST) $(TB_SV_FILE) | $(TEST_LOG_DIR)
	@echo "Generating testbench filelist..."
	@echo "// Key Manager Testbench file list" > $(TB_FILELIST)
	@echo "" >> $(TB_FILELIST)
	@echo "// RTL files from Bender" >> $(TB_FILELIST)
	@echo "-f $(RTL_FILELIST)" >> $(TB_FILELIST)
	@echo "" >> $(TB_FILELIST)
	@echo "// Testbench top" >> $(TB_FILELIST)
	@echo "$(TB_SV_FILE)" >> $(TB_FILELIST)
	@echo "Testbench filelist ready: $(TB_FILELIST)"

# Auto-generate filelists before compilation if missing
$(SIM_BUILD): $(TB_FILELIST)

#===========================================================================
# Firmware images (built by the shared DV firmware dispatcher)
#===========================================================================
# Firmware compiles in the OCAH toolchain container unless RISCV_TOOLCHAIN
# names a directory of `riscv64-unknown-elf-*` or `riscv-none-elf-*` tools whose
# gcc has picolibc.specs (compile.mk builds with --specs=picolibc.specs). That
# variable is the only host override, the same contract as the SMC/SEP cgen
# stages (hw/sys/sep/dv/sep_sim_cfg.toml [c_build] blocks); a toolchain on PATH
# is not consulted. `run-here` keeps host paths 1:1 so the absolute -C
# $(OCH_ROOT) resolves inside the sandbox, where RISCV_TOOLCHAIN/RISCV_PREFIX
# are unset so compile.mk takes the sandbox's own tools.
FW_DISPATCH_MK := -C $(OCH_ROOT) -f ocah.mk ocah-dv-fw-tests OCAH_ROOT=$(OCH_ROOT) TARGET=key_manager
define ocah_km_fw_dispatch
set -e; \
RV_TC="$(RISCV_TOOLCHAIN)"; RV_PFX="$(RISCV_PREFIX)"; \
if [ -n "$$RV_TC" ] && [ -z "$$RV_PFX" ]; then \
	if [ -x "$$RV_TC/riscv64-unknown-elf-gcc" ]; then RV_PFX=riscv64-unknown-elf-; \
	elif [ -x "$$RV_TC/riscv-none-elf-gcc" ]; then RV_PFX=riscv-none-elf-; \
	else RV_PFX=riscv64-unknown-elf-; fi; \
fi; \
if [ -z "$$RV_PFX" ]; then RV_PFX=riscv64-unknown-elf-; fi; \
if [ -n "$$RV_TC" ] && "$$RV_TC/$$RV_PFX"gcc -specs=picolibc.specs -E - </dev/null >/dev/null 2>&1; then \
	$(MAKE) $(FW_DISPATCH_MK) RISCV_TOOLCHAIN="$$RV_TC" RISCV_PREFIX="$$RV_PFX" $(1); \
elif [ -x $(OCH_ROOT)/scripts/docker-run.sh ]; then \
	echo "[build_fw] RISCV_TOOLCHAIN is unset or has no picolibc; building key_manager firmware in the OCAH toolchain container"; \
	env -u RISCV_TOOLCHAIN -u RISCV_PREFIX $(OCH_ROOT)/scripts/docker-run.sh run-here $(MAKE) $(FW_DISPATCH_MK) $(1); \
else \
	echo "error: set RISCV_TOOLCHAIN to a picolibc-enabled RISC-V toolchain, or provide scripts/docker-run.sh" >&2; exit 1; \
fi
endef

# Map cocotb test name to firmware name for the built-in named tests.
ifeq ($(TEST),test_rom_interface)
  FIRMWARE_NAME := test_rom_interface
  MODULE := test_firmware
else ifeq ($(TEST),test_sram_interface)
  FIRMWARE_NAME := test_sram_interface
  MODULE := test_firmware
endif

# Generic firmware test runner: FW_TEST selects the firmware image to run.
ifdef FW_TEST
  TEST := test_firmware
  MODULE := test_firmware
  TESTCASE := test_firmware_generic
  FIRMWARE_NAME := $(FW_TEST)
endif

ifdef FIRMWARE_NAME
  ROM_HEX_FILE := $(FW_BUILD_TESTS)/$(FIRMWARE_NAME)/$(FIRMWARE_NAME).rom.hex
  VROM_HEX_FILE := $(FW_BUILD_TESTS)/$(FIRMWARE_NAME)/$(FIRMWARE_NAME).vrom.hex
  ifneq ($(filter clean clean_all help,$(MAKECMDGOALS)),)
    # Skip ROM hex file check during clean/help
  else ifneq ($(filter regression build_all_fw build_fw compile_first,$(MAKECMDGOALS)),)
    # Skip when building firmware-only targets; firmware is built separately.
  else ifeq ($(wildcard $(ROM_HEX_FILE)),)
    $(warning ROM hex file not found: $(ROM_HEX_FILE))
    $(warning Build it first: make build_fw FW_TEST=$(FIRMWARE_NAME))
  else
    SIM_ARGS += +ROM_HEX_FILE=$(ROM_HEX_FILE)
    SIM_ARGS += +VROM_HEX_FILE=$(VROM_HEX_FILE)
  endif
endif

# VUART printing control (test_vuart always enables it).
ifeq ($(TEST),test_vuart)
  SIM_ARGS += +VUART_PRINT=1
else ifeq ($(VUART_PRINT),1)
  SIM_ARGS += +VUART_PRINT=1
endif

# Build one firmware image via the shared dispatcher.
.PHONY: build_fw
build_fw:
ifndef FW_TEST
	$(error FW_TEST is not set. Usage: make build_fw FW_TEST=<test_name>)
endif
	@echo "Building firmware via open dispatcher: $(FW_TEST)"
	@$(call ocah_km_fw_dispatch,TEST=$(FW_TEST))

# Build all discovered firmware images via the shared dispatcher.
.PHONY: build_all_fw
build_all_fw:
	@echo "Building all key_manager firmware via open dispatcher..."
	@$(call ocah_km_fw_dispatch,)

.PHONY: run
run: $(TB_FILELIST) | $(TEST_LOG_DIR)
	@echo "Simulation output will be logged to: $(SIM_OUTPUT_LOG)"
	@set -o pipefail; $(MAKE) TEST=$(TEST) FW_TEST=$(FW_TEST) MODULE=$(MODULE) TESTCASE=$(TESTCASE) \
		SIM_ARGS="$(SIM_ARGS)" \
		VUART_PRINT=$(VUART_PRINT) WAVES=$(WAVES) DEBUG=$(DEBUG) sim 2>&1 | tee "$(SIM_OUTPUT_LOG)"

.PHONY: run_fw
run_fw: build_fw
ifndef FW_TEST
	$(error FW_TEST is not set. Usage: make run_fw FW_TEST=<test_name>)
endif
	@echo "Running firmware test: $(FW_TEST)"
	$(MAKE) TEST=test_firmware FW_TEST=$(FW_TEST) run VUART_PRINT=$(VUART_PRINT) WAVES=$(WAVES) DEBUG=$(DEBUG)

# Run simulation without recompilation. Runs from the test's own log directory so
# that concurrent runs of the shared simv (see the regression below) do not share
# a working directory for the files VCS drops at runtime. Wave and log paths are
# absolute, so only those runtime droppings move.
.PHONY: run_no_compile
run_no_compile: | $(TEST_LOG_DIR)
	@echo "Simulation output will be logged to: $(SIM_OUTPUT_LOG)"
	@set -o pipefail; cd "$(TEST_LOG_DIR)" && \
	"$(SIM_BUILD)/simv" $(SIM_ARGS) +COCOTB_LOG_LEVEL=$(COCOTB_LOG_LEVEL) 2>&1 | tee "$(SIM_OUTPUT_LOG)"

# Compile the testbench without running a test, so a caller can separate the one
# compile from the many runs. TEST selects which SIM_BUILD is populated.
.PHONY: compile_first
compile_first: $(SIM_BUILD)/simv
	@echo "Testbench compiled: $(SIM_BUILD)/simv"

#===========================================================================
# Regression: build all firmware, compile once, run every test in parallel
#===========================================================================
# Discover firmware tests from the DV firmware tree (per-test directories).
FW_TESTS := $(notdir $(wildcard $(KM_ROOT)/dv/fw/tests/test_*))

# Concurrent simulations. Each job is one simv process of a small design, so the
# practical ceiling is VCS runtime licences rather than cores or memory.
PARALLEL_JOBS ?= 16

# Every firmware test runs the same testbench and takes its image from a plusarg,
# so the whole regression shares one simv: compile it once up front, then let the
# per-test jobs go straight to run_no_compile.
#
# SIM_BUILD is pinned on each recursive command line rather than left to TEST.
# Cocotb exports SIM_BUILD, so a sub-make inherits it from the environment, and an
# inherited value already satisfies this Makefile's `SIM_BUILD ?=` — passing only
# TEST would leave the child pointing at the parent's build directory.
REGRESSION_SIM_BUILD := $(abspath sim/build/test_firmware)
REGRESSION_STATUS_DIR := $(abspath sim/regression_status)
REGRESSION_JOBS := $(addprefix regression-run-,$(FW_TESTS))

# One test. Failures are recorded rather than raised so that a single bad test
# does not stop the other jobs; the summary below turns the status files into the
# regression's exit code. Not .PHONY: make does not apply pattern
# rules to phony targets, and nothing creates a file by this name anyway, so the
# recipe runs on every invocation.
regression-run-%:
	@mkdir -p "$(REGRESSION_STATUS_DIR)" "sim/logs/$*"
	@start=$$SECONDS; \
	$(MAKE) --no-print-directory run_no_compile \
		TEST=test_firmware FW_TEST=$* SIM_BUILD="$(REGRESSION_SIM_BUILD)" \
		> sim/logs/$*/regression_run.log 2>&1 || true; \
	elapsed=$$((SECONDS - start)); \
	if grep -qE "PASSED|PASS=1[[:space:]]+FAIL=0" sim/logs/$*/regression_run.log; then \
		echo PASSED > "$(REGRESSION_STATUS_DIR)/$*"; \
		echo "[$*] PASSED ($${elapsed}s)"; \
	else \
		echo FAILED > "$(REGRESSION_STATUS_DIR)/$*"; \
		echo "[$*] FAILED ($${elapsed}s)"; \
	fi

.PHONY: regression
regression:
	@if [ "$(WAVES)" = "1" ] || [ "$(FSDB)" = "1" ]; then \
		echo "Regression with WAVES/FSDB is not supported (shared simv dump paths)."; \
		exit 2; \
	fi
	@echo "==================================================================="
	@echo "Key Manager Testbench - Regression ($(words $(FW_TESTS)) tests, $(PARALLEL_JOBS) at a time)"
	@echo "==================================================================="
	@mkdir -p "$(CYCLE_COUNT_DIR)"
	@$(MAKE) clean 2>/dev/null || true
	@rm -rf "$(REGRESSION_STATUS_DIR)"
	@$(MAKE) build_all_fw
	@$(MAKE) compile_first TEST=test_firmware SIM_BUILD="$(REGRESSION_SIM_BUILD)"
	@$(MAKE) --no-print-directory -k -j$(PARALLEL_JOBS) $(REGRESSION_JOBS)
	@passed=$$(grep -lx PASSED "$(REGRESSION_STATUS_DIR)"/* 2>/dev/null | wc -l); \
	failed=$$(grep -lx FAILED "$(REGRESSION_STATUS_DIR)"/* 2>/dev/null | wc -l); \
	echo "==================================================================="; \
	echo "Summary: $$passed passed, $$failed failed"; \
	if [ $$failed -gt 0 ]; then \
		echo "Failed: $$(grep -lx FAILED "$(REGRESSION_STATUS_DIR)"/* | xargs -n1 basename | tr '\n' ' ')"; \
	fi; \
	echo "==================================================================="; \
	if [ $$failed -gt 0 ]; then exit 1; fi

.PHONY: help
help:
	@echo "Key Manager Testbench Makefile (open tree)"
	@echo ""
	@echo "Targets:"
	@echo "  run                - Build and run the selected test"
	@echo "  run_fw FW_TEST=<t> - Build firmware (via open dispatcher) and run it"
	@echo "  build_fw FW_TEST=<t> - Build one firmware image only"
	@echo "  build_all_fw       - Build all key_manager firmware images"
	@echo "  filelist           - Generate RTL and testbench filelists"
	@echo "  compile_first      - Compile the testbench without running a test"
	@echo "  regression         - Build all firmware and run every test_* image"
	@echo "  clean / clean_all  - Remove simulation artifacts and filelists"
	@echo "  help               - Show this help message"
	@echo ""
	@echo "Common variables:"
	@echo "  TEST=<name>        - Cocotb test selector (default: test_rom_interface)"
	@echo "  FW_TEST=<name>     - Firmware test to build/run with generic runner"
	@echo "  RISCV_TOOLCHAIN=<dir> - Picolibc-enabled toolchain dir (riscv64-unknown-elf-*"
	@echo "                     tools); unset, firmware builds in the toolchain container"
	@echo "  WAVES=1 FSDB=1     - Waveform dumping (VCD default; FSDB optional)"
	@echo "  DEBUG=1            - Broader VCS debug access"
	@echo "  VUART_PRINT=1      - Enable VUART printf output"
	@echo "  PARALLEL_JOBS=<n>  - Concurrent regression simulations (default: 16)"
	@echo ""
	@echo "Firmware is built by the shared open DV firmware dispatcher:"
	@echo "  make -f ocah.mk ocah-dv-fw-tests TARGET=key_manager [TEST=<t>]"

.PHONY: clean_all
# Use :: to allow multiple definitions (cocotb's Makefile.sim also defines clean)
clean::
	@echo "Cleaning simulation artifacts..."
	@if [ -d sim ]; then rm -rf sim; fi
	@if [ -f rtl.f ]; then rm -f rtl.f; fi
	@if [ -f tb.f ]; then rm -f tb.f; fi
	@echo "Clean complete (firmware: make -f ocah.mk ocah-dv-fw-clean TARGET=key_manager)"

clean_all: clean
