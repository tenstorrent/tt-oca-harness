# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Tenstorrent Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

VERILATOR = verilator

# Requires verilator (5.036 or newer) and g++ 13 or newer on PATH.

# Set OCH_ROOT to point to the parent of the git repository root (relative path)
# The jtag_stap test file expects paths relative to tb directory
export OCH_ROOT = ../../../../..

IPNAME = jtag_stap
IPDIR = ..
CONFIGDIR = $(IPDIR)/config

# Optimization for better performance; alternative is nothing for
# slower runtime (faster compiles) -O2 for faster runtime (slower
# compiles), or -O for balance.
VERILATOR_MAKE_FLAGS = OPT_FAST="-Os"

# Help target (default)
help:
	@echo "JTAG STAP IP Testbench Makefile"
	@echo "==============================="
	@echo ""
	@echo "Available targets:"
	@echo "  help        - Show this help message (default)"
	@echo "  all         - Clean and run STAP test"
	@echo "  stap-test   - Run JTAG STAP interface testbench"
	@echo "  run         - Alias for stap-test"
	@echo "  clean       - Clean build artifacts"
	@echo ""
	@echo "Examples:"
	@echo "  make              # Show this help"
	@echo "  make stap-test    # Run STAP test"
	@echo "  make run          # Run STAP test"
	@echo "  make clean all    # Clean and run test"

# Targets
.PHONY: help all clean stap-test run
all: clean stap-test

clean:
	ccache -C
	rm -rf *.log *.s *.hex *.dis *.size *.tbl irun* vcs* simv* .map *.map snapshots \
	verilator* *.exe obj* *.o ucli.key vc_hdrs.h csrc *.csv work \
	dataset.asdb  library.cfg vsimsa.cfg  riviera-build wave.asdb sim.vcd \
	stap-test-build *.vcd

############ Model Builds ###############################

stap-test-build: ../config/jtag_stap_test.f jtag_stap_tb.sv test_jtag_stap_tb.cpp
	$(VERILATOR) --cc --exe \
		--timing \
		--timescale 1ns/1ps \
		-f ../config/jtag_stap_test.f --top-module jtag_stap_tb \
		--trace \
		-Wall -Wno-fatal \
		-Wno-PINMISSING -Wno-UNUSEDSIGNAL -Wno-UNUSEDPARAM -Wno-WIDTHEXPAND -Wno-WIDTHTRUNC -Wno-BLKSEQ \
		test_jtag_stap_tb.cpp
	cp jtag_test_utils.h obj_dir/
	$(MAKE) -j -C obj_dir/ -f Vjtag_stap_tb.mk
	touch stap-test-build

############ TEST Simulation ###############################

stap-test: stap-test-build
	./obj_dir/Vjtag_stap_tb

run: stap-test

