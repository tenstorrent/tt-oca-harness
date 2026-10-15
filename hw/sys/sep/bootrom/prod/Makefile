# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

SHELL := /usr/bin/env
.SHELLFLAGS := bash -c
#
# SEP Boot ROM.
#
# Flash is read through the OpenTitan SPI host (src/sep_ot_spi.c) by default.
# BOOT_SPI_CONTROLLER_OT=0 selects memory-mapped flash through the XIP window, whose
# controller driver an integrator supplies; the open src/sep_spi.c reports it absent.
#
# The boot images are built from source: bl1_pass_test is packed by the
# tools/tt-oca-manifest submodule from the configs/oca_*.yaml pairs (OCA_IMAGES).
#
# Read-only sections (.text/.metadata/.rodata) link into Boot ROM and are loaded
# through +sep_boot_rom_hex. Writable sections (.data/.bss) link into DCCM and
# are backdoor-loaded through the TCM responder.
#
# Outputs (build/, gitignored):
#   boot_rom.vmem     - 64-bit VMEM for the Boot ROM responder ($readmemh)
#   boot_rom.itcm.hex - ROM read-only sections as TCM-relative byte hex
#   boot_rom.dtcm.hex - DCCM .data/.bss as DCCM-relative byte hex
#   oca_*.bin         - OCA boot images, one per validator path (OCA_IMAGES)
#   oca_smc_mem.hex   - manifest+BL1 image at SMC-SRAM base (+sep_smc_mem_hex)
#
# Prereqs: RISCV_TOOLCHAIN pointing at a picolibc-enabled toolchain bin dir, or
# scripts/docker-run.sh. The packer's Python dependencies come from its
# submodule's pyproject.toml, installed on demand by uv, and stay on the host.
RISCV_TOOLCHAIN ?=
RISCV_PREFIX ?= $(if $(wildcard $(RISCV_TOOLCHAIN)/riscv64-unknown-elf-gcc),riscv64-unknown-elf-,riscv-none-elf-)
GCC_PREFIX ?= $(if $(strip $(RISCV_TOOLCHAIN)),$(patsubst %/,%,$(RISCV_TOOLCHAIN))/$(patsubst %-,%,$(RISCV_PREFIX)),riscv64-unknown-elf)

# hw/sys/sep -- this ROM lives at <sep>/bootrom/prod, the DV tree is its sibling.
PROD_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
SEP_ROOT := $(abspath $(PROD_DIR)/../..)
DV_ROOT  := $(SEP_ROOT)/dv

OCAH_ROOT := $(abspath $(SEP_ROOT)/../../..)

UV ?= uv
# The manylinux_2_34 cryptography wheel requires GLIBC_2.30. A host whose glibc
# is older installs the manylinux_2_28 wheel, or the 2.17 wheel below that.
# An environment created without the cap keeps the incompatible wheel, so the
# capped invocation reinstalls it.
MANIFEST_UV_PLATFORM := $(shell python3 -c 'import platform; libc, ver = platform.libc_ver(); parts = tuple(int(x) for x in ver.split(".")[:2]) if ver else (0, 0); machine = platform.machine(); print("" if libc != "glibc" or parts >= (2, 34) else f"{machine}-manylinux_2_28" if parts >= (2, 28) else f"{machine}-manylinux_2_17")' 2>/dev/null)
MANIFEST_UV_FLAGS := $(if $(MANIFEST_UV_PLATFORM),--python-platform $(MANIFEST_UV_PLATFORM) --reinstall-package cryptography,)
MANIFEST_PYTHON ?= $(UV) --project "$(OCAH_ROOT)" run --locked --group manifest $(MANIFEST_UV_FLAGS) python

# Generated SEP register headers, read from the register flow's own output so
# they cannot drift from the RDL the RTL is built from.
# Overlay inputs must be explicit make command-line assignments. These
# assignments discard ambient environment values while preserving command-line
# overrides.
OCAH_FW_REG_OVERLAY_INCLUDE_DIRS_sep :=
OCAH_FW_REG_OVERLAY_INCLUDE_DIRS_smc :=
OCAH_FW_OVERLAY_SOURCES_sep :=
include $(OCAH_ROOT)/hw/common/dv/fw/reg_includes.mk
# The SMC map places the SMC registers SEP reaches through its SMC window.
REG_INCLUDE_DIRS := $(call ocah_fw_reg_includes,sep) $(call ocah_fw_reg_includes,smc)

