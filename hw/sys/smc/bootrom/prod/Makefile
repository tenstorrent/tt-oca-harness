# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# SMC Production ROM - Standalone Makefile
# Self-contained build; does not include the shared compile.mk engine.
#
# Usage:
#   make                         # release build (default)
#   make BUILD_TYPE=debug        # debug build
#   make RISCV_TOOLCHAIN=/path/to/bin   # explicit toolchain override
#
# Requires: RISCV_TOOLCHAIN pointing at a picolibc-enabled
# riscv64-unknown-elf-* bin dir, or scripts/docker-run.sh.

# =============================================================================
# CONFIGURATION
# =============================================================================

PROJECT_NAME := smc_prod_rom
VERSION      := 1.0.0

BUILD_TYPE ?= release
TARGET     ?= prod_rom
CHIP_ARCH  ?= smc
# Set to 1 to enable simputs() debug prints in a release build
ENABLE_RELEASE_PRINTS ?= 0

EXEMEM := ROM
CONFIG := smc

# =============================================================================
# TOOLCHAIN CONFIGURATION
# =============================================================================

# RISCV_TOOLCHAIN may be set externally (env var or make argument) to the
# *directory* containing the toolchain binaries. When empty, compiler-dependent
# targets run through scripts/docker-run.sh run-here.
RISCV_TOOLCHAIN ?=
PROD_DIR  := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
OCAH_ROOT  ?= $(abspath $(PROD_DIR)/../../../../..)
OCAH_DOCKER_RUN := $(OCAH_ROOT)/scripts/docker-run.sh
UV = uv
PYTHON ?= $(UV) --project "$(OCAH_ROOT)" run --locked python3

ifneq ($(RISCV_TOOLCHAIN),)
  _TC_PREFIX := $(RISCV_TOOLCHAIN)/
else
  _TC_PREFIX :=
endif

GCC  := $(_TC_PREFIX)riscv64-unknown-elf-gcc
CXX  := $(_TC_PREFIX)riscv64-unknown-elf-g++
OC   := $(_TC_PREFIX)riscv64-unknown-elf-objcopy
OD   := $(_TC_PREFIX)riscv64-unknown-elf-objdump
SIZE := $(_TC_PREFIX)riscv64-unknown-elf-size
NM   := $(_TC_PREFIX)riscv64-unknown-elf-nm

# Architecture / ABI – same as hw/sys/smc/dv/fw/toolchain.mk
ARCH      := rv64imafdczicsr_zba_zbb_zbs_zifencei_zihpm
ABI       := lp64d
ARCHFLAGS := -march=$(ARCH) -mabi=$(ABI) -mtune=rocket

# =============================================================================
# DIRECTORY STRUCTURE
# =============================================================================

SRC_DIR    := $(PROD_DIR)/src
INCLUDE_DIR := $(PROD_DIR)/include
DRIVERS_DIR := $(PROD_DIR)/drivers
LIB_DIR    := $(PROD_DIR)/lib
BOOT_DIR   := $(PROD_DIR)/boot
LINKER_DIR := $(PROD_DIR)/linker
REG_DIR    := $(PROD_DIR)/registers
SCRIPTS_DIR := $(PROD_DIR)/scripts

BUILD_DIR  := $(PROD_DIR)/build
# DV-only ROM padding self-test builds (never a production image).
# ROM_PADDING_SELFTEST=1 jumps into EBREAK padding; =2 executes a generic EBREAK.
ROM_PADDING_SELFTEST ?=
# I3C_CORE selects which I3C block the ROM programs, so the two selections need
# separate output trees. Sharing one directory would let whichever selection ran
# last decide what the other links. The default selection keeps the unsuffixed
# path.
ifeq ($(I3C_CORE),chipsalliance)
    OUT_VARIANT := _hci
else
    OUT_VARIANT :=
endif
ifneq ($(ROM_PADDING_SELFTEST),)
    OUT_DIR := $(BUILD_DIR)/$(BUILD_TYPE)_padding_selftest$(ROM_PADDING_SELFTEST)$(OUT_VARIANT)
