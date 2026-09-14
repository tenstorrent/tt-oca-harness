# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

#------------------------------------------------------------------------------
# Entropy Component Test Suite
# Simplified Makefile for component testbenches using iverilog simulator
#------------------------------------------------------------------------------

# Simulation tools
IVERILOG = iverilog
VVP = vvp
SURFER = surfer
VERILATOR = verilator

# Common source files
RTL_DIR = ../../rtl
PRIM_RTL_DIR = ../../../../common/och_prim_generic/rtl
COMMON_RTL = $(PRIM_RTL_DIR)/prim_clock_nand2.sv \
             $(PRIM_RTL_DIR)/prim_dffrxq.sv \
             $(PRIM_RTL_DIR)/prim_inv.sv \
             $(PRIM_RTL_DIR)/prim_stdbuf.sv \
             $(PRIM_RTL_DIR)/prim_stdmux2.sv \
             $(RTL_DIR)/entropy_ring_stage_wrappers.sv

# Ring Oscillator test configuration
RING_SOURCES = $(COMMON_RTL) $(RTL_DIR)/entropy_ring_oscillator.sv $(RTL_DIR)/entropy_noise_source.sv
RING_TESTBENCH = tb_ring_oscillator.v
RING_SIM_OUT = tb_ring_oscillator
RING_VCD_FILE = ring_oscillator.vcd
RING_SMOKE_TESTBENCH = tb_ring_smoke.sv
RING_SMOKE_SIM_OUT = tb_ring_smoke

# Debug Monitor test configuration
DEBUG_SOURCES = $(COMMON_RTL) $(RTL_DIR)/entropy_ripple_divider.sv $(RTL_DIR)/entropy_debug_monitor.sv
DEBUG_TESTBENCH = tb_debug_monitor.v
DEBUG_SIM_OUT = tb_debug_monitor
DEBUG_VCD_FILE = debug_monitor.vcd

# Repetition Test configuration
REP_SOURCES = $(RTL_DIR)/entropy_repetition_test.sv
REP_TESTBENCH = tb_repetition_test.v
REP_SIM_OUT = tb_repetition_test
REP_VCD_FILE = repetition_test.vcd

# Repetition Threshold Test configuration
REP_THRESH_SOURCES = $(RTL_DIR)/entropy_repetition_test.sv
REP_THRESH_TESTBENCH = tb_repetition_threshold.v
REP_THRESH_SIM_OUT = tb_repetition_threshold
REP_THRESH_VCD_FILE = repetition_threshold.vcd

# Repetition Simple Runs Test configuration (comprehensive verification)
REP_SIMPLE_SOURCES = $(RTL_DIR)/entropy_repetition_test.sv
REP_SIMPLE_TESTBENCH = tb_repetition_simple_runs.v
REP_SIMPLE_SIM_OUT = tb_repetition_simple_runs
REP_SIMPLE_VCD_FILE = repetition_simple_runs.vcd

# Markov Test configuration
MARKOV_SOURCES = $(RTL_DIR)/entropy_markov_test.sv
MARKOV_TESTBENCH = tb_markov_test.sv
MARKOV_SIM_OUT = tb_markov_test
MARKOV_VCD_FILE = markov_test.vcd

# Integrated Health Test configuration
HEALTH_SOURCES = $(RTL_DIR)/entropy_health_test.sv $(RTL_DIR)/entropy_repetition_test.sv $(RTL_DIR)/entropy_adaptive_proportion_test.sv $(RTL_DIR)/entropy_markov_test.sv
HEALTH_TESTBENCH = tb_health_test.v
HEALTH_SIM_OUT = tb_health_test
HEALTH_VCD_FILE = health_test.vcd

# Sample Clock Divider Test configuration
SCLKDIV_SOURCES = $(COMMON_RTL) $(RTL_DIR)/entropy_ripple_divider.sv $(RTL_DIR)/entropy_sampler_clocks.sv $(RTL_DIR)/entropy_generator.sv $(RTL_DIR)/entropy_noise_source.sv $(RTL_DIR)/entropy_ring_oscillator.sv $(RTL_DIR)/entropy_decorrelator.sv $(RTL_DIR)/entropy_health_test.sv $(RTL_DIR)/entropy_repetition_test.sv $(RTL_DIR)/entropy_adaptive_proportion_test.sv $(RTL_DIR)/entropy_markov_test.sv $(RTL_DIR)/entropy_rosc_tune_fsm.sv $(RTL_DIR)/gf_muladd.sv entropy_generator_test_wrapper.sv
SCLKDIV_TESTBENCH = tb_sample_clk_divider.v
SCLKDIV_SIM_OUT = tb_sample_clk_divider
SCLKDIV_FULL_SIM_OUT = tb_sample_clk_divider_full
SCLKDIV_VCD_FILE = sample_clk_divider.vcd

