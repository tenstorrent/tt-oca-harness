# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# Key Manager Application ROM - Standalone Makefile
# Self-contained build; does not include the shared compile.mk engine.
#
# Usage:
#   make                                  # build/rom_main.rom.parhex
#   make KM_BOOT_WIPE=0 KM_UNREC_WIPE=0   # boot and unrecoverable-fault SRAM wipe disabled
#   make BUILD_DIR=build/<variant>        # keep a variant's objects apart
#   make RISCV_TOOLCHAIN=/path/to/bin     # explicit toolchain override
#
# Requires: RISCV_TOOLCHAIN pointing at a picolibc-enabled
# riscv64-unknown-elf-* bin dir, or scripts/docker-run.sh. A caller already
# running inside the toolchain container uses the `build` target directly.

.DELETE_ON_ERROR:

PROD_DIR  := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
OCAH_ROOT ?= $(abspath $(PROD_DIR)/../../../../..)
OCAH_DOCKER_RUN := $(OCAH_ROOT)/scripts/docker-run.sh
# add_rom_parity.py uses the standard library only.
PYTHON ?= python3

# =============================================================================
# TOOLCHAIN
# =============================================================================

RISCV_TOOLCHAIN ?=
RISCV_PREFIX    ?= riscv64-unknown-elf-
_TC_PREFIX := $(if $(strip $(RISCV_TOOLCHAIN)),$(patsubst %/,%,$(RISCV_TOOLCHAIN))/)$(RISCV_PREFIX)

# gcc-ar indexes the -flto objects for the LTO plugin.
CC      := $(_TC_PREFIX)gcc
AR      := $(_TC_PREFIX)gcc-ar
OBJCOPY := $(_TC_PREFIX)objcopy
OBJDUMP := $(_TC_PREFIX)objdump
NM      := $(_TC_PREFIX)nm
SIZE    := $(_TC_PREFIX)size

include $(PROD_DIR)/toolchain.mk

# =============================================================================
# CONFIGURATION
# =============================================================================

KM_BOOT_WIPE  ?= 1
KM_UNREC_WIPE ?= 1

BUILD_DIR ?= build
override BUILD_DIR := $(abspath $(BUILD_DIR))

KM_INCLUDES := -I$(PROD_DIR)/include -I$(OCAH_ROOT)/hw/ip/key_manager/regs/gen/c
KM_DEFINES  := \
  -DROM_KM_BOOT_WIPE_DEFAULT=$(KM_BOOT_WIPE) \
  -DROM_KM_UNREC_WIPE_DEFAULT=$(KM_UNREC_WIPE)

LINK_DIR      := $(PROD_DIR)/link
LINKER_SCRIPT := $(LINK_DIR)/km_production.ld

# =============================================================================
# SOURCES AND OUTPUTS
# =============================================================================

