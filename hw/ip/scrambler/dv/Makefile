# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

#-----------------------------------------------------------------------------
# Makefile for Scrambler Testbenches (Verilator)
#
# Copyright 2026 Tenstorrent Inc.
#-----------------------------------------------------------------------------

RTL_DIR  = ../rtl
TB_DIR   = .
TEST_DIR = tests

VERILATOR       = verilator
# Generate C++ and Makefile from RTL; --exe includes user .cpp; no --build here
VERILATOR_FLAGS = --cc --exe -Wall --no-timing \
                  -Wno-UNOPTFLAT \
                  -CFLAGS "-I$(abspath $(TB_DIR))"

# macOS uses Apple ld which requires BSD-format archives.
# When GNU ar (from Homebrew binutils) is on PATH it creates GNU-format archives
# that Apple ld rejects ("archive member '/' not a mach-o file").
# Override AR to the system BSD ar for all sub-makes.
AR_OVERRIDE = AR=/usr/bin/ar

COMMON_RTL = $(RTL_DIR)/scrambler_pkg.sv \
             $(RTL_DIR)/scrambler_addr_tweak.sv \
             $(RTL_DIR)/scrambler_rotator.sv

RTL_512  = $(COMMON_RTL) $(RTL_DIR)/scrambler_512x32.sv
RTL_1024 = $(COMMON_RTL) $(RTL_DIR)/scrambler_1024x32.sv
RTL_2048 = $(COMMON_RTL) $(RTL_DIR)/scrambler_2048x32.sv
RTL_4096 = $(COMMON_RTL) $(RTL_DIR)/scrambler_4096x32.sv
RTL_8192 = $(COMMON_RTL) $(RTL_DIR)/scrambler_8192x32.sv

TB_COMMON = $(TB_DIR)/tb_scrambler_common.h

# Simulation binary paths (Verilator places binary inside Mdir)
SIM_512       = obj_dir_512/tb_scrambler_512x32
SIM_1024      = obj_dir_1024/tb_scrambler_1024x32
SIM_2048      = obj_dir_2048/tb_scrambler_2048x32
SIM_4096      = obj_dir_4096/tb_scrambler_4096x32
SIM_8192      = obj_dir_8192/tb_scrambler_8192x32

SIM_512_BW    = obj_dir_512_bw/tb_scrambler_512x32_bw
SIM_1024_BW   = obj_dir_1024_bw/tb_scrambler_1024x32_bw
SIM_2048_BW   = obj_dir_2048_bw/tb_scrambler_2048x32_bw
SIM_4096_BW   = obj_dir_4096_bw/tb_scrambler_4096x32_bw
SIM_8192_BW   = obj_dir_8192_bw/tb_scrambler_8192x32_bw

ALL_SIMS    = $(SIM_512)    $(SIM_1024)    $(SIM_2048)    $(SIM_4096)    $(SIM_8192)
ALL_SIMS_BW = $(SIM_512_BW) $(SIM_1024_BW) $(SIM_2048_BW) $(SIM_4096_BW) $(SIM_8192_BW)

.PHONY: all all_bw clean run run_all run_all_bw
.PHONY: run_512  run_1024  run_2048  run_4096  run_8192
.PHONY: run_512_bw run_1024_bw run_2048_bw run_4096_bw run_8192_bw
.DEFAULT_GOAL := help

# ---------------------------------------------------------------------------
# Default: build everything
# ---------------------------------------------------------------------------
all: $(ALL_SIMS) $(ALL_SIMS_BW)
	@echo "All testbenches built.  make run_all / make run_all_bw to execute."

all_bw: $(ALL_SIMS_BW)
	@echo "All BYTE_WISE=1 testbenches built."

# ---------------------------------------------------------------------------
# Word-mode (BYTE_WISE=0) build rules
# Two-step: verilator generates C++/Makefile, then make builds with BSD ar.
# ---------------------------------------------------------------------------
$(SIM_512): $(RTL_512) $(TB_COMMON) $(TEST_DIR)/tb_scrambler_512x32.cpp
	@echo "Building 512x32 BYTE_WISE=0..."
	$(VERILATOR) $(VERILATOR_FLAGS) \
	    --top-module scrambler_512x32 \
	    --Mdir obj_dir_512 -o tb_scrambler_512x32 \
	    $(RTL_512) $(TEST_DIR)/tb_scrambler_512x32.cpp
	$(MAKE) -C obj_dir_512 -f Vscrambler_512x32.mk $(AR_OVERRIDE) tb_scrambler_512x32

$(SIM_1024): $(RTL_1024) $(TB_COMMON) $(TEST_DIR)/tb_scrambler_1024x32.cpp
	@echo "Building 1024x32 BYTE_WISE=0..."
	$(VERILATOR) $(VERILATOR_FLAGS) \
	    --top-module scrambler_1024x32 \
	    --Mdir obj_dir_1024 -o tb_scrambler_1024x32 \
	    $(RTL_1024) $(TEST_DIR)/tb_scrambler_1024x32.cpp
	$(MAKE) -C obj_dir_1024 -f Vscrambler_1024x32.mk $(AR_OVERRIDE) tb_scrambler_1024x32