else
    OUT_DIR := $(BUILD_DIR)/$(BUILD_TYPE)$(OUT_VARIANT)
endif
OBJ_DIR    := $(OUT_DIR)/obj
BIN_DIR    := $(OUT_DIR)/bin
HEX_DIR    := $(OUT_DIR)/hex
DISASM_DIR := $(OUT_DIR)/disasm

# =============================================================================
# COMPILER FLAGS
# =============================================================================

ifeq ($(BUILD_TYPE),debug)
    OPTIMIZE    := -O0 -g3 -DDEBUG=1
    DEBUG_FLAGS := -ggdb3 -gdwarf-4
else ifeq ($(BUILD_TYPE),release)
    OPTIMIZE    := -Os -flto -fno-plt -fno-jump-tables -mtune=rocket \
                   -fno-math-errno -mstrict-align
    DEBUG_FLAGS := -g1
    ifeq ($(ENABLE_RELEASE_PRINTS),1)
        OPTIMIZE += -DDEBUG=1
    else
        OPTIMIZE += -DNDEBUG=1
    endif
else
    $(error Invalid BUILD_TYPE: $(BUILD_TYPE). Use 'debug' or 'release')
endif

WARNINGS := -Wall -Wextra -Werror \
            -Wstrict-prototypes \
            -Wno-address-of-packed-member \
            -Wno-missing-braces \
            -Wno-unused-parameter \
            -Wno-unused-variable

PICOLIBC_SPECS ?= picolibc.specs

CFLAGS := \
    -std=gnu17 \
    $(OPTIMIZE) \
    $(DEBUG_FLAGS) \
    $(WARNINGS) \
    $(ARCHFLAGS) \
    -ffunction-sections \
    -fdata-sections \
    -fno-common \
    -fmerge-all-constants \
    -fno-builtin \
    -mcmodel=medany \
    -mstrict-align \
    --specs=$(PICOLIBC_SPECS)

CXXFLAGS := \
    $(CFLAGS) \
    -std=gnu++17 \
    -fno-rtti \
    -fno-exceptions \
    -fno-unwind-tables \
    -fno-threadsafe-statics \
    -fno-use-cxa-atexit \
    -fno-weak

LINKER_SCRIPT := $(LINKER_DIR)/$(CHIP_ARCH)/smc_rom.ld

LDFLAGS := \
    $(OPTIMIZE) \
    $(ARCHFLAGS) \
    -Wl,--gc-sections \
    -Wl,-Map=$(OUT_DIR)/$(TARGET).map \
    -Wl,--print-memory-usage \
    -Wl,--as-needed \
    -Wl,--defsym=__stack_size=4K \
    -Wl,--defsym=__heap_size=2K \
    -Wl,--no-relax \
    -nostartfiles \
    --specs=$(PICOLIBC_SPECS) \
    -T $(LINKER_SCRIPT)

LIBFLAGS := \
    -lgcc \
    -Wl,--start-group \
    -Wl,--end-group

INCLUDES := \
    -I$(SRC_DIR) \
    -I$(INCLUDE_DIR) \
    -I$(DRIVERS_DIR)/include \
    -I$(LIB_DIR)/include \
    -I$(LINKER_DIR) \
    -I$(LINKER_DIR)/$(CHIP_ARCH) \
    -I$(REG_DIR)

EXTRA_DEFINES ?=

DEFINES := \
    -DPROJECT_NAME=\"$(PROJECT_NAME)\" \
    -DVERSION=\"$(VERSION)\" \
    -DTARGET_$(shell echo $(TARGET) | tr '[:lower:]' '[:upper:]') \
    -DCHIP_$(shell echo $(CHIP_ARCH) | tr '[:lower:]' '[:upper:]') \
    -DEXEMEM_ROM \
    -DCFG_$(shell echo $(CONFIG) | tr '[:lower:]' '[:upper:]') \
    $(EXTRA_DEFINES)

ifeq ($(BUILD_TYPE),debug)
    DEFINES += -DDEBUG=1 -DCFP_DBG_MSG=1