# rom_isr.c links as an object, not from the archive: nothing references its
# rom_irq(), which overrides the weak stub in crt0.s, so an archive link would
# leave faults unserviced without a build error.
KM_ISR_SRC    := $(PROD_DIR)/drivers/rom_isr.c
KM_ENTRY_SRCS := $(PROD_DIR)/src/rom_main.c $(KM_ISR_SRC)
KM_LIB_C_SRCS := $(filter-out $(KM_ISR_SRC),$(sort $(wildcard $(PROD_DIR)/drivers/*.c)))
KM_LIB_ASM_SRCS := $(sort $(wildcard $(PROD_DIR)/startup/*.s)) $(sort $(wildcard $(PROD_DIR)/drivers/*.S))

OBJ_DIR := $(BUILD_DIR)/obj
KM_LIB_OBJS   := $(addprefix $(OBJ_DIR)/,$(addsuffix .o,$(basename $(notdir $(KM_LIB_C_SRCS) $(KM_LIB_ASM_SRCS)))))
KM_ENTRY_OBJS := $(addprefix $(OBJ_DIR)/,$(addsuffix .o,$(basename $(notdir $(KM_ENTRY_SRCS)))))
KM_ARCHIVE    := $(BUILD_DIR)/libkm_approm.a

# Make tracks header dependencies, not flags. Every object depends on this file,
# which is rewritten only when the flag set changes, so changing a knob such as
# KM_BOOT_WIPE rebuilds the objects instead of relinking stale ones.
KM_FLAGS_FILE := $(BUILD_DIR)/.flags
KM_FLAGS_SIG  := $(CC) $(KM_CFLAGS) $(KM_ASFLAGS) $(KM_INCLUDES) $(KM_DEFINES)

ROM_ELF    := $(BUILD_DIR)/rom_main.elf
ROM_MAP    := $(BUILD_DIR)/rom_main.map
ROM_DIS    := $(BUILD_DIR)/rom_main.dis
ROM_SYM    := $(BUILD_DIR)/rom_main.sym
ROM_HEX    := $(BUILD_DIR)/rom_main.rom.hex
ROM_PARHEX := $(BUILD_DIR)/rom_main.rom.parhex

# The physical KM ROM carries the whole image: vectors, code, constants and the
# .data load image.
ROM_HEX_SECTIONS := \
  --only-section=.text.reset --only-section=.text.irq_vec --only-section=.text.irq_handler \
  --only-section=.text --only-section=.rodata --only-section=.data

# =============================================================================
# BUILD RULES
# =============================================================================

.PHONY: all build
all:
	@if [ -n "$(RISCV_TOOLCHAIN)" ]; then \
	  $(MAKE) build; \
	elif [ -x "$(OCAH_DOCKER_RUN)" ]; then \
	  echo "[km_approm] RISCV_TOOLCHAIN is unset; building in the OCAH toolchain container"; \
	  env -u RISCV_TOOLCHAIN -u RISCV_PREFIX -u MAKEFLAGS -u MFLAGS \
	    "$(OCAH_DOCKER_RUN)" run-here \
	    $(MAKE) -C "$(PROD_DIR)" BUILD_DIR="$(BUILD_DIR)" \
	    KM_BOOT_WIPE="$(KM_BOOT_WIPE)" KM_UNREC_WIPE="$(KM_UNREC_WIPE)" \
	    PYTHON=python3 build; \
	else \
	  echo "error: scripts/docker-run.sh is required when RISCV_TOOLCHAIN is unset" >&2; \
	  exit 1; \
	fi

build: $(ROM_PARHEX) $(ROM_SYM) $(ROM_DIS)
	@$(SIZE) $(ROM_ELF)

$(BUILD_DIR) $(OBJ_DIR):
	@mkdir -p $@

.PHONY: FORCE
FORCE:

$(KM_FLAGS_FILE): FORCE | $(BUILD_DIR)
	@if [ "$$(cat $@ 2>/dev/null)" != '$(KM_FLAGS_SIG)' ]; then \
	  printf '%s' '$(KM_FLAGS_SIG)' > $@; \
	fi

DEPFLAGS := -MMD -MP

vpath %.c $(PROD_DIR)/drivers $(PROD_DIR)/src
vpath %.S $(PROD_DIR)/drivers
vpath %.s $(PROD_DIR)/startup

$(OBJ_DIR)/%.o: %.c $(KM_FLAGS_FILE) | $(OBJ_DIR) check-toolchain
	$(CC) $(KM_CFLAGS) $(KM_INCLUDES) $(KM_DEFINES) $(DEPFLAGS) -c "$<" -o "$@"

$(OBJ_DIR)/%.o: %.S $(KM_FLAGS_FILE) | $(OBJ_DIR) check-toolchain
	$(CC) $(KM_ASFLAGS) $(KM_INCLUDES) $(KM_DEFINES) $(DEPFLAGS) -x assembler-with-cpp -c "$<" -o "$@"

$(OBJ_DIR)/%.o: %.s $(KM_FLAGS_FILE) | $(OBJ_DIR) check-toolchain
	$(CC) $(KM_ASFLAGS) $(KM_INCLUDES) $(KM_DEFINES) $(DEPFLAGS) -x assembler-with-cpp -c "$<" -o "$@"

-include $(KM_LIB_OBJS:.o=.d) $(KM_ENTRY_OBJS:.o=.d)

$(KM_ARCHIVE): $(KM_LIB_OBJS)
	@rm -f "$@"
	$(AR) rcs "$@" $(KM_LIB_OBJS)

$(ROM_ELF): $(KM_ENTRY_OBJS) $(KM_ARCHIVE) $(LINKER_SCRIPT) $(LINK_DIR)/km_sram_layout.ld
	$(CC) $(KM_LDFLAGS) -L"$(LINK_DIR)" -Wl,-Map="$(ROM_MAP)" -T "$(LINKER_SCRIPT)" \
	  $(KM_ENTRY_OBJS) "$(KM_ARCHIVE)" -o "$@"

$(ROM_HEX): $(ROM_ELF)
	$(OBJCOPY) -O verilog $< $(ROM_HEX_SECTIONS) "$@"

$(ROM_PARHEX): $(ROM_HEX) $(PROD_DIR)/scripts/add_rom_parity.py
	$(PYTHON) "$(PROD_DIR)/scripts/add_rom_parity.py" "$<" "$@"

$(ROM_SYM): $(ROM_ELF)
	$(NM) -B -n $< > "$@"

$(ROM_DIS): $(ROM_ELF)
	$(OBJDUMP) -dCSsx $< > "$@"

# A bare gcc on PATH is not enough: distro RISC-V toolchains often lack picolibc
# and only fail later with a spec-file error.
.PHONY: check-toolchain
check-toolchain:
	@command -v "$(CC)" >/dev/null 2>&1 || { \
	  echo "error: RISC-V toolchain not found (looking for '$(CC)')." >&2; \
	  echo "set RISCV_TOOLCHAIN=/path/to/bin, or run 'make' (not 'make build') to use the container" >&2; \
	  exit 1; \
	}
	@specs=$$("$(CC)" --print-file-name=$(KM_PICOLIBC_SPECS) 2>/dev/null); \
	if [ "$$specs" = "$(KM_PICOLIBC_SPECS)" ] || [ ! -f "$$specs" ]; then \
	  echo "error: '$(CC)' cannot find $(KM_PICOLIBC_SPECS); this toolchain has no picolibc." >&2; \
	  exit 1; \
	fi

.PHONY: clean
clean:
	rm -rf "$(BUILD_DIR)"

.PHONY: help
help:
	@echo "Key Manager Application ROM Build"
	@echo "Usage:"
	@echo "  make                         - build rom_main (container unless RISCV_TOOLCHAIN is set)"
	@echo "  make build                   - build with the toolchain already in reach"
	@echo "  make KM_BOOT_WIPE=0          - disable the boot SRAM wipe"
	@echo "  make KM_UNREC_WIPE=0         - disable the unrecoverable-fault SRAM wipe"
	@echo "  make BUILD_DIR=<dir>         - output directory (default: build)"
	@echo "  make clean                   - remove BUILD_DIR"