$(SIM_2048): $(RTL_2048) $(TB_COMMON) $(TEST_DIR)/tb_scrambler_2048x32.cpp
	@echo "Building 2048x32 BYTE_WISE=0..."
	$(VERILATOR) $(VERILATOR_FLAGS) \
	    --top-module scrambler_2048x32 \
	    --Mdir obj_dir_2048 -o tb_scrambler_2048x32 \
	    $(RTL_2048) $(TEST_DIR)/tb_scrambler_2048x32.cpp
	$(MAKE) -C obj_dir_2048 -f Vscrambler_2048x32.mk $(AR_OVERRIDE) tb_scrambler_2048x32

$(SIM_4096): $(RTL_4096) $(TB_COMMON) $(TEST_DIR)/tb_scrambler_4096x32.cpp
	@echo "Building 4096x32 BYTE_WISE=0..."
	$(VERILATOR) $(VERILATOR_FLAGS) \
	    --top-module scrambler_4096x32 \
	    --Mdir obj_dir_4096 -o tb_scrambler_4096x32 \
	    $(RTL_4096) $(TEST_DIR)/tb_scrambler_4096x32.cpp
	$(MAKE) -C obj_dir_4096 -f Vscrambler_4096x32.mk $(AR_OVERRIDE) tb_scrambler_4096x32

$(SIM_8192): $(RTL_8192) $(TB_COMMON) $(TEST_DIR)/tb_scrambler_8192x32.cpp
	@echo "Building 8192x32 BYTE_WISE=0..."
	$(VERILATOR) $(VERILATOR_FLAGS) \
	    --top-module scrambler_8192x32 \
	    --Mdir obj_dir_8192 -o tb_scrambler_8192x32 \
	    $(RTL_8192) $(TEST_DIR)/tb_scrambler_8192x32.cpp
	$(MAKE) -C obj_dir_8192 -f Vscrambler_8192x32.mk $(AR_OVERRIDE) tb_scrambler_8192x32

# ---------------------------------------------------------------------------
# Byte-wise (BYTE_WISE=1) build rules — override parameter with -G
# ---------------------------------------------------------------------------
$(SIM_512_BW): $(RTL_512) $(TB_COMMON) $(TEST_DIR)/tb_scrambler_512x32_bw.cpp
	@echo "Building 512x32 BYTE_WISE=1..."
	$(VERILATOR) $(VERILATOR_FLAGS) \
	    --top-module scrambler_512x32 -GBYTE_WISE=1 \
	    --Mdir obj_dir_512_bw -o tb_scrambler_512x32_bw \
	    $(RTL_512) $(TEST_DIR)/tb_scrambler_512x32_bw.cpp
	$(MAKE) -C obj_dir_512_bw -f Vscrambler_512x32.mk $(AR_OVERRIDE) tb_scrambler_512x32_bw

$(SIM_1024_BW): $(RTL_1024) $(TB_COMMON) $(TEST_DIR)/tb_scrambler_1024x32_bw.cpp
	@echo "Building 1024x32 BYTE_WISE=1..."
	$(VERILATOR) $(VERILATOR_FLAGS) \
	    --top-module scrambler_1024x32 -GBYTE_WISE=1 \
	    --Mdir obj_dir_1024_bw -o tb_scrambler_1024x32_bw \
	    $(RTL_1024) $(TEST_DIR)/tb_scrambler_1024x32_bw.cpp
	$(MAKE) -C obj_dir_1024_bw -f Vscrambler_1024x32.mk $(AR_OVERRIDE) tb_scrambler_1024x32_bw

$(SIM_2048_BW): $(RTL_2048) $(TB_COMMON) $(TEST_DIR)/tb_scrambler_2048x32_bw.cpp
	@echo "Building 2048x32 BYTE_WISE=1..."
	$(VERILATOR) $(VERILATOR_FLAGS) \
	    --top-module scrambler_2048x32 -GBYTE_WISE=1 \
	    --Mdir obj_dir_2048_bw -o tb_scrambler_2048x32_bw \
	    $(RTL_2048) $(TEST_DIR)/tb_scrambler_2048x32_bw.cpp
	$(MAKE) -C obj_dir_2048_bw -f Vscrambler_2048x32.mk $(AR_OVERRIDE) tb_scrambler_2048x32_bw

$(SIM_4096_BW): $(RTL_4096) $(TB_COMMON) $(TEST_DIR)/tb_scrambler_4096x32_bw.cpp
	@echo "Building 4096x32 BYTE_WISE=1..."
	$(VERILATOR) $(VERILATOR_FLAGS) \
	    --top-module scrambler_4096x32 -GBYTE_WISE=1 \
	    --Mdir obj_dir_4096_bw -o tb_scrambler_4096x32_bw \
	    $(RTL_4096) $(TEST_DIR)/tb_scrambler_4096x32_bw.cpp
	$(MAKE) -C obj_dir_4096_bw -f Vscrambler_4096x32.mk $(AR_OVERRIDE) tb_scrambler_4096x32_bw