else ifeq ($(BUILD_TYPE),release)
    ifeq ($(ENABLE_RELEASE_PRINTS),1)
        DEFINES += -DDEBUG=1
    endif
endif

ifneq ($(ROM_PADDING_SELFTEST),)
    DEFINES += -DROM_PADDING_SELFTEST=$(ROM_PADDING_SELFTEST)
endif

# I3C_CORE=chipsalliance selects the OCA i3c-core (MIPI HCI) driver in
# i3c_hci_driver.c. The source is always compiled; the define enables its
# implementation while the default build uses the weak stubs or a platform
# implementation. The value is inherited from the environment so the DV build
# can propagate it here.
ifeq ($(I3C_CORE),chipsalliance)
    DEFINES += -DI3C_USE_HCI_CORE
endif

# =============================================================================
# SOURCE FILES
# =============================================================================

# Ignore ambient environment values; explicit make command-line values still win.
OCAH_FW_OVERLAY_SOURCES_smc :=
SMC_FW_OVERLAY_SOURCES := $(OCAH_FW_OVERLAY_SOURCES_smc)

MAIN_SOURCES   := $(wildcard $(SRC_DIR)/*.c) $(wildcard $(SRC_DIR)/*.cpp)
MAIN_ASM       := $(wildcard $(SRC_DIR)/*.S)
LIB_SOURCES    := $(wildcard $(LIB_DIR)/src/*.c)
BOOT_ASM       := $(wildcard $(BOOT_DIR)/*.S)
DRIVER_SOURCES := $(wildcard $(DRIVERS_DIR)/src/*.c)

ALL_C_SOURCES   := $(MAIN_SOURCES) $(LIB_SOURCES) $(DRIVER_SOURCES)
ALL_ASM_SOURCES := $(MAIN_ASM) $(BOOT_ASM)

MAIN_OBJS      := $(patsubst $(SRC_DIR)/%.c,$(OBJ_DIR)/src/%.o,$(filter %.c,$(MAIN_SOURCES)))
MAIN_OBJS      += $(patsubst $(SRC_DIR)/%.cpp,$(OBJ_DIR)/src/%.o,$(filter %.cpp,$(MAIN_SOURCES)))
MAIN_ASM_OBJS  := $(patsubst $(SRC_DIR)/%.S,$(OBJ_DIR)/src/%.o,$(MAIN_ASM))
LIB_OBJS       := $(patsubst $(LIB_DIR)/src/%.c,$(OBJ_DIR)/lib/%.o,$(LIB_SOURCES))
BOOT_ASM_OBJS  := $(patsubst $(BOOT_DIR)/%.S,$(OBJ_DIR)/boot/%.o,$(BOOT_ASM))
DRIVER_OBJS    := $(patsubst $(DRIVERS_DIR)/src/%.c,$(OBJ_DIR)/drivers/%.o,$(DRIVER_SOURCES))

ALL_OBJS := $(MAIN_OBJS) $(MAIN_ASM_OBJS) $(LIB_OBJS) $(BOOT_ASM_OBJS) $(DRIVER_OBJS)

SMC_FW_OVERLAY_OBJS := $(patsubst %.c,$(OBJ_DIR)/drivers/%.o, \
                           $(notdir $(SMC_FW_OVERLAY_SOURCES)))
ALL_OBJS += $(SMC_FW_OVERLAY_OBJS)

BUILD_FLAGS := SOURCE_OVERLAY=$(OCAH_FW_OVERLAY_SOURCES_smc)
FLAGS_STAMP := $(OUT_DIR)/.build_flags

# An object carries no record of the flags that produced it, and Make compares
# only timestamps, so changing ENABLE_RELEASE_PRINTS, EXTRA_DEFINES or the
# injected overlay sources over a populated build directory relinks objects from
# the previous configuration and reports success. Every object depends on this
# stamp, whose content is that configuration.
BUILD_CONFIG_SIG := $(strip $(DEFINES)) | $(strip $(notdir $(SMC_FW_OVERLAY_SOURCES)))
CONFIG_STAMP     := $(OUT_DIR)/.config.stamp
$(shell mkdir -p $(OUT_DIR) && \
    { [ "$$(cat $(CONFIG_STAMP) 2>/dev/null)" = '$(BUILD_CONFIG_SIG)' ] || \
        printf '%s' '$(BUILD_CONFIG_SIG)' > $(CONFIG_STAMP); })

ELF_FILE         := $(BIN_DIR)/$(TARGET).elf
BIN_FILE         := $(BIN_DIR)/$(TARGET).bin
HEX_FILE         := $(HEX_DIR)/$(TARGET).hex
PRELOAD_HEX_FILE := $(HEX_DIR)/$(TARGET).preload.hex
ECC_HEX_FILE     := $(HEX_DIR)/$(TARGET).ecc.hex
BIN64_FILE       := $(HEX_DIR)/$(TARGET).bin64
MAP_FILE         := $(OUT_DIR)/$(TARGET).map
DISASM_FILE      := $(DISASM_DIR)/$(TARGET).dis
SYM_FILE         := $(HEX_DIR)/$(TARGET).sym

# =============================================================================
# BUILD RULES
# =============================================================================

.PHONY: all toolchain-images toolchain-images-build pack-images
all:
	$(MAKE) toolchain-images
	$(MAKE) pack-images

toolchain-images:
	@if [ -n "$(RISCV_TOOLCHAIN)" ]; then \
	  $(MAKE) toolchain-images-build; \
	elif [ -x "$(OCAH_DOCKER_RUN)" ]; then \
	  echo "[bootrom] RISCV_TOOLCHAIN is unset; building in the OCAH toolchain container"; \
	  env -u RISCV_TOOLCHAIN -u RISCV_PREFIX -u MAKEFLAGS -u MFLAGS \
	    "$(OCAH_DOCKER_RUN)" run-here \
	    $(MAKE) -C "$(PROD_DIR)" \
	    BUILD_TYPE="$(BUILD_TYPE)" TARGET="$(TARGET)" CHIP_ARCH="$(CHIP_ARCH)" \
	    ENABLE_RELEASE_PRINTS="$(ENABLE_RELEASE_PRINTS)" \
	    ROM_PADDING_SELFTEST="$(ROM_PADDING_SELFTEST)" I3C_CORE="$(I3C_CORE)" \
	    EXTRA_DEFINES="$(EXTRA_DEFINES)" \
	    OCAH_FW_OVERLAY_SOURCES_smc="$(OCAH_FW_OVERLAY_SOURCES_smc)" \
	    RISCV_PREFIX=riscv64-unknown-elf- toolchain-images-build; \
	else \
	  echo "error: scripts/docker-run.sh is required when RISCV_TOOLCHAIN is unset" >&2; \
	  exit 1; \
	fi

toolchain-images-build: info $(ELF_FILE) $(BIN_FILE) $(HEX_FILE) \
     $(DISASM_FILE) $(SYM_FILE) size

pack-images:
	@test -f "$(BIN_FILE)" && test -f "$(HEX_FILE)" || { \
	  echo "error: ROM toolchain images are missing; run 'make toolchain-images' first" >&2; \
	  exit 1; \
	}
	@echo "PRELOAD $(PRELOAD_HEX_FILE)"
	@$(PYTHON) $(SCRIPTS_DIR)/update_smc_hex_to_preload_addr.py \
	    $(HEX_FILE) --out_file $(PRELOAD_HEX_FILE)
	@echo "ECC $(ECC_HEX_FILE)"
	@$(PYTHON) $(SCRIPTS_DIR)/gen_64b_ecc.py $(BIN_FILE) $(ECC_HEX_FILE)
	@echo "BIN64 $(BIN64_FILE)"
	@$(PYTHON) $(SCRIPTS_DIR)/bin_to_64b.py \
	    --input $(BIN_FILE) --output $(BIN64_FILE)

.PHONY: info
info:
	@echo "=========================================="
	@echo "SMC Production ROM Build"
	@echo "=========================================="
	@echo "Project:    $(PROJECT_NAME) v$(VERSION)"
	@echo "Target:     $(TARGET)"
	@echo "Chip:       $(CHIP_ARCH)"
	@echo "Build Type: $(BUILD_TYPE)"
	@echo "Toolchain:  $(if $(RISCV_TOOLCHAIN),$(RISCV_TOOLCHAIN),(from PATH))"
	@echo "Output:     $(OUT_DIR)"
	@echo "=========================================="

$(OBJ_DIR) $(OBJ_DIR)/src $(OBJ_DIR)/lib $(OBJ_DIR)/boot $(OBJ_DIR)/drivers:
	@mkdir -p $@

$(BIN_DIR) $(HEX_DIR) $(DISASM_DIR):
	@mkdir -p $@

.PHONY: FORCE
FORCE:

$(FLAGS_STAMP): FORCE | $(OBJ_DIR)
	@echo '$(BUILD_FLAGS)' > "$@.tmp"
	@if ! cmp -s "$@.tmp" "$@" 2>/dev/null; then \
	  echo "  [build flags changed -> rebuilding objects]"; \
	  mv "$@.tmp" "$@"; \
	else \
	  rm "$@.tmp"; \
	fi

$(ALL_OBJS): $(FLAGS_STAMP)

# Header dependency tracking. Without it an incremental build keeps objects whose
# headers have since changed, so editing an address in smc_rom_defs.h leaves the
# old constant baked into the ROM and only a clean build shows the edit. That is
# especially easy to miss for the .S files, whose constants come entirely from
# headers. -MP emits phony targets so a deleted header does not wedge the build.
DEPFLAGS := -MMD -MP

$(OBJ_DIR)/src/%.o: $(SRC_DIR)/%.c $(CONFIG_STAMP) | $(OBJ_DIR)/src
	@echo "CC  $<"
	@$(GCC) $(CFLAGS) $(DEPFLAGS) $(INCLUDES) $(DEFINES) -c $< -o $@

$(OBJ_DIR)/src/%.o: $(SRC_DIR)/%.cpp $(CONFIG_STAMP) | $(OBJ_DIR)/src
	@echo "CXX $<"
	@$(CXX) $(CXXFLAGS) $(DEPFLAGS) $(INCLUDES) $(DEFINES) -c $< -o $@

$(OBJ_DIR)/src/%.o: $(SRC_DIR)/%.S $(CONFIG_STAMP) | $(OBJ_DIR)/src
	@echo "AS  $<"
	@$(GCC) $(CFLAGS) $(DEPFLAGS) $(INCLUDES) $(DEFINES) -c $< -o $@

$(OBJ_DIR)/lib/%.o: $(LIB_DIR)/src/%.c $(CONFIG_STAMP) | $(OBJ_DIR)/lib
	@echo "CC  $<"
	@$(GCC) $(CFLAGS) $(DEPFLAGS) $(INCLUDES) $(DEFINES) -c $< -o $@

$(OBJ_DIR)/boot/%.o: $(BOOT_DIR)/%.S $(CONFIG_STAMP) | $(OBJ_DIR)/boot
	@echo "AS  $<"
	@$(GCC) $(CFLAGS) $(DEPFLAGS) $(INCLUDES) $(DEFINES) -c $< -o $@

$(OBJ_DIR)/drivers/%.o: $(DRIVERS_DIR)/src/%.c $(CONFIG_STAMP) | $(OBJ_DIR)/drivers
	@echo "CC  $<"
	@$(GCC) $(CFLAGS) $(DEPFLAGS) $(INCLUDES) $(DEFINES) -c $< -o $@

# Compile rules for SMC_FW_OVERLAY_SOURCES, one per source so each object names
# its own path as a prerequisite. A single pattern rule cannot, and an object
# with no source prerequisite is compiled once and then never again, however the
# source changes.
define SMC_FW_OVERLAY_RULE
$(OBJ_DIR)/drivers/$(notdir $(basename $(1))).o: $(1) $(CONFIG_STAMP) | $(OBJ_DIR)/drivers
	@echo "CC (extra) $(1)"
	@$$(GCC) $$(CFLAGS) $$(DEPFLAGS) $$(INCLUDES) $$(DEFINES) -c $(1) -o $$@
endef
$(foreach src,$(SMC_FW_OVERLAY_SOURCES),$(eval $(call SMC_FW_OVERLAY_RULE,$(src))))

-include $(ALL_OBJS:.o=.d)

$(ELF_FILE): $(ALL_OBJS) $(LINKER_SCRIPT) | $(BIN_DIR)
	@echo "LD  $@"
	@$(GCC) $(LDFLAGS) $(ALL_OBJS) $(LIBFLAGS) -o $@

$(BIN_FILE): $(ELF_FILE) | $(BIN_DIR)
	@echo "BIN $@"
	@$(OC) -O binary $< $@

$(HEX_FILE): $(ELF_FILE) | $(HEX_DIR)
	@echo "HEX $@"
	@$(OC) -O verilog --verilog-data-width 8 $< $@

# Post-processing scripts live in scripts/ next to this Makefile.
$(PRELOAD_HEX_FILE): $(HEX_FILE) | $(HEX_DIR)
	@echo "PRELOAD $@"
	@$(PYTHON) $(SCRIPTS_DIR)/update_smc_hex_to_preload_addr.py $< --out_file $@

$(ECC_HEX_FILE): $(BIN_FILE) | $(HEX_DIR)
	@echo "ECC $@"
	@$(PYTHON) $(SCRIPTS_DIR)/gen_64b_ecc.py $< $@

$(BIN64_FILE): $(BIN_FILE) | $(HEX_DIR)
	@echo "BIN64 $@"
	@$(PYTHON) $(SCRIPTS_DIR)/bin_to_64b.py --input $< --output $@

# nm listing next to the images: the DV processor-state monitors symbolize
# retired PCs from it.
$(SYM_FILE): $(ELF_FILE) | $(HEX_DIR)
	@echo "SYM $@"
	@$(NM) -B -n $< > $@

# -d (code sections) not -D (all sections): binutils 2.44 objdump aborts on -D
# for this image's NOBITS/.stack layout, and disassembling data is noise anyway.
$(DISASM_FILE): $(ELF_FILE) | $(DISASM_DIR)
	@echo "DIS $@"
	@$(OD) -dCSsx $< > $@

# =============================================================================
# UTILITY TARGETS
# =============================================================================

.PHONY: size
size: $(ELF_FILE)
	@echo "=========================================="
	@echo "Size Information:"
	@echo "=========================================="
	@$(SIZE) --format=berkeley $<
	@$(SIZE) --format=sysv $< | grep -E "(\.text|\.data|\.bss|\.rodata|Total)"

.PHONY: memory
memory: $(ELF_FILE)
	@echo "=========================================="
	@echo "Memory Layout:"
	@echo "=========================================="
	@$(NM) --size-sort --print-size $< | tail -20

.PHONY: debug
debug:
	@$(MAKE) BUILD_TYPE=debug all

.PHONY: release
release:
	@$(MAKE) BUILD_TYPE=release all

.PHONY: clean
clean:
	@echo "Cleaning build artifacts..."
	@rm -rf $(BUILD_DIR)

.PHONY: distclean
distclean: clean

.PHONY: check-toolchain
check-toolchain:
	@echo "Checking RISC-V toolchain..."
	@$(GCC) --version | head -n1
	@$(OC) --version | head -n1

.PHONY: check
check: check-toolchain
	@echo "✓ Toolchain OK"
	@test -f "$(LINKER_SCRIPT)" && echo "✓ Linker script found" || (echo "✗ Linker script missing: $(LINKER_SCRIPT)"; exit 1)

.PHONY: help
help:
	@echo "SMC Production ROM Build System"
	@echo "Usage:"
	@echo "  make                         - release build"
	@echo "  make BUILD_TYPE=debug        - debug build"
	@echo "  make RISCV_TOOLCHAIN=/path   - explicit toolchain directory"
	@echo "  (unset RISCV_TOOLCHAIN uses scripts/docker-run.sh run-here)"
	@echo "  make clean                   - remove build/"
	@echo "  make check                   - validate build environment"

.PHONY: all toolchain-images toolchain-images-build pack-images info clean \
        distclean debug release size memory check check-toolchain help