# Entropy FIFO Test configuration
FIFO_SOURCES = $(RTL_DIR)/entropy_fifo.sv
FIFO_TESTBENCH = tb_entropy_fifo.v
FIFO_SIM_OUT = tb_entropy_fifo
FIFO_VCD_FILE = entropy_fifo.vcd

# AXI4-Lite Register Interface Test configuration (Verilator)
AXI4LITE_INTF = ../../../../common/axi/axi4lite_intf.sv
AXI4LITE_SOURCES = $(AXI4LITE_INTF) \
                   $(REG_RTL_DIR)/entropy_source_reg_pkg.sv $(RTL_DIR)/entropy_source_pkg.sv \
                   $(COMMON_RTL) $(RTL_DIR)/entropy_ring_oscillator.sv \
                   $(RTL_DIR)/entropy_noise_source.sv $(RTL_DIR)/entropy_sampler_clocks.sv \
                   $(RTL_DIR)/entropy_generator.sv $(RTL_DIR)/entropy_decorrelator.sv \
                   $(RTL_DIR)/entropy_health_test.sv $(RTL_DIR)/entropy_repetition_test.sv \
                   $(RTL_DIR)/entropy_adaptive_proportion_test.sv $(RTL_DIR)/entropy_markov_test.sv \
                   $(RTL_DIR)/entropy_rosc_tune_fsm.sv $(RTL_DIR)/gf_muladd.sv \
                   $(RTL_DIR)/entropy_generator_complex.sv $(RTL_DIR)/entropy_fifo.sv \
                   $(RTL_DIR)/entropy_debug_monitor.sv $(RTL_DIR)/entropy_ripple_divider.sv \
                   $(REG_RTL_DIR)/entropy_source_reg.sv \
                   $(RTL_DIR)/entropy_source.sv
AXI4LITE_TESTBENCH = tb_entropy_source_axi4lite.cpp
AXI4LITE_OBJ_DIR = obj_dir_axi4lite
AXI4LITE_EXECUTABLE = $(AXI4LITE_OBJ_DIR)/Ventropy_source
AXI4LITE_VCD_FILE = entropy_source_axi4lite.vcd

# Verilator Lint configuration
REG_RTL_DIR = ../../regs/gen/sv
VERILATOR_BUILD_DIR = verilator_lint
VERILATOR_FILELIST = $(VERILATOR_BUILD_DIR)/entropy_source_complete.f
VERILATOR_FLAGS = --lint-only --no-timing -Wall -Wno-fatal --top-module entropy_source
VERILATOR_BACKUP_SCRIPT = verify_verilator_compilation.sh

# Default target shows help
all: help

#==============================================================================
# RING OSCILLATOR TARGETS
#==============================================================================

# Ring oscillator simulation
ring: $(RING_SIM_OUT)
	@echo "=== Running Ring Oscillator Test ==="
	$(VVP) $(RING_SIM_OUT)

ring-smoke: $(RING_SMOKE_SIM_OUT)
	@echo "=== Running Ring Oscillator Smoke Test ==="
	$(VVP) $(RING_SMOKE_SIM_OUT)

# Compile ring oscillator testbench
$(RING_SIM_OUT): $(RING_SOURCES) $(RING_TESTBENCH)
	@echo "=== Compiling Ring Oscillator Test ==="
	$(IVERILOG) -g2012 -DSIMULATION -o $(RING_SIM_OUT) $(RING_SOURCES) $(RING_TESTBENCH)

$(RING_SMOKE_SIM_OUT): $(RING_SOURCES) $(RING_SMOKE_TESTBENCH)
	@echo "=== Compiling Ring Oscillator Smoke Test ==="
	$(IVERILOG) -g2012 -DSIMULATION -o $(RING_SMOKE_SIM_OUT) $(RING_SOURCES) $(RING_SMOKE_TESTBENCH)

# View ring oscillator waveforms
ring-waves: $(RING_VCD_FILE)
	@echo "=== Opening Ring Oscillator Waveforms ==="
	$(SURFER) $(RING_VCD_FILE) &

# Clean ring oscillator files
ring-clean:
	@echo "=== Cleaning Ring Oscillator Files ==="
	rm -f $(RING_SIM_OUT) $(RING_SMOKE_SIM_OUT) $(RING_VCD_FILE)

#==============================================================================
# DEBUG MONITOR TARGETS
#==============================================================================

# Debug monitor simulation
debug: $(DEBUG_SIM_OUT)
	@echo "=== Running Debug Monitor Test ==="
	$(VVP) $(DEBUG_SIM_OUT)

# Compile debug monitor testbench
$(DEBUG_SIM_OUT): $(DEBUG_SOURCES) $(DEBUG_TESTBENCH)
	@echo "=== Compiling Debug Monitor Test ==="
	$(IVERILOG) -g2012 -DSIMULATION -o $(DEBUG_SIM_OUT) $(DEBUG_SOURCES) $(DEBUG_TESTBENCH)

# View debug monitor waveforms
debug-waves: $(DEBUG_VCD_FILE)
	@echo "=== Opening Debug Monitor Waveforms ==="
	$(SURFER) $(DEBUG_VCD_FILE) &