$(SIM_8192_BW): $(RTL_8192) $(TB_COMMON) $(TEST_DIR)/tb_scrambler_8192x32_bw.cpp
	@echo "Building 8192x32 BYTE_WISE=1..."
	$(VERILATOR) $(VERILATOR_FLAGS) \
	    --top-module scrambler_8192x32 -GBYTE_WISE=1 \
	    --Mdir obj_dir_8192_bw -o tb_scrambler_8192x32_bw \
	    $(RTL_8192) $(TEST_DIR)/tb_scrambler_8192x32_bw.cpp
	$(MAKE) -C obj_dir_8192_bw -f Vscrambler_8192x32.mk $(AR_OVERRIDE) tb_scrambler_8192x32_bw

# ---------------------------------------------------------------------------
# Run targets
# ---------------------------------------------------------------------------
run_512: $(SIM_512)
	@echo "Running 512x32 BYTE_WISE=0 simulation..."
	./$(SIM_512)

run_1024: $(SIM_1024)
	@echo "Running 1024x32 BYTE_WISE=0 simulation..."
	./$(SIM_1024)

run_2048: $(SIM_2048)
	@echo "Running 2048x32 BYTE_WISE=0 simulation..."
	./$(SIM_2048)

run_4096: $(SIM_4096)
	@echo "Running 4096x32 BYTE_WISE=0 simulation..."
	./$(SIM_4096)

run_8192: $(SIM_8192)
	@echo "Running 8192x32 BYTE_WISE=0 simulation..."
	./$(SIM_8192)

run_512_bw: $(SIM_512_BW)
	@echo "Running 512x32 BYTE_WISE=1 simulation..."
	./$(SIM_512_BW)

run_1024_bw: $(SIM_1024_BW)
	@echo "Running 1024x32 BYTE_WISE=1 simulation..."
	./$(SIM_1024_BW)

run_2048_bw: $(SIM_2048_BW)
	@echo "Running 2048x32 BYTE_WISE=1 simulation..."
	./$(SIM_2048_BW)

run_4096_bw: $(SIM_4096_BW)
	@echo "Running 4096x32 BYTE_WISE=1 simulation..."
	./$(SIM_4096_BW)

run_8192_bw: $(SIM_8192_BW)
	@echo "Running 8192x32 BYTE_WISE=1 simulation..."
	./$(SIM_8192_BW)

run_all: run_512 run_1024 run_2048 run_4096 run_8192
	@echo ""
	@echo "=========================================="
	@echo "All BYTE_WISE=0 simulations complete"
	@echo "=========================================="

run_all_bw: run_512_bw run_1024_bw run_2048_bw run_4096_bw run_8192_bw
	@echo ""
	@echo "=========================================="
	@echo "All BYTE_WISE=1 simulations complete"
	@echo "=========================================="

# Default run target (512x32 word mode).
run: run_512


# ---------------------------------------------------------------------------
# Clean
# ---------------------------------------------------------------------------
clean:
	rm -rf obj_dir_512 obj_dir_1024 obj_dir_2048 obj_dir_4096 obj_dir_8192
	rm -rf obj_dir_512_bw obj_dir_1024_bw obj_dir_2048_bw obj_dir_4096_bw obj_dir_8192_bw
	rm -f *.vcd

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------
help:
	@echo "Scrambler Testbench Makefile (Verilator)"
	@echo ""
	@echo "Build targets:"
	@echo "  all           - Build every word-mode and byte-wise testbench"
	@echo "  all_bw        - Build BYTE_WISE=1 testbenches only"
	@echo ""
	@echo "Run targets:"
	@echo "  run_all       - Run all BYTE_WISE=0 simulations"
	@echo "  run_all_bw    - Run all BYTE_WISE=1 simulations"
	@echo "  run_512       - Build+run 512x32   BYTE_WISE=0"
	@echo "  run_1024      - Build+run 1024x32  BYTE_WISE=0"
	@echo "  run_2048      - Build+run 2048x32  BYTE_WISE=0"
	@echo "  run_4096      - Build+run 4096x32  BYTE_WISE=0"
	@echo "  run_8192      - Build+run 8192x32  BYTE_WISE=0"
	@echo "  run_512_bw    - Build+run 512x32   BYTE_WISE=1"
	@echo "  run_1024_bw   - Build+run 1024x32  BYTE_WISE=1"
	@echo "  run_2048_bw   - Build+run 2048x32  BYTE_WISE=1"
	@echo "  run_4096_bw   - Build+run 4096x32  BYTE_WISE=1"
	@echo "  run_8192_bw   - Build+run 8192x32  BYTE_WISE=1"
	@echo ""
	@echo "Utility targets:"
	@echo "  clean         - Remove all generated build artifacts"
	@echo "  help          - Show this help"
