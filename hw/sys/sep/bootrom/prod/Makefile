# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

SHELL := /usr/bin/env
.SHELLFLAGS := bash -c
# SEP Boot ROM image build. BOOT_SPI_CONTROLLER_OT=0 uses integrator-supplied
# memory-mapped flash hooks; the open hooks report no controller. Requires a
# picolibc-enabled RISC-V toolchain or scripts/docker-run.sh.
RISCV_TOOLCHAIN ?=
RISCV_PREFIX ?= $(if $(wildcard $(RISCV_TOOLCHAIN)/riscv64-unknown-elf-gcc),riscv64-unknown-elf-,riscv-none-elf-)
GCC_PREFIX ?= $(if $(strip $(RISCV_TOOLCHAIN)),$(patsubst %/,%,$(RISCV_TOOLCHAIN))/$(patsubst %-,%,$(RISCV_PREFIX)),riscv64-unknown-elf)

PROD_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
SEP_ROOT := $(abspath $(PROD_DIR)/../..)
DV_ROOT  := $(SEP_ROOT)/dv

OCAH_ROOT := $(abspath $(SEP_ROOT)/../../..)

UV ?= uv
# Cap the wheel platform on older glibc hosts; an existing environment may
# otherwise retain an ABI-incompatible cryptography wheel.
MANIFEST_UV_PLATFORM := $(shell python3 -c 'import platform; libc, ver = platform.libc_ver(); parts = tuple(int(x) for x in ver.split(".")[:2]) if ver else (0, 0); machine = platform.machine(); print("" if libc != "glibc" or parts >= (2, 34) else f"{machine}-manylinux_2_28" if parts >= (2, 28) else f"{machine}-manylinux_2_17")' 2>/dev/null)
MANIFEST_UV_FLAGS := $(if $(MANIFEST_UV_PLATFORM),--python-platform $(MANIFEST_UV_PLATFORM) --reinstall-package cryptography,)
MANIFEST_PYTHON ?= $(UV) --project "$(OCAH_ROOT)" run --locked --group manifest $(MANIFEST_UV_FLAGS) python

# Read generated headers from the register flow to keep them aligned with the RTL.
# Ignore ambient overlay variables while preserving command-line overrides.
OCAH_FW_REG_OVERLAY_INCLUDE_DIRS_sep :=
OCAH_FW_REG_OVERLAY_INCLUDE_DIRS_smc :=
OCAH_FW_OVERLAY_SOURCES_sep :=
include $(OCAH_ROOT)/hw/common/dv/fw/reg_includes.mk
REG_INCLUDE_DIRS := $(call ocah_fw_reg_includes,sep) $(call ocah_fw_reg_includes,smc)

ROM_BASE  ?= 0x10040000
DCCM_BASE ?= 0xC0040000

# Scrub all DCCM because reset and explicit_memzero() can leave key material in stack temporaries.
DCCM_SCRUB_BYTES ?= 0x20000

# Disabled by default because ROM clearing precedes testbench SRAM preloading.
# Set 0x40000 to scrub all SEP SRAM.
SRAM_SCRUB_BYTES ?= 0

# ICCM execution is always allowed; set this to 0 to reject BL1 and warm-reset
# handlers in SRAM. The cold and warm paths must enforce the same region policy.
BL1_SRAM_EXEC_ENABLE ?= 1
# BL1 writes establish ECC only through its end; the default pads the remaining
# fetchable words. Full clearing also removes power-up residue but costs about 2M cycles.
ROM_ICCM_CLEAR_ENABLE ?= 1
ROM_ICCM_CLEAR_FULL ?= 0
PMP_ENABLE ?= 1

# Debug uses in-tree private test keys. Release accepts only out-of-tree public
# keys and rejects directories containing private keys.
BUILD_TYPE ?= debug
ifeq ($(filter $(BUILD_TYPE),debug release),)
$(error Invalid BUILD_TYPE: $(BUILD_TYPE). Use 'debug' or 'release')
endif

BOOT_SPI_CONTROLLER_OT ?= 1
BOOT_OT_SPI_USE_PIO ?= 0
BOOT_OT_SPI_PROFILE ?= 0

# Preserve command-line BUILD_DIR overrides and isolate release artifacts from debug builds.
ifeq ($(BUILD_TYPE),release)
BUILD_DIR ?= $(PROD_DIR)/build_release
else
BUILD_DIR ?= $(PROD_DIR)/build
endif
LINK_DIR  := $(PROD_DIR)/link
SRC_DIR   := $(PROD_DIR)/src
TOOLS_DIR := $(PROD_DIR)/tools
INCLUDE_DIR := $(PROD_DIR)/include