# Clean debug monitor files
debug-clean:
	@echo "=== Cleaning Debug Monitor Files ==="
	rm -f $(DEBUG_SIM_OUT) $(DEBUG_VCD_FILE)

#==============================================================================
# TUNE FSM TEST TARGETS
#==============================================================================

# Tune FSM test configuration (rising edge only)
TUNE_FSM_CORRECT_SOURCES = $(RTL_DIR)/entropy_rosc_tune_fsm.sv
TUNE_FSM_CORRECT_TESTBENCH = tb_rosc_tune_fsm_correct.v
TUNE_FSM_CORRECT_SIM_OUT = tb_rosc_tune_fsm_correct
TUNE_FSM_CORRECT_VCD_FILE = rosc_tune_fsm_correct.vcd

# Tune FSM rising-edge-only toggle test
tune-fsm-correct: $(TUNE_FSM_CORRECT_SIM_OUT)
	@echo "=== Running Tune FSM Correct Behavior Test ==="
	$(VVP) $(TUNE_FSM_CORRECT_SIM_OUT)

# Compile tune FSM correct testbench
$(TUNE_FSM_CORRECT_SIM_OUT): $(TUNE_FSM_CORRECT_SOURCES) $(TUNE_FSM_CORRECT_TESTBENCH)
	@echo "=== Compiling Tune FSM Correct Test ==="
	$(IVERILOG) -g2012 -DSIMULATION -o $(TUNE_FSM_CORRECT_SIM_OUT) $(TUNE_FSM_CORRECT_SOURCES) $(TUNE_FSM_CORRECT_TESTBENCH)

# View tune FSM correct waveforms
tune-fsm-correct-waves: $(TUNE_FSM_CORRECT_VCD_FILE)
	@echo "=== Opening Tune FSM Correct Waveforms ==="
	$(SURFER) $(TUNE_FSM_CORRECT_VCD_FILE) &

# Clean tune FSM correct files
tune-fsm-correct-clean:
	@echo "=== Cleaning Tune FSM Correct Files ==="
	rm -f $(TUNE_FSM_CORRECT_SIM_OUT) $(TUNE_FSM_CORRECT_VCD_FILE)

#==============================================================================
# REPETITION TEST TARGETS
#==============================================================================

# Comprehensive repetition testing - runs both test suites
repetition: $(REP_SIM_OUT) $(REP_SIMPLE_SIM_OUT)
	@echo ""
	@echo "=========================================="
	@echo "  COMPREHENSIVE REPETITION TEST SUITE"
	@echo "=========================================="
	@echo ""
	@echo "=== Test 1/2: Original Comprehensive Test ==="
	@echo "Tests: Random data patterns, enable/disable, stuck-at failures, recovery, saturation"
	@echo ""
	$(VVP) $(REP_SIM_OUT)
	@echo ""
	@echo "=== Test 2/2: Simple Runs Verification Test ==="
	@echo "Tests: 168 exact boundary tests (thresholds 5-25, run lengths threshold±2)"
	@echo ""
	$(VVP) $(REP_SIMPLE_SIM_OUT)
	@echo ""
	@echo "=========================================="
	@echo "  COMPREHENSIVE TESTING COMPLETE"
	@echo "=========================================="
	@echo ""

# Compile repetition test testbench
$(REP_SIM_OUT): $(REP_SOURCES) $(REP_TESTBENCH)
	@echo "=== Compiling Repetition Test ==="
	$(IVERILOG) -g2012 -DSIMULATION -o $(REP_SIM_OUT) $(REP_SOURCES) $(REP_TESTBENCH)

# View repetition test waveforms (both tests)
repetition-waves: $(REP_VCD_FILE) $(REP_SIMPLE_VCD_FILE)
	@echo "=== Opening Original Repetition Test Waveforms ==="
	$(SURFER) $(REP_VCD_FILE) &
	@echo "=== Opening Simple Runs Test Waveforms ==="
	$(SURFER) $(REP_SIMPLE_VCD_FILE) &

# Clean repetition test files (both tests)
repetition-clean:
	@echo "=== Cleaning Repetition Test Files ==="
	rm -f $(REP_SIM_OUT) $(REP_VCD_FILE) $(REP_SIMPLE_SIM_OUT) $(REP_SIMPLE_VCD_FILE)

#==============================================================================
# REPETITION THRESHOLD TEST TARGETS
#==============================================================================

# Repetition threshold test simulation
repetition-threshold: $(REP_THRESH_SIM_OUT)
	@echo "=== Running Repetition Threshold Test ==="
	$(VVP) $(REP_THRESH_SIM_OUT)

# Compile repetition threshold test testbench
$(REP_THRESH_SIM_OUT): $(REP_THRESH_SOURCES) $(REP_THRESH_TESTBENCH)
	@echo "=== Compiling Repetition Threshold Test ==="
	$(IVERILOG) -g2012 -DSIMULATION -o $(REP_THRESH_SIM_OUT) $(REP_THRESH_SOURCES) $(REP_THRESH_TESTBENCH)