ROM_BASE  ?= 0x10040000
DCCM_BASE ?= 0xC0040000

# Full DCCM. Reset does not clear it and explicit_memzero() misses temporaries
# and spilled registers, so this scrub is what keeps key material off the stack.
DCCM_SCRUB_BYTES ?= 0x20000

# Off by default: rom_clear_ext_sram() runs before the manifest load, and the
# testbench can preload SEP SRAM (+sep_sram_hex). 0x40000 clears all of it, which
# SEP-ROM-CPU-100 requires; rom.adoc tracks the default as a gap.
SRAM_SCRUB_BYTES ?= 0

# BL1 execution from SEP SRAM. ICCM is the secure execution space and is always
# permitted; SRAM is additionally permitted by default because debug and special
# applications need it (a BL1 linked for SRAM, or an image staged where the LSU
# can read it too). Set to 0 to lock the ROM down to ICCM-only execution: the ROM
# then refuses a BL1 whose TOC load_addr lies in SRAM, and vector.S likewise
# refuses a warm-reset handler there -- both have to move together or a warm
# reset would re-enter a region the cold path would not have booted.
#
# Default 1 preserves today's behaviour; the default may flip once nothing needs
# the SRAM path.
BL1_SRAM_EXEC_ENABLE ?= 1
# ICCM ECC establishment. The BL1 copy writes BL1's own words with valid ECC, so
# only words past its end can be fetched having never been written; a pad at
# hand-off covers those. Set ROM_ICCM_CLEAR_FULL=1 to scrub all of ICCM at [S16]
# instead, which also clears power-up residue at a cost of ~2M cycles.
ROM_ICCM_CLEAR_ENABLE ?= 1
ROM_ICCM_CLEAR_FULL ?= 0
PMP_ENABLE ?= 1

# DV drives this Makefile directly (sep_sim_cfg.toml) and names build/, so debug is
# the default.
#
# The build type selects the trust anchors: debug generates key_digests.c from the
# private test keys in tests/signing_keys/, release from PUBLIC keys only, out of
# tree, and refuses to build without them. See SEP_ROM_KEYS_DIR below.
BUILD_TYPE ?= debug
ifeq ($(filter $(BUILD_TYPE),debug release),)
$(error Invalid BUILD_TYPE: $(BUILD_TYPE). Use 'debug' or 'release')
endif

# Flash transport: 1 = OpenTitan SPI host (default), 0 = memory-mapped flash through
# the XIP window, with controller init from an override of the src/sep_spi.c hooks.
# --gc-sections drops the unused driver.
BOOT_SPI_CONTROLLER_OT ?= 1
# OpenTitan RX-FIFO drain method (used only when BOOT_SPI_CONTROLLER_OT=1):
# 0 = secure DMA (default), 1 = CPU programmed I/O.
BOOT_OT_SPI_USE_PIO ?= 0
# OpenTitan timing/device profile index (used only when BOOT_SPI_CONTROLLER_OT=1).
BOOT_OT_SPI_PROFILE ?= 0

# `?=`, because the OT variants pass BUILD_DIR= on the sub-make command line and DV
# names build/ directly; a command-line value has to win. Release lands in its own
# tree, so a caller that means the debug image cannot pick up the release one.
ifeq ($(BUILD_TYPE),release)
BUILD_DIR ?= $(PROD_DIR)/build_release
else
BUILD_DIR ?= $(PROD_DIR)/build
endif
LINK_DIR  := $(PROD_DIR)/link
SRC_DIR   := $(PROD_DIR)/src
TOOLS_DIR := $(PROD_DIR)/tools
INCLUDE_DIR := $(PROD_DIR)/include

