# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# OTBN Application Build Infrastructure
# Generic Makefile for building OTBN applications and generating C arrays
#
# Reusable Makefile flow built on the vendored OpenTitan OTBN infrastructure
# under vendor/lowRISC/opentitan/upstream/hw/ip/otbn/.
#
# Usage in test Makefile:
#   OTBN_APP_NAME = my_app
#   OTBN_APP_SRCS = src/file1.s src/file2.s
#   include $(OCAH_ROOT)/hw/sys/sep/dv/fw/tests/common_otbn/otbn_app.mk
#
# Outputs:
#   $(OTBN_APP_NAME)_otbn.c - Single C file with memory arrays and CRC values
#   $(OTBN_APP_NAME)_otbn.h - Header with extern declarations

ifndef OCAH_ROOT
$(error OCAH_ROOT is not set. Please run: export OCAH_ROOT=<path to the tt-oca checkout>)
endif



# Directory structure
COMMON_OTBN_DIR := $(OCAH_ROOT)/hw/sys/sep/dv/fw/tests/common_otbn
OTBN_IP_DIR    := $(OCAH_ROOT)/vendor/lowRISC/opentitan/upstream/hw/ip/otbn
OTBN_UTIL_DIR   := $(OTBN_IP_DIR)/util
OTBN_DATA_DIR   := $(OTBN_IP_DIR)/data

# Allow uv binary or python override
UV ?= uv
OTBN_PYTHON     ?= $(UV) --directory "$(OCAH_ROOT)" run --locked python3

# Build tools from vendored OpenTitan OTBN
OTBN_AS := $(OTBN_PYTHON) $(OTBN_UTIL_DIR)/otbn_as.py
# otbn_as.py passes -mabi=ilp32 but leaves the ISA to the assembler's default,
# which for a riscv64 binutils is 64-bit and rejects that ABI. OTBN's base ISA
# is RV32I; the M extension covers the mul/div in the crypto sources, and zicsr
# the csrrw that drives OTBN's flag/mod CSRs (binutils split zicsr out of the
# base ISA, so it has to be named explicitly).
OTBN_AS_FLAGS ?= -march=rv32im_zicsr
OTBN_OBJDUMP := $(OTBN_PYTHON) $(OTBN_UTIL_DIR)/otbn_objdump.py
# The toolchain container ships riscv64 binutils only; they cover 32-bit
# RISC-V targets, so ld is pointed at the elf32lriscv emulation explicitly.
RV32_PREFIX ?= riscv64-unknown-elf-
RV32_LD := $(RV32_PREFIX)ld -m elf32lriscv
RV32_OBJCOPY := $(RV32_PREFIX)objcopy
RV32_OBJDUMP := $(RV32_PREFIX)objdump