# View repetition threshold test waveforms
repetition-threshold-waves: $(REP_THRESH_VCD_FILE)
	@echo "=== Opening Repetition Threshold Test Waveforms ==="
	$(SURFER) $(REP_THRESH_VCD_FILE) &

# Clean repetition threshold test files
repetition-threshold-clean:
	@echo "=== Cleaning Repetition Threshold Test Files ==="
	rm -f $(REP_THRESH_SIM_OUT) $(REP_THRESH_VCD_FILE)

#==============================================================================
# REPETITION SIMPLE RUNS TEST TARGETS
#==============================================================================

# Repetition simple runs test simulation
repetition-simple-runs: $(REP_SIMPLE_SIM_OUT)
	@echo "=== Running Repetition Simple Runs Test ==="
	$(VVP) $(REP_SIMPLE_SIM_OUT)

# Compile repetition simple runs test testbench
$(REP_SIMPLE_SIM_OUT): $(REP_SIMPLE_SOURCES) $(REP_SIMPLE_TESTBENCH)
	@echo "=== Compiling Repetition Simple Runs Test ==="
	$(IVERILOG) -g2012 -DSIMULATION -o $(REP_SIMPLE_SIM_OUT) $(REP_SIMPLE_SOURCES) $(REP_SIMPLE_TESTBENCH)

# View repetition simple runs test waveforms
repetition-simple-runs-waves: $(REP_SIMPLE_VCD_FILE)
	@echo "=== Opening Repetition Simple Runs Test Waveforms ==="
	$(SURFER) $(REP_SIMPLE_VCD_FILE) &

# Clean repetition simple runs test files
repetition-simple-runs-clean:
	@echo "=== Cleaning Repetition Simple Runs Test Files ==="
	rm -f $(REP_SIMPLE_SIM_OUT) $(REP_SIMPLE_VCD_FILE)

#==============================================================================
# MARKOV TEST TARGETS
#==============================================================================

# Markov test simulation
markov: $(MARKOV_SIM_OUT)
	@echo "=== Running Markov Test ==="
	$(VVP) $(MARKOV_SIM_OUT)

# Compile markov test testbench
$(MARKOV_SIM_OUT): $(MARKOV_SOURCES) $(MARKOV_TESTBENCH)
	@echo "=== Compiling Markov Test ==="
	$(IVERILOG) -g2012 -DSIMULATION -o $(MARKOV_SIM_OUT) $(MARKOV_SOURCES) $(MARKOV_TESTBENCH)

# View markov test waveforms
markov-waves: $(MARKOV_VCD_FILE)
	@echo "=== Opening Markov Test Waveforms ==="
	$(SURFER) $(MARKOV_VCD_FILE) &

# Clean markov test files
markov-clean:
	@echo "=== Cleaning Markov Test Files ==="
	rm -f $(MARKOV_SIM_OUT) $(MARKOV_VCD_FILE)

#==============================================================================
# MARKOV WINDOWING TEST TARGETS
#==============================================================================

# Markov windowing test configuration
MARKOV_WINDOW_SOURCES = $(RTL_DIR)/entropy_markov_test.sv
MARKOV_WINDOW_TESTBENCH = tb_markov_windowing.v
MARKOV_WINDOW_SIM_OUT = tb_markov_windowing
MARKOV_WINDOW_VCD_FILE = markov_windowing.vcd

# Markov windowing test
markov-window: $(MARKOV_WINDOW_SIM_OUT)
	@echo "=== Running Markov Windowing Test ==="
	$(VVP) $(MARKOV_WINDOW_SIM_OUT)

# Compile markov windowing testbench
$(MARKOV_WINDOW_SIM_OUT): $(MARKOV_WINDOW_SOURCES) $(MARKOV_WINDOW_TESTBENCH)
	@echo "=== Compiling Markov Windowing Test ==="
	$(IVERILOG) -g2012 -DSIMULATION -o $(MARKOV_WINDOW_SIM_OUT) $(MARKOV_WINDOW_SOURCES) $(MARKOV_WINDOW_TESTBENCH)

# View markov windowing waveforms
markov-window-waves: $(MARKOV_WINDOW_VCD_FILE)
	@echo "=== Opening Markov Windowing Waveforms ==="
	$(SURFER) $(MARKOV_WINDOW_VCD_FILE) &

# Clean markov windowing files
markov-window-clean:
	@echo "=== Cleaning Markov Windowing Files ==="
	rm -f $(MARKOV_WINDOW_SIM_OUT) $(MARKOV_WINDOW_VCD_FILE)

#==============================================================================
# DECORRELATOR DISABLE TEST TARGETS
#==============================================================================