# ROM key material. The ROM anchors on SHA-256 of each slot's RSA-3072 public modulus.
# key_digests.c is generated from these files at build time, so the anchors track the
# keys and no test digest can reach a mask.
#
# debug reads the private test keys in the tree. release reads PUBLIC keys only, from a
# directory that ships empty, and refuses one holding any private key. Production
# private keys belong in a key store, never in source control.
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

# The packer is the tt-oca-manifest repo, checked out as a submodule here rather
# than copied in, so it tracks the upstream repo as that grows. Defined this early
# because the OCA validation library it also ships feeds CFLAGS and OBJS below.
TT_OCA_MANIFEST_DIR := $(TOOLS_DIR)/tt-oca-manifest

ELF      := $(BUILD_DIR)/boot_rom.elf
VMEM     := $(BUILD_DIR)/boot_rom.vmem
ITCM_HEX := $(BUILD_DIR)/boot_rom.itcm.hex
DTCM_HEX := $(BUILD_DIR)/boot_rom.dtcm.hex

INSERT_SHA256 := $(TOOLS_DIR)/insert-rom-sha256.py
ELF_TO_VMEM   := $(TOOLS_DIR)/elf-to-vmem.py

# --- manifest+BL1 SMC image (built from source, packed by tt-oca-manifest) ---
BL1_TEST_DIR := $(DV_ROOT)/fw/tests/bl1_pass_test
BL1_TEST_BIN := $(BL1_TEST_DIR)/build/bl1_pass_test.bin
# SMC-SRAM base the behavioral SMC responder loads the image at (see tb_top.sv
# SEP_SMC_MEM_MODEL + testlist +sep_smc_mem_hex). Verilog-hex @ address (no 0x).
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