# Generate trust anchors from each RSA-3072 public modulus.
# Debug reads private test keys; release accepts only public keys from an
# out-of-tree directory so production private keys never enter source control.
GENERATE_KEY_DIGESTS := $(TOOLS_DIR)/generate_key_digests.py
SEP_ROM_RELEASE_SIGNING_KEYS_DIR ?= $(CURDIR)/release_signing_keys
ifeq ($(BUILD_TYPE),release)
SEP_ROM_KEYS_DIR  := $(SEP_ROM_RELEASE_SIGNING_KEYS_DIR)
SEP_ROM_KEY_FORM  := public
else
SEP_ROM_KEYS_DIR  := $(CURDIR)/tests/signing_keys
SEP_ROM_KEY_FORM  := private
endif
SEP_ROM_KEY_FILES := $(wildcard $(SEP_ROM_KEYS_DIR)/rsa_$(SEP_ROM_KEY_FORM)_key.rom_key*.pem)
KEY_DIGESTS_C     := $(BUILD_DIR)/key_digests.c

TT_OCA_MANIFEST_DIR := $(TOOLS_DIR)/tt-oca-manifest

ELF      := $(BUILD_DIR)/boot_rom.elf
VMEM     := $(BUILD_DIR)/boot_rom.vmem
ITCM_HEX := $(BUILD_DIR)/boot_rom.itcm.hex
DTCM_HEX := $(BUILD_DIR)/boot_rom.dtcm.hex

INSERT_SHA256 := $(TOOLS_DIR)/insert-rom-sha256.py
ELF_TO_VMEM   := $(TOOLS_DIR)/elf-to-vmem.py

BL1_TEST_DIR := $(DV_ROOT)/fw/tests/bl1_pass_test
BL1_TEST_BIN := $(BL1_TEST_DIR)/build/bl1_pass_test.bin
# SMC-SRAM preload base, encoded as a Verilog-hex address without a 0x prefix.
SMC_SRAM_BASE ?= 40060000
BIN_TO_SPI    := $(TOOLS_DIR)/bin_to_spi_preload.py

OBJS := $(BUILD_DIR)/vector.o $(BUILD_DIR)/rom_main.o $(BUILD_DIR)/rom_metadata.o \
	$(BUILD_DIR)/boot_straps.o $(BUILD_DIR)/pll_init.o \
	$(BUILD_DIR)/sep_spi.o $(BUILD_DIR)/sep_ot_spi.o $(BUILD_DIR)/sep_dma.o \
	$(BUILD_DIR)/oca_boot.o $(BUILD_DIR)/rom_handoff.o \
	$(BUILD_DIR)/rom_mem_clear.o $(BUILD_DIR)/status_ring.o \
	$(BUILD_DIR)/hmac_sha256.o $(BUILD_DIR)/measurement.o $(BUILD_DIR)/fuse_lock.o \
	$(BUILD_DIR)/lifecycle.o \
	$(BUILD_DIR)/rsa_verify.o $(BUILD_DIR)/otbn_driver.o \
	$(BUILD_DIR)/aes_driver.o $(BUILD_DIR)/kdf.o $(BUILD_DIR)/key_digests.o \
	$(BUILD_DIR)/sep_entropy.o \
	$(BUILD_DIR)/oca_platform.o \
	$(BUILD_DIR)/rsa_3072_app_otbn.o

# Built with warnings fatal but not linked: the Adams Bridge ML-DSA-87 driver, which
# no ROM path calls. Its host tests are under tests/host (make host-test).
CHECK_OBJS := $(BUILD_DIR)/abr_driver.o
$(CHECK_OBJS): CFLAGS += -Wall -Wextra -Werror