# Decorrelator disable test configuration
DECORR_DISABLE_SOURCES = $(RTL_DIR)/entropy_decorrelator.sv
DECORR_DISABLE_TESTBENCH = tb_decorrelator_disable.v
DECORR_DISABLE_SIM_OUT = tb_decorrelator_disable
DECORR_DISABLE_VCD_FILE = decorrelator_disable.vcd

# Decorrelator disable test simulation
decorr-disable: $(DECORR_DISABLE_SIM_OUT)
	@echo "=== Running Decorrelator Disable Bug Fix Test ==="
	$(VVP) $(DECORR_DISABLE_SIM_OUT)

# Compile decorrelator disable test testbench
$(DECORR_DISABLE_SIM_OUT): $(DECORR_DISABLE_SOURCES) $(DECORR_DISABLE_TESTBENCH)
	@echo "=== Compiling Decorrelator Disable Test ==="
	$(IVERILOG) -g2012 -DSIMULATION -o $(DECORR_DISABLE_SIM_OUT) $(DECORR_DISABLE_SOURCES) $(DECORR_DISABLE_TESTBENCH)

# View decorrelator disable test waveforms
decorr-disable-waves: $(DECORR_DISABLE_VCD_FILE)
	@echo "=== Opening Decorrelator Disable Test Waveforms ==="
	$(SURFER) $(DECORR_DISABLE_VCD_FILE) &

# Clean decorrelator disable test files
decorr-disable-clean:
	@echo "=== Cleaning Decorrelator Disable Test Files ==="
	rm -f $(DECORR_DISABLE_SIM_OUT) $(DECORR_DISABLE_VCD_FILE)

#==============================================================================
# INTEGRATED HEALTH TEST TARGETS
#==============================================================================

# Integrated health test simulation
health: $(HEALTH_SIM_OUT)
	@echo "=== Running Integrated Health Test ==="
	$(VVP) $(HEALTH_SIM_OUT)

# Compile integrated health test testbench
$(HEALTH_SIM_OUT): $(HEALTH_SOURCES) $(HEALTH_TESTBENCH)
	@echo "=== Compiling Integrated Health Test ==="
	$(IVERILOG) -g2012 -DSIMULATION -o $(HEALTH_SIM_OUT) $(HEALTH_SOURCES) $(HEALTH_TESTBENCH)

# View integrated health test waveforms
health-waves: $(HEALTH_VCD_FILE)
	@echo "=== Opening Integrated Health Test Waveforms ==="
	$(SURFER) $(HEALTH_VCD_FILE) &

# Clean integrated health test files
health-clean:
	@echo "=== Cleaning Integrated Health Test Files ==="
	rm -f $(HEALTH_SIM_OUT) $(HEALTH_VCD_FILE)

#==============================================================================
# SAMPLE CLOCK DIVIDER TEST TARGETS
#==============================================================================

# Sample clock divider test simulation
sclkdiv: $(SCLKDIV_SIM_OUT)
	@echo "=== Running Sample Clock Divider Test ==="
	$(VVP) $(SCLKDIV_SIM_OUT)

# Compile sample clock divider testbench
$(SCLKDIV_SIM_OUT): $(SCLKDIV_SOURCES) $(SCLKDIV_TESTBENCH)
	@echo "=== Compiling Sample Clock Divider Test ==="
	$(IVERILOG) -g2012 -DSIMULATION -o $(SCLKDIV_SIM_OUT) $(SCLKDIV_SOURCES) $(SCLKDIV_TESTBENCH)

# Full test compiles a second image: `ifdef FULL_TEST is a preprocessor gate, so
# the name has to reach iverilog as -D, not vvp as a plusarg.
sclkdiv-full: $(SCLKDIV_FULL_SIM_OUT)
	@echo "=== Running Full Sample Clock Divider Test (All 12 Generators) ==="
	$(VVP) $(SCLKDIV_FULL_SIM_OUT)

$(SCLKDIV_FULL_SIM_OUT): $(SCLKDIV_SOURCES) $(SCLKDIV_TESTBENCH)
	@echo "=== Compiling Full Sample Clock Divider Test ==="
	$(IVERILOG) -g2012 -DSIMULATION -DFULL_TEST -o $(SCLKDIV_FULL_SIM_OUT) $(SCLKDIV_SOURCES) $(SCLKDIV_TESTBENCH)

# View sample clock divider waveforms
sclkdiv-waves: $(SCLKDIV_VCD_FILE)
	@echo "=== Opening Sample Clock Divider Waveforms ==="
	$(SURFER) $(SCLKDIV_VCD_FILE) &

# Clean sample clock divider test files
sclkdiv-clean:
	@echo "=== Cleaning Sample Clock Divider Test Files ==="
	rm -f $(SCLKDIV_SIM_OUT) $(SCLKDIV_FULL_SIM_OUT) $(SCLKDIV_VCD_FILE)

#==============================================================================
# ENTROPY FIFO TEST TARGETS
#==============================================================================

