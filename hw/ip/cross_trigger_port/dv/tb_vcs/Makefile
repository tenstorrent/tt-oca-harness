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
WAVES ?= 0
DEBUG ?= 0

COCOTB_HDL_TIMEUNIT = 1ns
COCOTB_HDL_TIMEPRECISION = 1ps

# Handle 'x' and 'z' values in simulation (resolve to 0)
export COCOTB_RESOLVE_X ?= ZEROS

# Make test and VIP importable by Python
# Add tb_vcs directory so 'from test.test_base' works, and axil_vip for AXI-Lite master
export PYTHONPATH := $(abspath .):$(abspath axil_vip):$(PYTHONPATH)

# DUT wrapper and cocotb module
TOPLEVEL = tb_cross_trigger_port
TEST ?= test_sanity
MODULE ?= test.$(TEST)
export MODULE

# Build/output locations and cocotb logs
# Organize logs and waveforms by testcase in sim/logs/<testname>/
# Use separate build directories for waves/no-waves to avoid recompilation issues
TEST_LOG_DIR := $(abspath sim/logs/$(TEST))
ifeq ($(WAVES), 1)
SIM_BUILD ?= $(abspath sim/build/$(TEST)_waves)
else
SIM_BUILD ?= $(abspath sim/build/$(TEST))
endif
export COCOTB_RESULTS_FILE := $(TEST_LOG_DIR)/results_$(TEST).xml
export COCOTB_LOG_FILE := $(TEST_LOG_DIR)/cocotb_$(TEST).log
export COCOTB_LOG_LEVEL := INFO

# Create test log directory
$(shell mkdir -p $(TEST_LOG_DIR))

# Compile args and filelist
COMPILE_ARGS += -l $(TEST_LOG_DIR)/vcs.log
COMPILE_ARGS += -sverilog
COMPILE_ARGS += -timescale=1ns/1ps
COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/ip/cross_trigger_port/tb_vcs
COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/common/och_prim/rtl
COMPILE_ARGS += +incdir+$(OCH_ROOT)/vendor/opentitan/upstream/hw/ip/prim/rtl
COMPILE_ARGS += +incdir+$(OCH_ROOT)/vendor/pulp-platform/axi/upstream/include
COMPILE_ARGS += +incdir+$(OCH_ROOT)/hw/common/assert
COMPILE_ARGS += -f $(OCH_ROOT)/hw/ip/cross_trigger_port/tb_vcs/rtl.f
COMPILE_ARGS += -f $(OCH_ROOT)/hw/ip/cross_trigger_port/tb_vcs/tb.f

# Optional extras similar to other components
COMPILE_ARGS += -lca +rad -kdb +nospecify
ifeq ($(DEBUG), 0)
	COMPILE_ARGS += -debug_access-memcbk -debug_region+cell
else
	COMPILE_ARGS += -debug_access+all -debug_region+cell
endif

# Waves (minimal; detailed FSDB setup can be added later)
ifeq ($(WAVES), 1)
	# Enable FSDB dump similar to other components
	# Output FSDB to test-specific log directory
	SIM_ARGS += +waves +fsdb+delta +vcs+dumparrays
	SIM_ARGS += +FSDB_FILE=$(TEST_LOG_DIR)/tb_cross_trigger_port.fsdb
	COMPILE_ARGS += +define+FSDB_DUMP
endif

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

clean:: # cocotb's own `clean` uses double colon
	rm -rf __pycache__ sim/vcs.log sim/logs sim/build