# --- OCA boot-manifest validation library (tt-oca-manifest submodule) --------
# The ROM does not hand-parse the OCA manifest; it links the vendor library and
# supplies platform callbacks (src/oca_platform.c). Sources are globbed rather
# than listed so a library that grows a translation unit does not silently drop
# it -- the library is the format's source of truth, not this list.
#
# Objects land in a subdirectory, NOT flat in $(BUILD_DIR): the library ships its
# own lifecycle.c, which would otherwise overwrite this ROM's src/lifecycle.o.
# That is also why the firmware overlay hook is wrong for it -- that hook
# $(notdir)s every source into one flat namespace.
OCA_LIB_DIR  := $(TT_OCA_MANIFEST_DIR)/validators/oca/lib
OCA_LIB_SRCS := $(wildcard $(OCA_LIB_DIR)/*.c)
OCA_OBJ_DIR  := $(BUILD_DIR)/oca
OCA_LIB_OBJS := $(patsubst $(OCA_LIB_DIR)/%.c,$(OCA_OBJ_DIR)/%.o,$(OCA_LIB_SRCS))

# Feature gates. PQC stays on so the ROM understands OCAP geometry; the library
# implements no PQC signature verification either way, so a native PQC signature
# reports OCA_FAIL_UNSUPPORTED_VARIANT rather than a false pass. Turning PQC off
# is the largest ROM-size lever available if the 64 KiB budget gets tight.

# Entropy chain bring-up (ESRC -> DRBG/CSRNG -> EDN) in the ROM. On by default.
# Setting it to 0 produces a diagnostic build in which the ROM does not provide
# entropy to crypto blocks, so entropy-dependent secure boot cannot complete.
SEP_ENTROPY_BRINGUP ?= 1

# One-way entropy lock bypasses, independent of each other. Both locks are
# APPLIED BY DEFAULT; set a flag to 1 to leave that lock for SEP BL1 instead.
# They are separate knobs because they freeze unrelated things and an adopter
# may well want one and not the other:
#   DEFER_FIPS_LOCK     leaves ESRC.FIPS_LOCK clear, so BL1 can still change the
#                       entropy-source configuration (conditioning, health-test
#                       thresholds, compressor bypass).
#   DEFER_SRC_SEL_LOCK  leaves EXT_TRNG_SRC_SEL_LOCK clear, so BL1 can still
#                       repoint an entropy stream at a different source.
# Deferring does NOT mean "never lock" -- it means BL1 owns applying it. A build
# that defers and whose BL1 never locks ships with the field mutable.
SEP_ENTROPY_DEFER_FIPS_LOCK    ?= 0
SEP_ENTROPY_DEFER_SRC_SEL_LOCK ?= 0

OCA_SUPPORT_CLASSIC ?= 1
OCA_SUPPORT_PQC     ?= 1
OCA_TOC_MAX_IMAGES  ?= 32

OBJS += $(OCA_LIB_OBJS)

# The secure-boot path verifies the manifest signature on OTBN, so the ROM links
# the generated RSA-3072 OTBN application; the $(OTBN_APP_C) rule regenerates it.
OTBN_APP_DIR := $(DV_ROOT)/fw/build/otbn/rsa_3072_app
OTBN_APP_C   := $(OTBN_APP_DIR)/rsa_3072_app_otbn.c

# Optional absolute .c paths from an adopter overlay build. Their strong symbols
# override the weak stubs in src/, such as the external flash controller hooks in
# src/sep_spi.c.
SEP_FW_OVERLAY_SOURCES := $(OCAH_FW_OVERLAY_SOURCES_sep)
SEP_FW_OVERLAY_OBJS := $(patsubst %.c,$(BUILD_DIR)/%.o,$(notdir $(SEP_FW_OVERLAY_SOURCES)))
OBJS += $(SEP_FW_OVERLAY_OBJS)

# rv32im (no C) + no relax. zifencei is spelled out because binutils >= 2.38
# rejects fence.i without it.
CC_ABI   := -march=rv32im_zicsr_zifencei -mabi=ilp32

# DEBUG gates the virtual console (include/rom_virt_console.h), whose ~230 call sites
# write decoded text to a real SEP scratch CSR -- lifecycle state, fuse lock values,
# key-slot selection and the BL1 load address among them. Without it the header's
# #else turns every simput* name into a no-op. Machine-readable STATUS_OUT()
# reporting does not pass through the console and is unaffected either way.
ifeq ($(BUILD_TYPE),release)
BUILD_TYPE_DEFINES := -DNDEBUG=1
else
BUILD_TYPE_DEFINES := -DTEST_BUILD=1 -DDEBUG
endif
# The generated register headers need <assert.h> for their packing checks, which
# is not freestanding and only resolves through picolibc's spec file.
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
# .rodata is deliberately not here: its LMA is in ROM, so claiming it for the
# DTCM image makes objcopy subtract DCCM_BASE from a ROM address and wrap.
DTCM_ELF_SECTIONS := --only-section=.data --only-section=.data.* --only-section=.sdata --only-section=.sdata.* \
	--only-section=.bss --only-section=.bss.* --only-section=.sbss --only-section=.sbss.*

# A recipe that dies partway must not leave its target behind: $(ELF) is linked and
# then patched in place, so a failed insert would otherwise leave an unpatched ELF
# that make considers up to date and skips on the next run.
.DELETE_ON_ERROR:

.PHONY: all clean bl1_test ensure-pack-deps toolchain-images toolchain-images-build \
        pio-toolchain-images debug release decrypt_negative_images

# Release stops at the ROM: oca-images emits flash images signed with the private
# test keys the configs name, which a release build must never emit.
ifeq ($(BUILD_TYPE),release)
all: toolchain-images
else
all: toolchain-images oca-images
endif

# Same shorthands hw/sys/smc/bootrom/prod offers.
debug:
	@$(MAKE) BUILD_TYPE=debug all
release:
	@$(MAKE) BUILD_TYPE=release all

# The CPU-PIO drain builds into its own directory so both OpenTitan ROM profiles
# coexist. Packed flash images are drain-method agnostic and remain in build/.
pio-toolchain-images:
	$(MAKE) BUILD_DIR=$(PROD_DIR)/build_pio BOOT_SPI_CONTROLLER_OT=1 BOOT_OT_SPI_USE_PIO=1 \
		toolchain-images

# Split by tool dependency so callers can run each half in the right environment:
# toolchain-images needs the RISC-V/picolibc toolchain (i.e. the ocah-toolchain
# container). oca-images and key-digests are pure Python and run via uv, which
# the container carries.
#
# Direct `make toolchain-images` uses only an explicit RISCV_TOOLCHAIN on the
# host. Otherwise it runs the compiler-dependent half in the OCAH container.
OCAH_DOCKER_RUN := $(OCAH_ROOT)/scripts/docker-run.sh

# key-digests runs before entering the container so the generated source is
# available to the compiler regardless of which path toolchain-images takes.
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

toolchain-images-build: $(VMEM) $(ITCM_HEX) $(DTCM_HEX) bl1_test

$(BUILD_DIR):
	mkdir -p "$(BUILD_DIR)"

$(OCA_OBJ_DIR):
	mkdir -p "$(OCA_OBJ_DIR)"

# --- Rebuild on build-flag changes ---
# Objects are keyed on source mtime but their content depends on the -D flags, so
# without this stamp a variant rebuild silently hands back the previous image.
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

# FORCE so the recipe runs every build; the cmp-and-move only bumps the stamp's
# mtime when the flags differ, so an unchanged build rebuilds nothing.
$(FLAGS_STAMP): FORCE | $(BUILD_DIR)
	@echo '$(BUILD_FLAGS)' > "$@.tmp"
	@if ! cmp -s "$@.tmp" "$@" 2>/dev/null; then \
	  echo "  [build flags changed -> rebuilding objects]"; \
	  mv "$@.tmp" "$@"; \
	else \
	  rm "$@.tmp"; \
	fi

$(OBJS): $(FLAGS_STAMP)

# Header dependencies (gcc -MMD -MP). Without these, a header edit that changes a
# shared struct layout (e.g. bl0_state.h) leaves stale objects with the old layout —
# a split-brain link where one .o writes a field at the old offset and another reads
# it at the new one (seen: bl0_state.lc_state read as garbage after a rebase, failing
# the manifest usage-constraint check). Header edits now rebuild dependents.
-include $(OBJS:.o=.d)

# smc_base_config.h also declares C types, which vector.S cannot read, so the
# SMC local base sep_smc_map.h needs is copied into a macro-only header.
SMC_BASE_CONFIG_H := $(firstword $(wildcard $(addsuffix /smc_base_config.h,$(patsubst -I%,%,$(REG_INCLUDE_DIRS)))))
SMC_LOCAL_BASE_H := $(BUILD_DIR)/smc_local_base.h
$(SMC_LOCAL_BASE_H): $(SMC_BASE_CONFIG_H) $(FLAGS_STAMP) | $(BUILD_DIR)
	grep -E '^#define SMC_BASE_CONFIG__LOCAL_BASE__BASE_reset 0x[0-9a-fA-F]+$$' "$<" > "$@"

$(OBJS): $(SMC_LOCAL_BASE_H)

# Static version header.
$(BUILD_DIR)/bl0_version.h: | $(BUILD_DIR)
	echo '#define BL0_VERSION "oss-nonsecure"' > "$@"

# ROM key digest table. The key files are prerequisites, so rotating a key rebuilds
# the anchors and keeps them in step with what signs the images.
#
# The digests track the key directory and form, nothing else in BUILD_FLAGS, and only
# the host can regenerate them (below), so they carry their own stamp.
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

# The generated source lives in $(BUILD_DIR), outside the $(SRC_DIR)/%.c pattern
# rule below, so it needs its own.
$(BUILD_DIR)/key_digests.o: $(KEY_DIGESTS_C) | $(BUILD_DIR)
	$(GCC_PREFIX)-gcc $(CFLAGS) -c "$<" -o "$@"

$(BUILD_DIR)/vector.o: $(SRC_DIR)/vector.S | $(BUILD_DIR)
	$(GCC_PREFIX)-gcc $(CFLAGS) $(ASFLAGS) -c "$<" -o "$@"

$(BUILD_DIR)/rom_metadata.o: $(SRC_DIR)/rom_metadata.c $(BUILD_DIR)/bl0_version.h | $(BUILD_DIR)
	$(GCC_PREFIX)-gcc $(CFLAGS) -c "$<" -o "$@"

$(BUILD_DIR)/%.o: $(SRC_DIR)/%.c | $(BUILD_DIR)
	$(GCC_PREFIX)-gcc $(CFLAGS) -c "$<" -o "$@"

# OCA validation library, compiled from the submodule into its own object dir.
# -Wno-pedantic is deliberately NOT set: the library builds clean under its own
# -Wall -Wextra -Werror -pedantic, so a warning here means a real toolchain or
# flag mismatch worth seeing rather than silencing.
$(OCA_LIB_OBJS): $(OCA_OBJ_DIR)/%.o: $(OCA_LIB_DIR)/%.c | $(OCA_OBJ_DIR)
	$(GCC_PREFIX)-gcc $(CFLAGS) -c "$<" -o "$@"

# A submodule nobody init'd yields an empty wildcard and a ROM that links without
# a manifest parser at all. Fail loudly instead.
ifeq ($(strip $(OCA_LIB_SRCS)),)
$(error the tt-oca-manifest submodule is not checked out: no sources under $(OCA_LIB_DIR). \
Run: git -C $(OCAH_ROOT) submodule update --init hw/sys/sep/bootrom/prod/tools/tt-oca-manifest)
endif

# Generated OTBN application image, built out of tree by the shared fw engine.
$(BUILD_DIR)/rsa_3072_app_otbn.o: $(OTBN_APP_C) | $(BUILD_DIR)
	$(GCC_PREFIX)-gcc $(CFLAGS) -c "$<" -o "$@"

$(OTBN_APP_C):
	$(MAKE) -C "$(DV_ROOT)/fw" -f fw.mk OCAH_ROOT="$(OCAH_ROOT)" dv-fw-otbn-apps

# rsa_verify.c/otbn_driver.c include the generated header too (order-only).
$(OBJS): | $(OTBN_APP_C)

# Compile rule for overlay sources (static pattern rule so Make maps
# each object back to its out-of-tree source path).
$(SEP_FW_OVERLAY_OBJS): $(BUILD_DIR)/%.o: | $(BUILD_DIR)
	$(GCC_PREFIX)-gcc $(CFLAGS) -c "$(filter %/$*.c,$(SEP_FW_OVERLAY_SOURCES))" -o "$@"

# The ROM-hash insert is not optional. g_rom_sha256_str (src/rom_metadata.c) ships as
# an all-zero placeholder, and a silently skipped insert leaves it that way -- which
# any consumer of the embedded hash reads as a valid-looking empty value. Errors are
# no longer swallowed, and the script is a real prerequisite so the ELF relinks when
# it changes.
$(ELF): $(BUILD_DIR) $(OBJS) $(LINK_DIR)/rom.ld $(INSERT_SHA256)
	$(GCC_PREFIX)-gcc $(LDFLAGS) $(OBJS) -o "$@"
	$(MANIFEST_PYTHON) $(INSERT_SHA256) --gcc-prefix $(GCC_PREFIX) -o "$@" "$@"
	$(GCC_PREFIX)-objdump -d -S "$@" > "$(BUILD_DIR)/boot_rom.dis"
	$(GCC_PREFIX)-nm -B -n "$@" > "$(BUILD_DIR)/boot_rom.sym"

# Boot ROM responder image. elf-to-vmem.py selects sections by LMA, and .data's
# LMA is in ROM (AT> rom), so its initial image lands here too.
$(VMEM): $(ELF) $(ELF_TO_VMEM)
	$(MANIFEST_PYTHON) $(ELF_TO_VMEM) --base $(ROM_BASE) -o "$@" "$(ELF)"

$(ITCM_HEX): $(ELF)
	$(GCC_PREFIX)-objcopy -O verilog "$(ELF)" $(ROM_ELF_SECTIONS) --change-addresses "-$(ROM_BASE)" "$@"

# DCCM preload image. .data's LMA is in ROM, so rebase by __data_load_start;
# DCCM_BASE would wrap negative and fail the load.
$(DTCM_HEX): $(ELF)
	set -e; \
	data_lma=$$($(GCC_PREFIX)-nm "$(ELF)" | awk '$$3 == "__data_load_start" { print "0x"$$1 }'); \
	[ -n "$$data_lma" ] || { echo "error: __data_load_start not found in $(ELF)" >&2; exit 1; }; \
	$(GCC_PREFIX)-objcopy -O verilog "$(ELF)" $(DTCM_ELF_SECTIONS) --change-addresses "-$$data_lma" "$@"

# --- manifest+BL1 SMC image ---
# Build the BL1 payload (bl1_pass_test) from source. Phony so the recursive make
# owns its own up-to-date check and we always re-pack against the latest BL1.
bl1_test:
	$(MAKE) -C "$(BL1_TEST_DIR)" GCC_PREFIX=$(GCC_PREFIX)

$(BL1_TEST_BIN):
	@echo "error: BL1 image is missing; run 'make toolchain-images' first" >&2
	@exit 1

# --no-project keeps this off the repo-root uv project: the root lockfile must
# stay resolvable in a checkout where submodules were never init'd.
#
# NOTE on the name mismatch below: the submodule is tt-oca-manifest, but the
# Python import package is still `tt_boot_manifest`. That is deliberate upstream
# -- tt-oca-manifest's pyproject.toml renames only the *distribution*
# (name = "tt-oca-manifest") and keeps package-dir {tt_boot_manifest = "src"} so
# existing `python -m tt_boot_manifest.pack_images` callers are a drop-in. Do not
# "fix" the module paths here to match the repo name; they would stop resolving.
#
# The packer imports native wheels such as cryptography. Keep its environment
# local to this invocation and bypass the shared package cache so artifacts
# resolved on another host cannot supply ABI-incompatible binaries; uv still
# detects the current OS, architecture and libc when resolving those wheels.
ifneq ($(shell command -v uv 2>/dev/null),)
PACK_RUN := $(MANIFEST_PYTHON) -m tt_boot_manifest.pack_images
else
# uv-less fallback The submodule maps package-dir {tt_boot_manifest = "src"}, which
# plain PYTHONPATH can't express — a symlink shim reproduces it. Kept a single
# sh -c command so callers' `OCH_ROOT=... ROOT=... $(PACK_RUN) args` env
# prefixes still bind to the packer, not to a leading mkdir.
PACK_SHIM := $(BUILD_DIR)/.pack-shim
PACK_RUN = sh -c 'mkdir -p "$(PACK_SHIM)" && \
	ln -sfn "$(abspath $(TT_OCA_MANIFEST_DIR))/src" "$(PACK_SHIM)/tt_boot_manifest" && \
	PYTHONPATH="$(PACK_SHIM)" exec python3 -m tt_boot_manifest.pack_images "$$@"' tt-pack
endif

# A submodule nobody init'd is the likely failure here, and the packer's own error
# for it ("No module named tt_boot_manifest") does not point at the cause.
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

# ROM key 0's private key, for the oca-images existence check only.
#
# Pointing it elsewhere does NOT change which key signs: each configs/oca_*_test.yaml
# names its own signing_key_file, the packer reads the key from there
# (tt-oca-manifest src/manifest_signing.py), and pack_images has no key option. To sign
# with a different key, edit the config. For the ROM's trust anchors, see
# SEP_ROM_KEYS_DIR above.
SEP_SIGNING_KEY    ?= $(PROD_DIR)/tests/signing_keys/rsa_private_key.rom_key0.pem

# --- OCA boot-manifest images (the format the ROM parses) ---------------------
# One entry per path through the validator. Each name <n> in OCA_IMAGES needs a
# pair of configs: configs/oca_<n>_image.yaml (oca-combined -- places the bundle
# at the two slot offsets the ROM reads, PRIMARY/BACKUP_MANIFEST_OFFSET in
# boot_flash.h) and configs/oca_<n>_test.yaml (the bundle itself). A bare bundle
# packs to offset 0 and is not bootable from SPI on its own.
#
# Every image emits BOTH forms: the VP stages the raw .bin through
# SimConfig(flash_image=...), DV hands the same .bin to OcahSpiFlash.preload(),
# and the .spi_preload ($readmemh) is what a spiPreload= run wants. Cheap to
# emit, and having only one is a confusing failure much later.
#
# No OCH_ROOT/ROOT env prefix: the OCA producer does not expand variables in
# config paths (src/oca/payload.py opens `path` verbatim), so the configs carry
# paths relative to this directory.
#
# rom_key1..rom_key5 are not extra validator paths -- they are the same signed
# path anchored on ROM key slots 1-5, each signed by a DIFFERENT key from
# tests/signing_keys/ (slot 0 is secure_boot, signed by ROM key 0).
# Six distinct keys are what makes per-slot resolution and per-slot revocation
# testable: with one shared key every slot would resolve to the same digest and an
# off-by-one in either path would go unnoticed.
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

# The SMC-SRAM model receives the combined non-secure image rebased to its
# address window. Its MANIFEST_ADDR points at offset 0x1000, matching the
# primary manifest position in that image.
OCA_SMC_MEM_HEX := $(BUILD_DIR)/oca_smc_mem.hex
# The virtual platform stages a bare bundle instead: it resolves the payload from
# the manifest's own payload_offset, which for a bundle is exactly body_size.
OCA_SMC_CONFIG := $(PROD_DIR)/configs/oca_secure_boot_test.yaml
OCA_SMC_BIN    := $(BUILD_DIR)/oca_smc_bundle.bin

.PHONY: oca-images
ifeq ($(BUILD_TYPE),release)
# Every config under configs/ names a private key in tests/signing_keys/, so packing
# here emits flashable images carrying a test signature. Release signing reaches a key
# store: the packer exposes that as signing_authority (local | aws | hsm,
# src/manifest_signing.py) with signing_key_id, but its OCA config path defers hsm, so
# wiring it needs a tt-oca-manifest change too.
oca-images:
	@echo "ERROR: oca-images is not implemented for BUILD_TYPE=release."; \
	echo "       The configs sign with the private test keys in tests/signing_keys/,"; \
	echo "       which must never produce a flashable release image."; \
	echo "       Production signing needs a key store (signing_authority=hsm/aws)"; \
	echo "       and is not wired up yet."; \
	echo "       For test images: make BUILD_TYPE=debug oca-images"; \
	exit 1
else
oca-images: $(OCA_HEXS) $(OCA_SMC_BIN) $(OCA_SMC_MEM_HEX)
endif

# Static pattern rule so a new image is one line in OCA_IMAGES plus its two
# configs -- there is no per-image recipe to copy and get subtly wrong.
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

# Rebase the combined non-secure image for $readmemh into the behavioral SMC
# SRAM model. The manifest remains at offset 0x1000 from SMC_SRAM_BASE.
$(OCA_SMC_MEM_HEX): $(BUILD_DIR)/oca_non_secure_boot.bin
	$(MANIFEST_PYTHON) "$(BIN_TO_SPI)" "$<" "$(BUILD_DIR)/oca_smc_mem.spi_preload"
	sed 's/@00000000/@$(SMC_SRAM_BASE)/' "$(BUILD_DIR)/oca_smc_mem.spi_preload" > "$@"

# Decryption negative image: the primary stays encrypted and the backup is unencrypted.
DERIVE_CONFIG_PY := $(PROD_DIR)/scripts/derive_pack_config.py
ifneq ($(shell command -v uv 2>/dev/null),)
DERIVE_RUN := $(MANIFEST_PYTHON) "$(DERIVE_CONFIG_PY)"
else
# uv-less fallback: the script needs only ruamel.yaml, which ensure-pack-deps checks.
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

# Removes every supported build profile, not just $(BUILD_DIR).
clean:
	rm -rf "$(BUILD_DIR)" $(PROD_DIR)/build $(PROD_DIR)/build_pio $(PROD_DIR)/build_release
	$(MAKE) -C "$(BL1_TEST_DIR)" clean 2>/dev/null || true