# Entropy FIFO test simulation
fifo: $(FIFO_SIM_OUT)
	@echo "=== Running Entropy FIFO Test ==="
	$(VVP) $(FIFO_SIM_OUT)

# Compile entropy FIFO testbench
$(FIFO_SIM_OUT): $(FIFO_SOURCES) $(FIFO_TESTBENCH)
	@echo "=== Compiling Entropy FIFO Test ==="
	$(IVERILOG) -g2012 -DSIMULATION -o $(FIFO_SIM_OUT) $(FIFO_SOURCES) $(FIFO_TESTBENCH)

# View entropy FIFO waveforms
fifo-waves: $(FIFO_VCD_FILE)
	@echo "=== Opening Entropy FIFO Waveforms ==="
	$(SURFER) $(FIFO_VCD_FILE) &

# Clean entropy FIFO test files
fifo-clean:
	@echo "=== Cleaning Entropy FIFO Test Files ==="
	rm -f $(FIFO_SIM_OUT) $(FIFO_VCD_FILE)

#==============================================================================
# AXI4-LITE REGISTER INTERFACE TEST TARGETS (VERILATOR)
#==============================================================================

# AXI4-Lite register interface test simulation
axi4lite: $(AXI4LITE_EXECUTABLE)
	@echo "=== Running AXI4-Lite Register Interface Test ==="
	$(AXI4LITE_EXECUTABLE)

# Compile AXI4-Lite register interface testbench with Verilator
$(AXI4LITE_EXECUTABLE): $(AXI4LITE_SOURCES) $(AXI4LITE_TESTBENCH)
	@echo "=== Compiling AXI4-Lite Register Interface Test with Verilator ==="
	$(VERILATOR) -cc --exe --no-timing --build -j 0 \
		--Mdir $(AXI4LITE_OBJ_DIR) \
		--top-module entropy_source \
		-Wno-LATCH -Wno-UNOPTFLAT -Wno-TIMESCALEMOD -Wno-UNUSEDSIGNAL \
		-Wno-UNUSEDPARAM -Wno-CMPCONST -Wno-WIDTHEXPAND -Wno-MULTIDRIVEN \
		$(AXI4LITE_SOURCES) $(AXI4LITE_TESTBENCH)

# View AXI4-Lite register interface waveforms
axi4lite-waves: $(AXI4LITE_VCD_FILE)
	@echo "=== Opening AXI4-Lite Test Waveforms ==="
	$(SURFER) $(AXI4LITE_VCD_FILE) &

# Clean AXI4-Lite register interface test files
axi4lite-clean:
	@echo "=== Cleaning AXI4-Lite Test Files ==="
	rm -rf $(AXI4LITE_OBJ_DIR) $(AXI4LITE_VCD_FILE)

#==============================================================================
# BYTE STREAM HEALTH TEST TARGETS
#==============================================================================

# Repetition Test Byte Stream configuration
REP_BS_SOURCES = $(RTL_DIR)/entropy_repetition_test_byte_stream.sv
REP_BS_TESTBENCH = tb_repetition_test_byte_stream.v
REP_BS_SIM_OUT = tb_repetition_test_byte_stream
REP_BS_VCD_FILE = repetition_test_byte_stream.vcd

# Markov Test Byte Stream configuration
MARKOV_BS_SOURCES = $(RTL_DIR)/entropy_markov_test_byte_stream.sv
MARKOV_BS_TESTBENCH = tb_markov_test_byte_stream.v
MARKOV_BS_SIM_OUT = tb_markov_test_byte_stream
MARKOV_BS_VCD_FILE = markov_test_byte_stream.vcd

# Repetition test byte stream simulation
repetition-bs: $(REP_BS_SIM_OUT)
	@echo "=== Running Repetition Test Byte Stream ==="
	$(VVP) $(REP_BS_SIM_OUT)

$(REP_BS_SIM_OUT): $(REP_BS_SOURCES) $(REP_BS_TESTBENCH)
	@echo "=== Compiling Repetition Test Byte Stream ==="
	$(IVERILOG) -g2012 -DSIMULATION -o $(REP_BS_SIM_OUT) $(REP_BS_SOURCES) $(REP_BS_TESTBENCH)

repetition-bs-clean:
	@echo "=== Cleaning Repetition Test Byte Stream Files ==="
	rm -f $(REP_BS_SIM_OUT) $(REP_BS_VCD_FILE)

# Markov test byte stream simulation
markov-bs: $(MARKOV_BS_SIM_OUT)
	@echo "=== Running Markov Test Byte Stream ==="
	$(VVP) $(MARKOV_BS_SIM_OUT)

$(MARKOV_BS_SIM_OUT): $(MARKOV_BS_SOURCES) $(MARKOV_BS_TESTBENCH)
	@echo "=== Compiling Markov Test Byte Stream ==="
	$(IVERILOG) -g2012 -DSIMULATION -o $(MARKOV_BS_SIM_OUT) $(MARKOV_BS_SOURCES) $(MARKOV_BS_TESTBENCH)