# Compile every validator source so new format support is not silently omitted.
# Keep its objects in a separate directory because the library and ROM both
# provide lifecycle.c; flattening the names would overwrite one object.
OCA_LIB_DIR  := $(TT_OCA_MANIFEST_DIR)/validators/oca/lib
OCA_LIB_SRCS := $(wildcard $(OCA_LIB_DIR)/*.c)
OCA_OBJ_DIR  := $(BUILD_DIR)/oca
OCA_LIB_OBJS := $(patsubst $(OCA_LIB_DIR)/%.c,$(OCA_OBJ_DIR)/%.o,$(OCA_LIB_SRCS))

# PQC enables OCAP geometry but not PQC signature verification; native PQC
# signatures remain unsupported. Disable it only to reduce ROM size.

# Disabling entropy bring-up creates a diagnostic build that cannot complete entropy-dependent secure boot.
SEP_ENTROPY_BRINGUP ?= 1

# These independent flags defer one-way locks to BL1: FIPS_LOCK protects
# entropy-source configuration, while EXT_TRNG_SRC_SEL_LOCK protects source
# selection. BL1 must apply every deferred lock before handing off.
SEP_ENTROPY_DEFER_FIPS_LOCK    ?= 0
SEP_ENTROPY_DEFER_SRC_SEL_LOCK ?= 0

OCA_SUPPORT_CLASSIC ?= 1
OCA_SUPPORT_PQC     ?= 1
OCA_TOC_MAX_IMAGES  ?= 32

OBJS += $(OCA_LIB_OBJS)

OTBN_APP_DIR := $(DV_ROOT)/fw/build/otbn/rsa_3072_app
OTBN_APP_C   := $(OTBN_APP_DIR)/rsa_3072_app_otbn.c

# Overlay sources must use absolute paths and provide strong definitions for the weak platform hooks.
SEP_FW_OVERLAY_SOURCES := $(OCAH_FW_OVERLAY_SOURCES_sep)
SEP_FW_OVERLAY_OBJS := $(patsubst %.c,$(BUILD_DIR)/%.o,$(notdir $(SEP_FW_OVERLAY_SOURCES)))
OBJS += $(SEP_FW_OVERLAY_OBJS)

# Spell out zifencei because binutils 2.38 and later reject fence.i without it.
CC_ABI   := -march=rv32im_zicsr_zifencei -mabi=ilp32

# DEBUG enables decoded security-state output through a real scratch CSR.
# STATUS_OUT() remains available in release builds.
ifeq ($(BUILD_TYPE),release)
BUILD_TYPE_DEFINES := -DNDEBUG=1
else
BUILD_TYPE_DEFINES := -DTEST_BUILD=1 -DDEBUG
endif
# Generated register-header assertions require picolibc.specs even in this freestanding build.
CFLAGS   := -Os -g -gdwarf-4 -ffreestanding -fno-builtin -fdata-sections -ffunction-sections -mno-relax \
-MMD -MP \
--specs=picolibc.specs \
	-I$(INCLUDE_DIR) -I$(BUILD_DIR) -I$(OTBN_APP_DIR) -I$(OCA_LIB_DIR) $(REG_INCLUDE_DIRS) \
	-DSEP_ENTROPY_BRINGUP=$(SEP_ENTROPY_BRINGUP) \
	-DSEP_ENTROPY_DEFER_FIPS_LOCK=$(SEP_ENTROPY_DEFER_FIPS_LOCK) \
	-DSEP_ENTROPY_DEFER_SRC_SEL_LOCK=$(SEP_ENTROPY_DEFER_SRC_SEL_LOCK) \
	-DOCA_SUPPORT_CLASSIC=$(OCA_SUPPORT_CLASSIC) -DOCA_SUPPORT_PQC=$(OCA_SUPPORT_PQC) \
	-DOCA_TOC_MAX_IMAGES=$(OCA_TOC_MAX_IMAGES) \
	-DDCCM_SCRUB_BYTES=$(DCCM_SCRUB_BYTES) -DSRAM_SCRUB_BYTES=$(SRAM_SCRUB_BYTES) \
	-DPMP_ENABLE=$(PMP_ENABLE) -DSEP_BL0 $(BUILD_TYPE_DEFINES) \
	-DROM_ICCM_CLEAR_ENABLE=$(ROM_ICCM_CLEAR_ENABLE) \
	-DROM_ICCM_CLEAR_FULL=$(ROM_ICCM_CLEAR_FULL) \
	-DBL1_SRAM_EXEC_ENABLE=$(BL1_SRAM_EXEC_ENABLE) \
	-DBOOT_SPI_CONTROLLER_OT=$(BOOT_SPI_CONTROLLER_OT) \
	-DBOOT_OT_SPI_USE_PIO=$(BOOT_OT_SPI_USE_PIO) \
	-DBOOT_OT_SPI_PROFILE=$(BOOT_OT_SPI_PROFILE) \
	$(CC_ABI)
ASFLAGS  := -x assembler-with-cpp -g -gdwarf-4 -mno-relax -I$(INCLUDE_DIR) $(REG_INCLUDE_DIRS) \
	-DDCCM_SCRUB_BYTES=$(DCCM_SCRUB_BYTES) -DPMP_ENABLE=$(PMP_ENABLE) \
	-DBL1_SRAM_EXEC_ENABLE=$(BL1_SRAM_EXEC_ENABLE) \
	$(CC_ABI)
LDFLAGS  := -nostdlib -Wl,--gc-sections -Wl,--no-relax -T $(LINK_DIR)/rom.ld $(CC_ABI)

ROM_ELF_SECTIONS := --only-section=.text --only-section=.text.* --only-section=.metadata --only-section=.metadata.* \
	--only-section=.rodata --only-section=.rodata.* --only-section=.srodata --only-section=.srodata.*
# Exclude .rodata: rebasing its ROM LMA by DCCM_BASE would wrap the address.
DTCM_ELF_SECTIONS := --only-section=.data --only-section=.data.* --only-section=.sdata --only-section=.sdata.* \
	--only-section=.bss --only-section=.bss.* --only-section=.sbss --only-section=.sbss.*

# Delete failed targets so a partially patched ELF cannot be reused as up to date.
.DELETE_ON_ERROR:

.PHONY: all clean bl1_test ensure-pack-deps toolchain-images toolchain-images-build \
        pio-toolchain-images debug release decrypt_negative_images

# Release builds must not emit flash images signed by private test keys.
ifeq ($(BUILD_TYPE),release)
all: toolchain-images
else
all: toolchain-images oca-images
endif

debug:
	@$(MAKE) BUILD_TYPE=debug all
release:
	@$(MAKE) BUILD_TYPE=release all

pio-toolchain-images:
	$(MAKE) BUILD_DIR=$(PROD_DIR)/build_pio BOOT_SPI_CONTROLLER_OT=1 BOOT_OT_SPI_USE_PIO=1 \
		toolchain-images

# Run compiler-dependent targets with an explicit RISCV_TOOLCHAIN or in the
# toolchain container. Generate Python-only artifacts on the host via uv.
OCAH_DOCKER_RUN := $(OCAH_ROOT)/scripts/docker-run.sh

# Generate key_digests.c on the host before entering the compiler container.
toolchain-images: key-digests
	@if [ -n "$(RISCV_TOOLCHAIN)" ]; then \
	  $(MAKE) toolchain-images-build; \
	elif [ -x "$(OCAH_DOCKER_RUN)" ]; then \
	  echo "[bootrom] RISCV_TOOLCHAIN is unset; building in the OCAH toolchain container"; \
	  env -u RISCV_TOOLCHAIN -u RISCV_PREFIX -u MAKEFLAGS -u MFLAGS \
	    "$(OCAH_DOCKER_RUN)" run-here \
	    $(MAKE) -C "$(CURDIR)" \
	    BUILD_DIR="$(BUILD_DIR)" ROM_BASE="$(ROM_BASE)" DCCM_BASE="$(DCCM_BASE)" \
	    DCCM_SCRUB_BYTES="$(DCCM_SCRUB_BYTES)" SRAM_SCRUB_BYTES="$(SRAM_SCRUB_BYTES)" \
	    ROM_ICCM_CLEAR_ENABLE="$(ROM_ICCM_CLEAR_ENABLE)" \
	    ROM_ICCM_CLEAR_FULL="$(ROM_ICCM_CLEAR_FULL)" \
	    BL1_SRAM_EXEC_ENABLE="$(BL1_SRAM_EXEC_ENABLE)" \
	    PMP_ENABLE="$(PMP_ENABLE)" BUILD_TYPE="$(BUILD_TYPE)" \
	    SEP_ENTROPY_BRINGUP="$(SEP_ENTROPY_BRINGUP)" \
	    SEP_ENTROPY_DEFER_FIPS_LOCK="$(SEP_ENTROPY_DEFER_FIPS_LOCK)" \
	    SEP_ENTROPY_DEFER_SRC_SEL_LOCK="$(SEP_ENTROPY_DEFER_SRC_SEL_LOCK)" \
	    OCA_SUPPORT_CLASSIC="$(OCA_SUPPORT_CLASSIC)" \
	    OCA_SUPPORT_PQC="$(OCA_SUPPORT_PQC)" OCA_TOC_MAX_IMAGES="$(OCA_TOC_MAX_IMAGES)" \
	    SEP_ROM_RELEASE_SIGNING_KEYS_DIR="$(SEP_ROM_RELEASE_SIGNING_KEYS_DIR)" \
	    BOOT_SPI_CONTROLLER_OT="$(BOOT_SPI_CONTROLLER_OT)" \
	    BOOT_OT_SPI_USE_PIO="$(BOOT_OT_SPI_USE_PIO)" \
	    BOOT_OT_SPI_PROFILE="$(BOOT_OT_SPI_PROFILE)" \
	    OCAH_FW_REG_OVERLAY_INCLUDE_DIRS_sep="$(OCAH_FW_REG_OVERLAY_INCLUDE_DIRS_sep)" \
	    OCAH_FW_REG_OVERLAY_INCLUDE_DIRS_smc="$(OCAH_FW_REG_OVERLAY_INCLUDE_DIRS_smc)" \
	    OCAH_FW_OVERLAY_SOURCES_sep="$(OCAH_FW_OVERLAY_SOURCES_sep)" \
	    RISCV_PREFIX=riscv64-unknown-elf- GCC_PREFIX=riscv64-unknown-elf \
	    toolchain-images-build; \
	else \
	  echo "error: scripts/docker-run.sh is required when RISCV_TOOLCHAIN is unset" >&2; \
	  exit 1; \
	fi

toolchain-images-build: $(VMEM) $(ITCM_HEX) $(DTCM_HEX) $(CHECK_OBJS) bl1_test

.PHONY: host-test
host-test:
	$(MAKE) -C $(PROD_DIR)/tests/host

$(BUILD_DIR):
	mkdir -p "$(BUILD_DIR)"

$(OCA_OBJ_DIR):
	mkdir -p "$(OCA_OBJ_DIR)"

# Track build flags because source timestamps alone cannot invalidate variant objects.
BUILD_FLAGS := CTRL_OT=$(BOOT_SPI_CONTROLLER_OT) USE_PIO=$(BOOT_OT_SPI_USE_PIO) \
	PROFILE=$(BOOT_OT_SPI_PROFILE) BUILD_TYPE=$(BUILD_TYPE) \
	PMP_ENABLE=$(PMP_ENABLE) \
	BL1_SRAM_EXEC=$(BL1_SRAM_EXEC_ENABLE) ICCM_ENABLE=$(ROM_ICCM_CLEAR_ENABLE) \
	ICCM_FULL=$(ROM_ICCM_CLEAR_FULL) \
	DCCM_SCRUB=$(DCCM_SCRUB_BYTES) SRAM_SCRUB=$(SRAM_SCRUB_BYTES) \
	REG_OVERLAY=$(OCAH_FW_REG_OVERLAY_INCLUDE_DIRS_sep) \
	SMC_REG_OVERLAY=$(OCAH_FW_REG_OVERLAY_INCLUDE_DIRS_smc) \
	SOURCE_OVERLAY=$(OCAH_FW_OVERLAY_SOURCES_sep) \
	OCA_CLASSIC=$(OCA_SUPPORT_CLASSIC) OCA_PQC=$(OCA_SUPPORT_PQC) \
	OCA_TOC_MAX=$(OCA_TOC_MAX_IMAGES) ENTROPY=$(SEP_ENTROPY_BRINGUP) \
	DEFER_FIPS=$(SEP_ENTROPY_DEFER_FIPS_LOCK) \
	DEFER_SRCSEL=$(SEP_ENTROPY_DEFER_SRC_SEL_LOCK) \
	KEYS_DIR=$(SEP_ROM_KEYS_DIR)
FLAGS_STAMP := $(BUILD_DIR)/.build_flags

.PHONY: FORCE
FORCE:

# Update the stamp mtime only when flags change, avoiding rebuilds for identical configurations.
$(FLAGS_STAMP): FORCE | $(BUILD_DIR)
	@echo '$(BUILD_FLAGS)' > "$@.tmp"
	@if ! cmp -s "$@.tmp" "$@" 2>/dev/null; then \
	  echo "  [build flags changed -> rebuilding objects]"; \
	  mv "$@.tmp" "$@"; \
	else \
	  rm "$@.tmp"; \
	fi

$(OBJS) $(CHECK_OBJS): $(FLAGS_STAMP)

# Header dependencies prevent objects compiled with incompatible shared
# structure layouts from being linked together.
-include $(OBJS:.o=.d) $(CHECK_OBJS:.o=.d)

# Extract the SMC base into a macro-only header because vector.S cannot include C declarations.
SMC_BASE_CONFIG_H := $(firstword $(wildcard $(addsuffix /smc_base_config.h,$(patsubst -I%,%,$(REG_INCLUDE_DIRS)))))
SMC_LOCAL_BASE_H := $(BUILD_DIR)/smc_local_base.h
$(SMC_LOCAL_BASE_H): $(SMC_BASE_CONFIG_H) $(FLAGS_STAMP) | $(BUILD_DIR)
	grep -E '^#define SMC_BASE_CONFIG__LOCAL_BASE__BASE_reset 0x[0-9a-fA-F]+$$' "$<" > "$@"

$(OBJS): $(SMC_LOCAL_BASE_H)

$(BUILD_DIR)/bl0_version.h: | $(BUILD_DIR)
	echo '#define BL0_VERSION "oss-nonsecure"' > "$@"

# Rebuild trust anchors when key files, directory, or key form changes.
# Regeneration is host-only, so key inputs use a separate stamp.
KEY_INPUTS_STAMP := $(BUILD_DIR)/.key_inputs
$(KEY_INPUTS_STAMP): FORCE | $(BUILD_DIR)
	@echo '$(SEP_ROM_KEYS_DIR) form=$(SEP_ROM_KEY_FORM)' > "$@.tmp"
	@if ! cmp -s "$@.tmp" "$@" 2>/dev/null; then mv "$@.tmp" "$@"; else rm "$@.tmp"; fi

$(SEP_ROM_KEY_FILES): ;
$(KEY_DIGESTS_C): $(GENERATE_KEY_DIGESTS) $(SEP_ROM_KEY_FILES) $(KEY_INPUTS_STAMP) | $(BUILD_DIR)
	@$(MANIFEST_PYTHON) -c 'import cryptography' 2>/dev/null || { \
	  echo "ERROR: cannot generate $@ here."; \
	  echo "       Key digests are read from PEM files with python3-cryptography,"; \
	  echo "       Generate them on the host first:"; \
	  echo "         make -C $(CURDIR) BUILD_DIR=$(BUILD_DIR) BUILD_TYPE=$(BUILD_TYPE) key-digests"; \
	  exit 1; }
	$(MANIFEST_PYTHON) "$(GENERATE_KEY_DIGESTS)" --keys-dir "$(SEP_ROM_KEYS_DIR)" \
		--key-form "$(SEP_ROM_KEY_FORM)" -o "$@"

.PHONY: key-digests
key-digests: $(KEY_DIGESTS_C)

$(BUILD_DIR)/key_digests.o: $(KEY_DIGESTS_C) | $(BUILD_DIR)
	$(GCC_PREFIX)-gcc $(CFLAGS) -c "$<" -o "$@"

$(BUILD_DIR)/vector.o: $(SRC_DIR)/vector.S | $(BUILD_DIR)
	$(GCC_PREFIX)-gcc $(CFLAGS) $(ASFLAGS) -c "$<" -o "$@"

$(BUILD_DIR)/rom_metadata.o: $(SRC_DIR)/rom_metadata.c $(BUILD_DIR)/bl0_version.h | $(BUILD_DIR)
	$(GCC_PREFIX)-gcc $(CFLAGS) -c "$<" -o "$@"

$(BUILD_DIR)/%.o: $(SRC_DIR)/%.c | $(BUILD_DIR)
	$(GCC_PREFIX)-gcc $(CFLAGS) -c "$<" -o "$@"

# Keep pedantic warnings enabled so library/toolchain flag mismatches fail the build.
$(OCA_LIB_OBJS): $(OCA_OBJ_DIR)/%.o: $(OCA_LIB_DIR)/%.c | $(OCA_OBJ_DIR)
	$(GCC_PREFIX)-gcc $(CFLAGS) -c "$<" -o "$@"

# Reject an empty source glob so an uninitialized submodule cannot produce a ROM without validation.
ifeq ($(strip $(OCA_LIB_SRCS)),)
$(error the tt-oca-manifest submodule is not checked out: no sources under $(OCA_LIB_DIR). \
Run: git -C $(OCAH_ROOT) submodule update --init hw/sys/sep/bootrom/prod/tools/tt-oca-manifest)
endif

$(BUILD_DIR)/rsa_3072_app_otbn.o: $(OTBN_APP_C) | $(BUILD_DIR)
	$(GCC_PREFIX)-gcc $(CFLAGS) -c "$<" -o "$@"

$(OTBN_APP_C):
	$(MAKE) -C "$(DV_ROOT)/fw" -f fw.mk OCAH_ROOT="$(OCAH_ROOT)" dv-fw-otbn-apps

$(OBJS): | $(OTBN_APP_C)

$(SEP_FW_OVERLAY_OBJS): $(BUILD_DIR)/%.o: | $(BUILD_DIR)
	$(GCC_PREFIX)-gcc $(CFLAGS) -c "$(filter %/$*.c,$(SEP_FW_OVERLAY_SOURCES))" -o "$@"

# Hash insertion must succeed: the linked ELF contains an all-zero placeholder
# that otherwise looks like a valid embedded value.
$(ELF): $(BUILD_DIR) $(OBJS) $(LINK_DIR)/rom.ld $(INSERT_SHA256)
	$(GCC_PREFIX)-gcc $(LDFLAGS) $(OBJS) -o "$@"
	$(MANIFEST_PYTHON) $(INSERT_SHA256) --gcc-prefix $(GCC_PREFIX) -o "$@" "$@"
	$(GCC_PREFIX)-objdump -d -S "$@" > "$(BUILD_DIR)/boot_rom.dis"
	$(GCC_PREFIX)-nm -B -n "$@" > "$(BUILD_DIR)/boot_rom.sym"

# Select sections by LMA so the ROM initialization image includes .data.
$(VMEM): $(ELF) $(ELF_TO_VMEM)
	$(MANIFEST_PYTHON) $(ELF_TO_VMEM) --base $(ROM_BASE) -o "$@" "$(ELF)"

$(ITCM_HEX): $(ELF)
	$(GCC_PREFIX)-objcopy -O verilog "$(ELF)" $(ROM_ELF_SECTIONS) --change-addresses "-$(ROM_BASE)" "$@"

# Rebase DCCM data by __data_load_start; subtracting DCCM_BASE from its ROM LMA would wrap.
$(DTCM_HEX): $(ELF)
	set -e; \
	data_lma=$$($(GCC_PREFIX)-nm "$(ELF)" | awk '$$3 == "__data_load_start" { print "0x"$$1 }'); \
	[ -n "$$data_lma" ] || { echo "error: __data_load_start not found in $(ELF)" >&2; exit 1; }; \
	$(GCC_PREFIX)-objcopy -O verilog "$(ELF)" $(DTCM_ELF_SECTIONS) --change-addresses "-$$data_lma" "$@"

# Keep this phony so recursive make checks BL1 before every repack.
bl1_test:
	$(MAKE) -C "$(BL1_TEST_DIR)" GCC_PREFIX=$(GCC_PREFIX)

$(BL1_TEST_BIN):
	@echo "error: BL1 image is missing; run 'make toolchain-images' first" >&2
	@exit 1

# Keep packing isolated from the root project. The distribution is
# tt-oca-manifest, but its import package remains tt_boot_manifest. Resolve
# native wheels per invocation to avoid reusing another host's ABI artifacts.
ifneq ($(shell command -v uv 2>/dev/null),)
PACK_RUN := $(MANIFEST_PYTHON) -m tt_boot_manifest.pack_images
else
# PYTHONPATH cannot express package-dir remapping, so provide a symlink shim.
# Keep setup and execution in one shell so caller environment prefixes reach the packer.
PACK_SHIM := $(BUILD_DIR)/.pack-shim
PACK_RUN = sh -c 'mkdir -p "$(PACK_SHIM)" && \
	ln -sfn "$(abspath $(TT_OCA_MANIFEST_DIR))/src" "$(PACK_SHIM)/tt_boot_manifest" && \
	PYTHONPATH="$(PACK_SHIM)" exec python3 -m tt_boot_manifest.pack_images "$$@"' tt-pack
endif

ensure-pack-deps:
	@test -f "$(TT_OCA_MANIFEST_DIR)/pyproject.toml" || { \
	  echo "ERROR: the tt-oca-manifest submodule is not checked out."; \
	  echo "       Expected: $(CURDIR)/$(TT_OCA_MANIFEST_DIR)"; \
	  echo "       Run: git -C $(OCAH_ROOT) submodule update --init \\"; \
	  echo "              hw/sys/sep/bootrom/prod/tools/tt-oca-manifest"; \
	  exit 1; }
	@command -v uv >/dev/null || $(MANIFEST_PYTHON) -c 'import cryptography, ruamel.yaml, tomlkit, bitarray' 2>/dev/null || { \
	  echo "ERROR: uv not found and the packer's Python deps are not importable."; \
	  echo "       Either install uv (https://docs.astral.sh/uv/getting-started/installation/,"; \
	  echo "       tools/dv/run_dv.py requires the same tool, so this is a one-off), or"; \
	  echo "       provide python3 with cryptography, ruamel.yaml, tomlkit and bitarray."; \
	  exit 1; }

# SEP_SIGNING_KEY is only an existence check; each image config selects its
# signing key independently. Trust anchors are selected by SEP_ROM_KEYS_DIR.
SEP_SIGNING_KEY    ?= $(PROD_DIR)/tests/signing_keys/rsa_private_key.rom_key0.pem

# Each OCA_IMAGES entry needs matching _image.yaml and _test.yaml configs, with
# manifests at the ROM's slot offsets. Emit raw and SPI-preload forms and keep
# config paths relative. Distinct key-slot keys expose selection and revocation errors.
OCA_IMAGES := \
	non_secure_boot \
	secure_boot \
	encrypted_boot \
	aes128_boot \
	otp_key_boot \
	sip_key_boot \
	identity_boot \
	pqc_boot \
	ecdsa_boot \
	der_boot \
	multi_image_boot \
	encrypted_multi_image_boot \
	toc_cap_boot \
	encrypted_toc_cap_boot \
	no_bl1_boot \
	rom_key1_boot \
	rom_key2_boot \
	rom_key3_boot \
	rom_key4_boot \
	rom_key5_boot

OCA_BINS := $(patsubst %,$(BUILD_DIR)/oca_%.bin,$(OCA_IMAGES))
OCA_HEXS := $(patsubst %,$(BUILD_DIR)/oca_%.spi_preload,$(OCA_IMAGES))

# Rebase the combined image to SMC_SRAM_BASE with its primary manifest at +0x1000.
OCA_SMC_MEM_HEX := $(BUILD_DIR)/oca_smc_mem.hex
OCA_SMC_MEM_MISALIGNED_HEX := $(BUILD_DIR)/oca_smc_mem_misaligned.hex
# The bare bundle instead resolves payload_offset from its own body_size.
OCA_SMC_CONFIG := $(PROD_DIR)/configs/oca_secure_boot_test.yaml
OCA_SMC_BIN    := $(BUILD_DIR)/oca_smc_bundle.bin

.PHONY: oca-images
ifeq ($(BUILD_TYPE),release)
oca-images:
	@echo "ERROR: oca-images is not implemented for BUILD_TYPE=release."; \
	echo "       The configs sign with the private test keys in tests/signing_keys/,"; \
	echo "       which must never produce a flashable release image."; \
	echo "       Production signing needs a key store (signing_authority=hsm/aws)"; \
	echo "       and is not wired up yet."; \
	echo "       For test images: make BUILD_TYPE=debug oca-images"; \
	exit 1
else
oca-images: $(OCA_HEXS) $(OCA_SMC_BIN) $(OCA_SMC_MEM_HEX) $(OCA_SMC_MEM_MISALIGNED_HEX)
endif

$(OCA_BINS): $(BUILD_DIR)/oca_%.bin: $(PROD_DIR)/configs/oca_%_image.yaml \
                                     $(PROD_DIR)/configs/oca_%_test.yaml \
                                     bl1_test ensure-pack-deps | $(BUILD_DIR)
	@test -f "$(SEP_SIGNING_KEY)" || { \
	  echo "ERROR: OCA images need the ROM key 0 signing key."; \
	  echo "       Expected: $(SEP_SIGNING_KEY)"; \
	  echo "       It is committed in this directory as a DV asset; check the working"; \
	  echo "       tree for local modifications."; \
	  exit 1; }
	$(PACK_RUN) --config "$<" --out "$@" -v

$(OCA_HEXS): $(BUILD_DIR)/oca_%.spi_preload: $(BUILD_DIR)/oca_%.bin
	$(MANIFEST_PYTHON) "$(BIN_TO_SPI)" "$<" "$@"

$(OCA_SMC_BIN): $(OCA_SMC_CONFIG) bl1_test ensure-pack-deps | $(BUILD_DIR)
	$(PACK_RUN) --config "$(OCA_SMC_CONFIG)" --out "$@" -v

# Rebase the image to SMC_SRAM_BASE while retaining the manifest at offset 0x1000.
$(OCA_SMC_MEM_HEX): $(BUILD_DIR)/oca_non_secure_boot.bin
	$(MANIFEST_PYTHON) "$(BIN_TO_SPI)" "$<" "$(BUILD_DIR)/oca_smc_mem.spi_preload"
	sed 's/@00000000/@$(SMC_SRAM_BASE)/' "$(BUILD_DIR)/oca_smc_mem.spi_preload" > "$@"

# Shift the complete image by four bytes so manifest and payload offsets remain mutually valid.
$(OCA_SMC_MEM_MISALIGNED_HEX): $(BUILD_DIR)/oca_non_secure_boot.bin
	printf '\000\000\000\000' > "$(BUILD_DIR)/oca_smc_mem_misaligned.bin"
	cat "$<" >> "$(BUILD_DIR)/oca_smc_mem_misaligned.bin"
	$(MANIFEST_PYTHON) "$(BIN_TO_SPI)" "$(BUILD_DIR)/oca_smc_mem_misaligned.bin" \
		"$(BUILD_DIR)/oca_smc_mem_misaligned.spi_preload"
	sed 's/@00000000/@$(SMC_SRAM_BASE)/' \
		"$(BUILD_DIR)/oca_smc_mem_misaligned.spi_preload" > "$@"

DERIVE_CONFIG_PY := $(PROD_DIR)/scripts/derive_pack_config.py
ifneq ($(shell command -v uv 2>/dev/null),)
DERIVE_RUN := $(MANIFEST_PYTHON) "$(DERIVE_CONFIG_PY)"
else
DERIVE_RUN := python3 "$(DERIVE_CONFIG_PY)"
endif
ENCRYPTED_IMAGE_CONFIG := $(PROD_DIR)/configs/oca_encrypted_boot_image.yaml
DECRYPT_NEG_BINS := $(BUILD_DIR)/invalid_class_key.bin

decrypt_negative_images: $(DECRYPT_NEG_BINS)

$(BUILD_DIR)/invalid_class_key.yaml: $(DERIVE_CONFIG_PY) $(ENCRYPTED_IMAGE_CONFIG) \
		| $(BUILD_DIR) ensure-pack-deps
	$(DERIVE_RUN) --base "$(ENCRYPTED_IMAGE_CONFIG)" \
		--set-str combos.1.config=configs/oca_secure_boot_test.yaml --out "$@"

$(DECRYPT_NEG_BINS): $(BUILD_DIR)/%.bin: $(BUILD_DIR)/%.yaml bl1_test ensure-pack-deps
	@test -f "$(SEP_SIGNING_KEY)" || { \
	  echo "ERROR: $* needs the ROM key 0 signing key."; \
	  echo "       Expected: $(SEP_SIGNING_KEY)"; \
	  exit 1; }
	$(PACK_RUN) --config "$<" --out "$@" -v

# Remove all build profiles, including those not selected by BUILD_DIR.
clean:
	rm -rf "$(BUILD_DIR)" $(PROD_DIR)/build $(PROD_DIR)/build_pio $(PROD_DIR)/build_release
	$(MAKE) -C "$(BL1_TEST_DIR)" clean 2>/dev/null || true