# Default values (can be overridden by including Makefile)
OTBN_APP_NAME ?= otbn_app
OTBN_SRC_DIR ?= otbn_src
OTBN_APP_SRCS ?= $(wildcard $(OTBN_SRC_DIR)/*.s)
OTBN_BUILD_DIR ?= otbn_build

# Check required variables
ifndef OTBN_APP_NAME
$(error OTBN_APP_NAME must be defined by including Makefile)
endif

ifeq ($(OTBN_APP_SRCS),)
$(error OTBN_APP_SRCS must be defined - no .s files found)
endif

# Output files (placed in build directory to keep source directory clean)
OTBN_APP_C_FILE := $(OTBN_BUILD_DIR)/$(OTBN_APP_NAME)_otbn.c
OTBN_APP_H_FILE := $(OTBN_BUILD_DIR)/$(OTBN_APP_NAME)_otbn.h

# Intermediate files
OTBN_APP_OBJS := $(patsubst %.s,$(OTBN_BUILD_DIR)/%.o,$(notdir $(OTBN_APP_SRCS)))
OTBN_APP_ELF := $(OTBN_BUILD_DIR)/$(OTBN_APP_NAME).elf
OTBN_APP_DISASM := $(OTBN_BUILD_DIR)/$(OTBN_APP_NAME).dis
OTBN_APP_SYMS := $(OTBN_BUILD_DIR)/$(OTBN_APP_NAME).sym
OTBN_APP_IMEM_BIN := $(OTBN_BUILD_DIR)/imem.bin
OTBN_APP_DMEM_BIN := $(OTBN_BUILD_DIR)/dmem.bin
OTBN_LINKER_SCRIPT := $(COMMON_OTBN_DIR)/otbn_app.ld

# Python environment for OTBN tools. The upstream helpers look for a
# riscv32-unknown-elf-* binutils; RV32_TOOL_<tool> overrides that lookup with
# the riscv64 binutils the toolchain container actually ships (they target
# 32-bit RISC-V too). The paths are resolved in the recipe shell, not by make,
# so they come from the PATH inside the container.
OTBN_PYTHON_ENV := PYTHONPATH="$(OTBN_UTIL_DIR):$(OTBN_IP_DIR):$(COMMON_OTBN_DIR):$$PYTHONPATH" \
	RV32_TOOL_AS="$$(command -v $(RV32_PREFIX)as)" \
	RV32_TOOL_LD="$$(command -v $(RV32_PREFIX)ld)" \
	RV32_TOOL_OBJCOPY="$$(command -v $(RV32_PREFIX)objcopy)" \
	RV32_TOOL_OBJDUMP="$$(command -v $(RV32_PREFIX)objdump)"

# Main targets
.PHONY: otbn-app otbn-app-clean

otbn-app: $(OTBN_APP_C_FILE) $(OTBN_APP_H_FILE) $(OTBN_APP_DISASM) $(OTBN_APP_SYMS)

# Create build directory
$(OTBN_BUILD_DIR):
	mkdir -p $(OTBN_BUILD_DIR)

# Assembly step: .s -> .o using OTBN assembler
# Primary rule for sources in configurable source directory
$(OTBN_BUILD_DIR)/%.o: $(OTBN_SRC_DIR)/%.s | $(OTBN_BUILD_DIR)
	@echo "Assembling OTBN: $<"
	$(OTBN_PYTHON_ENV) $(OTBN_AS) $(OTBN_AS_FLAGS) -o $@ $<


# Alternative assembly rule for sources not in standard directories
$(OTBN_BUILD_DIR)/%.o: %.s | $(OTBN_BUILD_DIR)
	@echo "Assembling OTBN: $<"
	$(OTBN_PYTHON_ENV) $(OTBN_AS) $(OTBN_AS_FLAGS) -o $@ $<

# Linking step: .o -> .elf using static linker script
$(OTBN_APP_ELF): $(OTBN_APP_OBJS) $(OTBN_LINKER_SCRIPT) | $(OTBN_BUILD_DIR)
	@echo "Linking OTBN application: $(OTBN_APP_NAME)"
	$(RV32_LD) --no-check-sections --no-warn-rwx-segments \
		-T $(OTBN_LINKER_SCRIPT) -o $@ $(OTBN_APP_OBJS)

# Disassembly generation: .elf -> .dis (with all sections and source intermixing)
$(OTBN_APP_DISASM): $(OTBN_APP_ELF)
	@echo "Generating OTBN disassembly"
	$(OTBN_PYTHON_ENV) $(OTBN_OBJDUMP) -D -S -x -h $< > $@

# Symbol table generation: .elf -> .sym
$(OTBN_APP_SYMS): $(OTBN_APP_ELF)
	@echo "Generating OTBN symbol table"
	$(RV32_OBJDUMP) -t $< > $@

# Binary extraction: .elf -> .bin files
$(OTBN_APP_IMEM_BIN): $(OTBN_APP_ELF)
	@echo "Extracting IMEM binary"
	$(RV32_OBJCOPY) -O binary --only-section=.text $< $@

$(OTBN_APP_DMEM_BIN): $(OTBN_APP_ELF)
	@echo "Extracting DMEM binary"
	$(RV32_OBJCOPY) -O binary --only-section=.data $< $@ || touch $@

# C file generation: .bin + .elf -> .c/.h with CRC calculation and symbol extraction
$(OTBN_APP_C_FILE) $(OTBN_APP_H_FILE): $(OTBN_APP_IMEM_BIN) $(OTBN_APP_DMEM_BIN) $(OTBN_APP_ELF)
	@echo "Generating C arrays, CRC values, and symbol addresses for $(OTBN_APP_NAME)"
	$(OTBN_PYTHON_ENV) $(OTBN_PYTHON) $(COMMON_OTBN_DIR)/generate_otbn_c.py \
		--app-name $(OTBN_APP_NAME) \
		--imem-bin $(OTBN_APP_IMEM_BIN) \
		--dmem-bin $(OTBN_APP_DMEM_BIN) \
		--output-c $(OTBN_APP_C_FILE) \
		--output-h $(OTBN_APP_H_FILE) \
		--elf-file $(OTBN_APP_ELF)

# Clean targets
otbn-app-clean:
	rm -rf $(OTBN_BUILD_DIR)

# Help target
.PHONY: otbn-app-help
otbn-app-help:
	@echo "OTBN Application Build Targets:"
	@echo "  otbn-app       - Build OTBN application, generate C files, disassembly, and symbols"
	@echo "  otbn-app-clean - Clean OTBN build artifacts"
	@echo ""
	@echo "Required Variables:"
	@echo "  OTBN_APP_NAME - Name of the OTBN application"
	@echo "  OTBN_APP_SRCS - List of .s source files"
	@echo ""
	@echo "Optional Variables:"
	@echo "  OTBN_SRC_DIR   - Source directory for OTBN assembly files (default: otbn_src)"
	@echo "  OTBN_BUILD_DIR - Build directory (default: otbn_build, generates C/H files here too)"
	@echo ""
	@echo "Generated Files (in build directory):"
	@echo "  $(OTBN_APP_NAME)_otbn.c - C array with IMEM/DMEM data"
	@echo "  $(OTBN_APP_NAME)_otbn.h - Header with symbols and declarations"
	@echo ""
	@echo "Include Path:"
	@echo "  Add -I$(OTBN_BUILD_DIR) to your C_FLAGS to include generated headers"