markov-bs-clean:
	@echo "=== Cleaning Markov Test Byte Stream Files ==="
	rm -f $(MARKOV_BS_SIM_OUT) $(MARKOV_BS_VCD_FILE)

#==============================================================================
# VERILATOR LINT TARGETS
#==============================================================================

# Verilator lint check for full entropy_source component
verilator-lint: $(VERILATOR_FILELIST)
	@echo "=== Running Verilator Lint Check ==="
	$(VERILATOR) $(VERILATOR_FLAGS) -f $(VERILATOR_FILELIST)

# Create complete file list for Verilator compilation
$(VERILATOR_FILELIST): | $(VERILATOR_BUILD_DIR)
	@echo "=== Creating Verilator File List ==="
	@echo "// Entropy Source Complete File List for Verilator" > $@
	@echo "// All files required for successful compilation" >> $@
	@echo "" >> $@
	@echo "// Register package and RTL (must come first)" >> $@
	@echo "$(REG_RTL_DIR)/entropy_source_reg_pkg.sv" >> $@
	@echo "$(REG_RTL_DIR)/entropy_source_reg.sv" >> $@
	@echo "" >> $@
	@echo "// Package" >> $@
	@echo "$(RTL_DIR)/entropy_source_pkg.sv" >> $@
	@echo "" >> $@
	@echo "// Generic cells (primitives)" >> $@
	@printf "%s\n" $(COMMON_RTL) >> $@
	@echo "" >> $@
	@echo "// RTL modules (in dependency order)" >> $@
	@echo "$(RTL_DIR)/entropy_ring_oscillator.sv" >> $@
	@echo "$(RTL_DIR)/entropy_noise_source.sv" >> $@
	@echo "$(RTL_DIR)/entropy_sampler_clocks.sv" >> $@
	@echo "$(RTL_DIR)/gf_muladd.sv" >> $@
	@echo "$(RTL_DIR)/entropy_generator.sv" >> $@
	@echo "$(RTL_DIR)/entropy_generator_complex.sv" >> $@
	@echo "$(RTL_DIR)/entropy_decorrelator.sv" >> $@
	@echo "$(RTL_DIR)/entropy_fifo.sv" >> $@
	@echo "" >> $@
	@echo "// Health test modules" >> $@
	@echo "$(RTL_DIR)/entropy_repetition_test.sv" >> $@
	@echo "$(RTL_DIR)/entropy_adaptive_proportion_test.sv" >> $@
	@echo "$(RTL_DIR)/entropy_markov_test.sv" >> $@
	@echo "$(RTL_DIR)/entropy_health_test.sv" >> $@
	@echo "" >> $@
	@echo "// Byte stream health test modules" >> $@
	@echo "$(RTL_DIR)/entropy_repetition_test_byte_stream.sv" >> $@
	@echo "$(RTL_DIR)/entropy_markov_test_byte_stream.sv" >> $@
	@echo "$(RTL_DIR)/entropy_health_test_byte_stream.sv" >> $@
	@echo "" >> $@
	@echo "// Support modules" >> $@
	@echo "$(RTL_DIR)/entropy_rosc_tune_fsm.sv" >> $@
	@echo "$(RTL_DIR)/entropy_debug_monitor.sv" >> $@
	@echo "" >> $@
	@echo "// Top-level module" >> $@
	@echo "$(RTL_DIR)/entropy_source.sv" >> $@

# Create Verilator build directory
$(VERILATOR_BUILD_DIR):
	mkdir -p $(VERILATOR_BUILD_DIR)

# Verilator C++ code generation test
verilator-cpp: $(VERILATOR_FILELIST)
	@echo "=== Testing Verilator C++ Code Generation ==="
	$(VERILATOR) -cc --no-timing -Wall -Wno-fatal --top-module entropy_source -f $(VERILATOR_FILELIST)

# Comprehensive Verilator verification (using backup script)
verilator-verify:
	@echo "=== Running Comprehensive Verilator Verification ==="
	@if [ -f "$(VERILATOR_BACKUP_SCRIPT)" ]; then \
		./$(VERILATOR_BACKUP_SCRIPT); \
	else \
		echo "Error: $(VERILATOR_BACKUP_SCRIPT) not found"; \
		exit 1; \
	fi

# Clean Verilator files
verilator-clean:
	@echo "=== Cleaning Verilator Files ==="
	rm -rf $(VERILATOR_BUILD_DIR) obj_dir

#==============================================================================
# COMBINED TARGETS
#==============================================================================

# Run all testbenches
test: ring debug repetition markov health fifo axi4lite
	@echo "=== All Tests Complete ==="

# Run all byte stream testbenches
test-bs: repetition-bs markov-bs
	@echo "=== All Byte Stream Tests Complete ==="

# View all waveforms
waves: ring-waves debug-waves tune-fsm-correct-waves repetition-waves repetition-threshold-waves repetition-simple-runs-waves markov-waves markov-window-waves decorr-disable-waves health-waves fifo-waves axi4lite-waves

# Clean all generated files
clean: ring-clean debug-clean sclkdiv-clean tune-fsm-correct-clean repetition-clean repetition-threshold-clean repetition-simple-runs-clean markov-clean markov-window-clean decorr-disable-clean health-clean fifo-clean axi4lite-clean repetition-bs-clean markov-bs-clean verilator-clean
	@echo "=== All Files Cleaned ==="

#==============================================================================
# HELP TARGET
#==============================================================================

help:
	@echo "================================================================================"
	@echo "                     ENTROPY COMPONENT TEST SUITE"
	@echo "================================================================================"
	@echo ""
	@echo "OVERVIEW:"
	@echo "  This Makefile provides testing for individual entropy generation components"
	@echo "  using the iverilog open-source simulator."
	@echo ""
	@echo "QUICK START:"
	@echo "  make ring             - Test ring oscillator and noise source"
	@echo "  make ring-smoke       - Check that ring oscillation advances simulation time"
	@echo "  make debug            - Test debug monitor"
	@echo "  make sclkdiv          - Test sample clock divider (3 generators, quick)"
	@echo "  make sclkdiv-full     - Test sample clock divider (all 12 generators)"
	@echo "  make tune-fsm-correct - Test tune FSM (rising edge only health error detection)"
	@echo "  make repetition      - Test repetition count health test"
	@echo "  make markov          - Test Markov chain health test"
	@echo "  make markov-window   - Test Markov counter windowing/scaling mechanism"
	@echo "  make health          - Test integrated health test module"
	@echo "  make fifo            - Test entropy FIFO (normal and churning modes)"
	@echo "  make axi4lite        - Test AXI4-Lite register interface (34 tests)"
	@echo "  make test            - Run all tests"
	@echo "  make clean           - Clean all generated files"
	@echo ""
	@echo "BYTE STREAM TESTS:"
	@echo "  make repetition-bs   - Test repetition count health test (byte stream)"
	@echo "  make markov-bs       - Test Markov chain health test (byte stream)"
	@echo "  make test-bs         - Run all byte stream tests"
	@echo ""
	@echo "VERILATOR VERIFICATION:"
	@echo "  make verilator-lint   - Run Verilator lint check on full entropy_source"
	@echo "  make verilator-cpp    - Test Verilator C++ code generation"
	@echo "  make verilator-verify - Run comprehensive Verilator verification"
	@echo ""
	@echo "WAVEFORM VIEWING:"
	@echo "  make ring-waves             - View ring oscillator waveforms"
	@echo "  make debug-waves            - View debug monitor waveforms"
	@echo "  make sclkdiv-waves          - View sample clock divider waveforms"
	@echo "  make tune-fsm-correct-waves - View tune FSM waveforms"
	@echo "  make repetition-waves     - View repetition test waveforms"
	@echo "  make markov-waves         - View Markov test waveforms"
	@echo "  make markov-window-waves  - View Markov windowing test waveforms"
	@echo "  make health-waves         - View health test waveforms"
	@echo "  make fifo-waves           - View entropy FIFO waveforms"
	@echo "  make axi4lite-waves       - View AXI4-Lite register interface waveforms"
	@echo "  make waves              - Open all waveform files"
	@echo ""
	@echo "CLEANING:"
	@echo "  make ring-clean             - Clean ring oscillator files"
	@echo "  make debug-clean            - Clean debug monitor files"
	@echo "  make tune-fsm-correct-clean - Clean tune FSM files"
	@echo "  make repetition-clean     - Clean repetition test files"
	@echo "  make markov-clean         - Clean Markov test files"
	@echo "  make markov-window-clean  - Clean Markov windowing test files"
	@echo "  make health-clean         - Clean health test files"
	@echo "  make fifo-clean           - Clean entropy FIFO files"
	@echo "  make axi4lite-clean       - Clean AXI4-Lite register interface files"
	@echo "  make clean              - Clean all files"
	@echo ""
	@echo "REQUIREMENTS:"
	@echo "  - iverilog: Icarus Verilog compiler and simulator"
	@echo "  - surfer: Waveform viewer (or substitute with gtkwave)"
	@echo "  - verilator: SystemVerilog lint checker and C++ simulation (optional)"
	@echo ""
	@echo "================================================================================"

.PHONY: all ring ring-smoke debug tune-fsm-correct repetition markov markov-window health fifo axi4lite test test-bs waves clean help
.PHONY: ring-waves ring-clean debug-waves debug-clean tune-fsm-correct-waves tune-fsm-correct-clean
.PHONY: repetition-waves repetition-clean markov-waves markov-clean markov-window-waves markov-window-clean
.PHONY: health-waves health-clean fifo-waves fifo-clean axi4lite-waves axi4lite-clean verilator-lint verilator-cpp verilator-verify verilator-clean
.PHONY: repetition-bs markov-bs
.PHONY: repetition-bs-clean markov-bs-clean