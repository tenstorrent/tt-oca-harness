# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

SHELL := /usr/bin/env
.SHELLFLAGS := bash -c
#
# SEP Boot ROM.
#
# SPI is stubbed (src/sep_spi.c): the `sep` DUT has no Cadence xSPI, so the ROM
# skips the SPI manifest and boots from the SMC-SRAM manifest path.  The
# manifest+BL1 image it boots is built from source here -- bl1_pass_test is
# compiled and packed by tt-boot-manifest from configs/non_secure_boot_test.yaml,
# then rebased to the SMC-SRAM base.
#
# Outputs (build/, gitignored):
#   boot_rom.vmem     - 64-bit VMEM for the Boot ROM responder
#   boot_rom.itcm.hex - ROM .text as TCM-relative byte hex
#   boot_rom.dtcm.hex - .data/.bss as DCCM-relative byte hex
#   smc_mem.hex       - manifest+BL1 image at the SMC-SRAM base
#
# Prereqs: RISCV_TOOLCHAIN pointing at a picolibc-enabled toolchain bin dir, or
# scripts/docker-run.sh. The packer's Python dependencies come from its
# submodule's pyproject.toml, installed on demand by uv, and stay on the host.
RISCV_TOOLCHAIN ?=
RISCV_PREFIX ?= $(if $(wildcard $(RISCV_TOOLCHAIN)/riscv64-unknown-elf-gcc),riscv64-unknown-elf-,riscv-none-elf-)
GCC_PREFIX ?= $(if $(strip $(RISCV_TOOLCHAIN)),$(patsubst %/,%,$(RISCV_TOOLCHAIN))/$(patsubst %-,%,$(RISCV_PREFIX)),riscv64-unknown-elf)

# hw/sys/sep -- this ROM lives at <sep>/bootrom/prod, the DV tree is its sibling.
SEP_ROOT := $(abspath $(CURDIR)/../..)
DV_ROOT  := $(SEP_ROOT)/dv

OCAH_ROOT := $(abspath $(SEP_ROOT)/../../..)

# Generated SEP register headers, read from the register flow's own output so
# they cannot drift from the RDL the RTL is built from.
include $(OCAH_ROOT)/hw/common/dv/fw/reg_includes.mk
REG_INCLUDE_DIRS := $(call ocah_fw_nonfree_reg_includes,sep) $(call ocah_fw_reg_includes,sep)

ROM_BASE  ?= 0x10040000
DCCM_BASE ?= 0xC0040000

# Full DCCM. Reset does not clear it and explicit_memzero() misses temporaries
# and spilled registers, so this scrub is what keeps key material off the stack.
DCCM_SCRUB_BYTES ?= 0x20000

# Off, and not for speed: rom_clear_ext_sram() runs before the manifest load and
# would wipe the warm handler sep_scratch_7_test preloads at SRAM_BASE + 0x100.
# Stays off until that preload can be staged after the cold-boot scrub.
SRAM_SCRUB_BYTES ?= 0

# MUST be 1 for release: the ICCM clear is what gives ICCM valid ECC, which on
# silicon powers up random. With it off, only the ICCM words the BL1 load writes
# have valid ECC -- not the rest of the image's last 64-bit fetch line when the
# BL1 length is not 8-byte aligned. Off here because the clear costs ~1.8M cycles.
ROM_ICCM_CLEAR_ENABLE ?= 0
PMP_ENABLE ?= 1
PMP_LOCK   ?= 0
BUILD_TYPE ?= test

# SPI flash transport selection. 0 = Cadence xSPI (default, memory-mapped XIP),
# 1 = OpenTitan SPI host (command/FIFO transfers). The unused driver is dropped
# by --gc-sections at link time.
BOOT_SPI_CONTROLLER_OT ?= 0
# OpenTitan RX-FIFO drain method (used only when BOOT_SPI_CONTROLLER_OT=1):
# 0 = secure DMA (default), 1 = CPU programmed I/O.
BOOT_OT_SPI_USE_PIO ?= 0
# OpenTitan timing/device profile index (used only when BOOT_SPI_CONTROLLER_OT=1).
BOOT_OT_SPI_PROFILE ?= 0

BUILD_DIR := build
LINK_DIR  := link
SRC_DIR   := src
TOOLS_DIR := tools
INCLUDE_DIR := include

ELF      := $(BUILD_DIR)/boot_rom.elf
VMEM     := $(BUILD_DIR)/boot_rom.vmem
ITCM_HEX := $(BUILD_DIR)/boot_rom.itcm.hex
DTCM_HEX := $(BUILD_DIR)/boot_rom.dtcm.hex

INSERT_SHA256 := $(TOOLS_DIR)/insert-rom-sha256.py
ELF_TO_VMEM   := $(TOOLS_DIR)/elf-to-vmem.py

# --- manifest+BL1 SMC image (built from source, packed by tt-boot-manifest) ---
BL1_TEST_DIR := $(DV_ROOT)/fw/tests/bl1_pass_test
BL1_TEST_BIN := $(BL1_TEST_DIR)/build/bl1_pass_test.bin
PACK_CONFIG  := $(CURDIR)/configs/non_secure_boot_test.yaml
NS_BOOT_BIN  := $(BUILD_DIR)/non_secure_boot.bin
NS_SPI_HEX   := $(BUILD_DIR)/non_secure_boot.spi_preload
SMC_MEM_HEX  := $(BUILD_DIR)/smc_mem.hex
# SMC-SRAM base the behavioral SMC responder loads the image at (see tb_top.sv
# SEP_SMC_MEM_MODEL + testlist +sep_smc_mem_hex). Verilog-hex @ address (no 0x).
SMC_SRAM_BASE ?= 40060000
BIN_TO_SPI    := $(TOOLS_DIR)/bin_to_spi_preload.py

OBJS := $(BUILD_DIR)/vector.o $(BUILD_DIR)/rom_main.o $(BUILD_DIR)/rom_metadata.o \
	$(BUILD_DIR)/boot_straps.o $(BUILD_DIR)/pll_init.o \
	$(BUILD_DIR)/sep_spi.o $(BUILD_DIR)/sep_ot_spi.o $(BUILD_DIR)/sep_dma.o \
	$(BUILD_DIR)/manifest_load.o $(BUILD_DIR)/rom_handoff.o \
	$(BUILD_DIR)/rom_mem_clear.o $(BUILD_DIR)/status_ring.o \
	$(BUILD_DIR)/hmac_sha256.o $(BUILD_DIR)/fuse_lock.o \
	$(BUILD_DIR)/lifecycle.o $(BUILD_DIR)/manifest_crypto.o \
	$(BUILD_DIR)/rsa_verify.o $(BUILD_DIR)/otbn_driver.o \
	$(BUILD_DIR)/aes_driver.o $(BUILD_DIR)/kdf.o $(BUILD_DIR)/key_digests.o \
	$(BUILD_DIR)/rsa_3072_app_otbn.o

# The secure-boot path verifies the manifest signature on OTBN, so the ROM links
# the generated RSA-3072 OTBN application; the $(OTBN_APP_C) rule regenerates it.
OTBN_APP_DIR := $(DV_ROOT)/fw/build/otbn/rsa_3072_app
OTBN_APP_C   := $(OTBN_APP_DIR)/rsa_3072_app_otbn.c

# Optional extra sources injected by a nonfree overlay build (absolute .c paths).
# Their strong symbols override the weak stubs in src/ at link time (e.g. a
# companion-supplied SPI controller driver overriding the weak src/sep_spi.c
# stub). Same pattern as the SMC prod ROM's NONFREE_DRIVER_SOURCES.
NONFREE_BOOTCODE_SOURCES ?=
NONFREE_BOOTCODE_OBJS := $(patsubst %.c,$(BUILD_DIR)/%.o,$(notdir $(NONFREE_BOOTCODE_SOURCES)))
OBJS += $(NONFREE_BOOTCODE_OBJS)

# rv32im (no C) + no relax. zifencei is spelled out because binutils >= 2.38
# rejects fence.i without it.
CC_ABI   := -march=rv32im_zicsr_zifencei -mabi=ilp32
# The generated register headers need <assert.h> for their packing checks, which
# is not freestanding and only resolves through picolibc's spec file.
CFLAGS   := -Os -ffreestanding -fno-builtin -fdata-sections -ffunction-sections -mno-relax \
	--specs=picolibc.specs \
	-I$(INCLUDE_DIR) -I$(BUILD_DIR) -I$(OTBN_APP_DIR) $(REG_INCLUDE_DIRS) \
	-DDCCM_SCRUB_BYTES=$(DCCM_SCRUB_BYTES) -DSRAM_SCRUB_BYTES=$(SRAM_SCRUB_BYTES) \
	-DPMP_ENABLE=$(PMP_ENABLE) -DPMP_LOCK=$(PMP_LOCK) -DTEST_BUILD=1 -DSEP_BL0 -DDEBUG \
	-DROM_ICCM_CLEAR_ENABLE=$(ROM_ICCM_CLEAR_ENABLE) \
	-DBOOT_SPI_CONTROLLER_OT=$(BOOT_SPI_CONTROLLER_OT) \
	-DBOOT_OT_SPI_USE_PIO=$(BOOT_OT_SPI_USE_PIO) \
	-DBOOT_OT_SPI_PROFILE=$(BOOT_OT_SPI_PROFILE) \
	$(CC_ABI)
ASFLAGS  := -x assembler-with-cpp -mno-relax -I$(INCLUDE_DIR) $(REG_INCLUDE_DIRS) \
	-DDCCM_SCRUB_BYTES=$(DCCM_SCRUB_BYTES) -DPMP_ENABLE=$(PMP_ENABLE) -DPMP_LOCK=$(PMP_LOCK) \
	$(CC_ABI)
LDFLAGS  := -nostdlib -Wl,--gc-sections -Wl,--no-relax -T $(LINK_DIR)/rom.ld $(CC_ABI)

ROM_ELF_SECTIONS := --only-section=.text --only-section=.text.* --only-section=.metadata --only-section=.metadata.* \
	--only-section=.rodata --only-section=.rodata.* --only-section=.srodata --only-section=.srodata.*
# .rodata is deliberately not here: its LMA is in ROM, so claiming it for the
# DTCM image makes objcopy subtract DCCM_BASE from a ROM address and wrap.
DTCM_ELF_SECTIONS := --only-section=.data --only-section=.data.* --only-section=.sdata --only-section=.sdata.* \
	--only-section=.bss --only-section=.bss.* --only-section=.sbss --only-section=.sbss.*

.PHONY: all clean bl1_test ensure-pack-deps toolchain-images toolchain-images-build \
        pack-images ot-toolchain-images ot-pio-toolchain-images
all:
	$(MAKE) toolchain-images
	$(MAKE) pack-images

# OT SPI-host ROM variants, each into its own BUILD_DIR so they coexist. The
# packed flash image is transport-agnostic, so `pack-images` builds it once.
ot-toolchain-images:
	$(MAKE) BUILD_DIR=build_ot BOOT_SPI_CONTROLLER_OT=1 toolchain-images
ot-pio-toolchain-images:
	$(MAKE) BUILD_DIR=build_ot_pio BOOT_SPI_CONTROLLER_OT=1 BOOT_OT_SPI_USE_PIO=1 \
		toolchain-images

# Split by tool dependency so callers can run each half in the right environment:
# toolchain-images needs the RISC-V/picolibc toolchain (i.e. the ocah-toolchain
# container), while pack-images is pure Python and needs cryptography +
# ruamel.yaml, which the container image does not carry. The companion's SEP
# firmware build script drives the two halves this way.
#
# Direct `make toolchain-images` uses only an explicit RISCV_TOOLCHAIN on the
# host. Otherwise it runs the compiler-dependent half in the OCAH container.
OCAH_DOCKER_RUN := $(OCAH_ROOT)/scripts/docker-run.sh

toolchain-images:
	@if [ -n "$(RISCV_TOOLCHAIN)" ]; then \
	  $(MAKE) toolchain-images-build; \
	elif [ -x "$(OCAH_DOCKER_RUN)" ]; then \
	  echo "[bootrom] RISCV_TOOLCHAIN is unset; building in the OCAH toolchain container"; \
	  env -u RISCV_TOOLCHAIN -u RISCV_PREFIX -u MAKEFLAGS -u MFLAGS \
	    "$(OCAH_DOCKER_RUN)" run-here \
	    $(MAKE) -C "$(CURDIR)" \
	    BUILD_DIR="$(BUILD_DIR)" ROM_BASE="$(ROM_BASE)" DCCM_BASE="$(DCCM_BASE)" \
	    DCCM_SCRUB_BYTES="$(DCCM_SCRUB_BYTES)" SRAM_SCRUB_BYTES="$(SRAM_SCRUB_BYTES)" \
	    ROM_ICCM_CLEAR_ENABLE="$(ROM_ICCM_CLEAR_ENABLE)" PMP_ENABLE="$(PMP_ENABLE)" \
	    PMP_LOCK="$(PMP_LOCK)" BUILD_TYPE="$(BUILD_TYPE)" \
	    BOOT_SPI_CONTROLLER_OT="$(BOOT_SPI_CONTROLLER_OT)" \
	    BOOT_OT_SPI_USE_PIO="$(BOOT_OT_SPI_USE_PIO)" \
	    BOOT_OT_SPI_PROFILE="$(BOOT_OT_SPI_PROFILE)" \
	    NONFREE_ROOT="$(NONFREE_ROOT)" \
	    NONFREE_BOOTCODE_SOURCES="$(NONFREE_BOOTCODE_SOURCES)" \
	    RISCV_PREFIX=riscv64-unknown-elf- GCC_PREFIX=riscv64-unknown-elf \
	    toolchain-images-build; \
	else \
	  echo "error: scripts/docker-run.sh is required when RISCV_TOOLCHAIN is unset" >&2; \
	  exit 1; \
	fi

toolchain-images-build: $(VMEM) $(ITCM_HEX) $(DTCM_HEX) bl1_test
pack-images: $(SMC_MEM_HEX)

$(BUILD_DIR):
	mkdir -p "$(BUILD_DIR)"

# --- Rebuild on build-flag changes ---
# Objects are keyed on source mtime but their content depends on the -D flags, so
# without this stamp a variant rebuild silently hands back the previous image.
BUILD_FLAGS := CTRL_OT=$(BOOT_SPI_CONTROLLER_OT) USE_PIO=$(BOOT_OT_SPI_USE_PIO) \
	PROFILE=$(BOOT_OT_SPI_PROFILE) BUILD_TYPE=$(BUILD_TYPE) \
	PMP_ENABLE=$(PMP_ENABLE) PMP_LOCK=$(PMP_LOCK) \
	DCCM_SCRUB=$(DCCM_SCRUB_BYTES) SRAM_SCRUB=$(SRAM_SCRUB_BYTES) \
	NONFREE=$(if $(NONFREE_ROOT),1,0)
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

# Static version header.
$(BUILD_DIR)/bl0_version.h: | $(BUILD_DIR)
	echo '#define BL0_VERSION "oss-nonsecure"' > "$@"

$(BUILD_DIR)/vector.o: $(SRC_DIR)/vector.S | $(BUILD_DIR)
	$(GCC_PREFIX)-gcc $(CFLAGS) $(ASFLAGS) -c "$<" -o "$@"

$(BUILD_DIR)/rom_metadata.o: $(SRC_DIR)/rom_metadata.c $(BUILD_DIR)/bl0_version.h | $(BUILD_DIR)
	$(GCC_PREFIX)-gcc $(CFLAGS) -c "$<" -o "$@"

$(BUILD_DIR)/%.o: $(SRC_DIR)/%.c | $(BUILD_DIR)
	$(GCC_PREFIX)-gcc $(CFLAGS) -c "$<" -o "$@"

# Generated OTBN application image, built out of tree by the shared fw engine.
$(BUILD_DIR)/rsa_3072_app_otbn.o: $(OTBN_APP_C) | $(BUILD_DIR)
	$(GCC_PREFIX)-gcc $(CFLAGS) -c "$<" -o "$@"

$(OTBN_APP_C):
	$(MAKE) -C "$(DV_ROOT)/fw" -f fw.mk OCAH_ROOT="$(OCAH_ROOT)" dv-fw-otbn-apps

# rsa_verify.c/otbn_driver.c include the generated header too (order-only).
$(OBJS): | $(OTBN_APP_C)

# Compile rule for NONFREE_BOOTCODE_SOURCES (static pattern rule so Make maps
# each object back to its out-of-tree source path).
$(NONFREE_BOOTCODE_OBJS): $(BUILD_DIR)/%.o: | $(BUILD_DIR)
	$(GCC_PREFIX)-gcc $(CFLAGS) -c "$(filter %/$*.c,$(NONFREE_BOOTCODE_SOURCES))" -o "$@"

$(ELF): $(OBJS) $(LINK_DIR)/rom.ld
	$(GCC_PREFIX)-gcc $(LDFLAGS) $(OBJS) -o "$@"
	python3 $(INSERT_SHA256) --gcc-prefix $(GCC_PREFIX) -o "$@" "$@" 2>/dev/null || true
	$(GCC_PREFIX)-objdump -d -S "$@" > "$(BUILD_DIR)/boot_rom.dis"
	$(GCC_PREFIX)-nm -B -n "$@" > "$(BUILD_DIR)/boot_rom.sym"

# Boot ROM responder image. elf-to-vmem.py selects sections by LMA, and .data's
# LMA is in ROM (AT> rom), so its initial image lands here too.
$(VMEM): $(ELF) $(ELF_TO_VMEM)
	python3 $(ELF_TO_VMEM) --base $(ROM_BASE) -o "$@" "$(ELF)"

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

# The packer is the tt-boot-manifest repo, checked out as a submodule here rather
# than copied in, so it tracks the upstream repo as that grows.
TT_BOOT_MANIFEST_DIR := $(TOOLS_DIR)/tt-boot-manifest

# --no-project keeps this off the repo-root uv project: the root lockfile must
# stay resolvable in a checkout where submodules were never init'd.
PACK_RUN := uv run --no-project --with-editable "$(TT_BOOT_MANIFEST_DIR)" \
	python -m tt_boot_manifest.pack_images

# A submodule nobody init'd is the likely failure here, and the packer's own error
# for it ("No module named tt_boot_manifest") does not point at the cause.
ensure-pack-deps:
	@test -f "$(TT_BOOT_MANIFEST_DIR)/pyproject.toml" || { \
	  echo "ERROR: the tt-boot-manifest submodule is not checked out."; \
	  echo "       Expected: $(CURDIR)/$(TT_BOOT_MANIFEST_DIR)"; \
	  echo "       Run: git -C $(OCAH_ROOT) submodule update --init \\"; \
	  echo "              hw/sys/sep/bootrom/prod/tools/tt-boot-manifest"; \
	  exit 1; }
	@command -v uv >/dev/null || { \
	  echo "ERROR: uv not found; it installs the manifest packer's Python deps."; \
	  echo "       Install it: https://docs.astral.sh/uv/getting-started/installation/"; \
	  echo "       tools/dv/run_dv.py requires the same tool, so this is a one-off."; \
	  exit 1; }

# manifest+BL1 -> raw image -> Verilog hex -> rebased to the SMC-SRAM base.
# OCH_ROOT resolves the config's payload file_path; ROOT (signing keys) is unused
# for the non-secure config (signature_type 0) so it points at a harmless dir.
$(SMC_MEM_HEX): $(BL1_TEST_BIN) ensure-pack-deps | $(BUILD_DIR)
	OCH_ROOT="$(DV_ROOT)" ROOT="$(TOOLS_DIR)" \
		$(PACK_RUN) --config "$(PACK_CONFIG)" --out "$(NS_BOOT_BIN)" -v
	python3 "$(BIN_TO_SPI)" "$(NS_BOOT_BIN)" "$(NS_SPI_HEX)"
	sed 's/@00000000/@$(SMC_SRAM_BASE)/' "$(NS_SPI_HEX)" > "$@"

# --- signed (secure boot) SPI image ---
# key_digests.c pins ROM key slot 0 to the SHA-256 of the dev0 modulus, so only
# that key produces an image the ROM accepts. $ROOT resolves signing_key_file.
SECURE_PACK_CONFIG := $(CURDIR)/configs/secure_boot_test.yaml
SECURE_BOOT_BIN    := $(BUILD_DIR)/secure_boot.bin
SECURE_SPI_HEX     := $(BUILD_DIR)/secure_boot.spi_preload
SEP_SIGNING_KEY    ?= $(TT_BOOT_MANIFEST_DIR)/tests/signing_keys/rsa_private_key.dev0.pem

.PHONY: secure_boot_spi
secure_boot_spi: $(SECURE_SPI_HEX)

# Fail here with the reason rather than letting the packer die on a missing file
# or, worse, letting the test start and stall waiting for an image nobody built.
$(SECURE_SPI_HEX): $(BL1_TEST_BIN) ensure-pack-deps | $(BUILD_DIR)
	@test -f "$(SEP_SIGNING_KEY)" || { \
	  echo "ERROR: secure boot image needs the dev0 signing key."; \
	  echo "       Expected: $(SEP_SIGNING_KEY)"; \
	  echo "       It ships in the tt-boot-manifest submodule, so this normally means"; \
	  echo "       the submodule is stale; re-run git submodule update, or set"; \
	  echo "       SEP_SIGNING_KEY=<path>. key_digests.c slot 0 pins the accepted key,"; \
	  echo "       so no other key will boot."; \
	  exit 1; }
	OCH_ROOT="$(DV_ROOT)" ROOT="$(abspath $(dir $(SEP_SIGNING_KEY))/../..)" \
		$(PACK_RUN) --config "$(SECURE_PACK_CONFIG)" --out "$(SECURE_BOOT_BIN)" -v
	python3 "$(BIN_TO_SPI)" "$(SECURE_BOOT_BIN)" "$@"

# Encrypted variant of secure_boot_spi. The ROM derives its AES key from the
# CLASS_KEY fuse, so the OTP must carry the config's encryption_key_input.
ENCRYPTED_PACK_CONFIG := $(CURDIR)/configs/encrypted_boot_test.yaml
ENCRYPTED_BOOT_BIN    := $(BUILD_DIR)/encrypted_boot.bin
ENCRYPTED_SPI_HEX     := $(BUILD_DIR)/encrypted_boot.spi_preload

.PHONY: encrypted_boot_spi
encrypted_boot_spi: $(ENCRYPTED_SPI_HEX)

$(ENCRYPTED_SPI_HEX): $(BL1_TEST_BIN) ensure-pack-deps | $(BUILD_DIR)
	@test -f "$(SEP_SIGNING_KEY)" || { \
	  echo "ERROR: encrypted boot image needs the dev0 signing key."; \
	  echo "       Expected: $(SEP_SIGNING_KEY)"; \
	  echo "       The packer rejects encrypted_payload=1 with secure_boot=0, so an"; \
	  echo "       encrypted image is always a signed image."; \
	  exit 1; }
	OCH_ROOT="$(DV_ROOT)" ROOT="$(abspath $(dir $(SEP_SIGNING_KEY))/../..)" \
		$(PACK_RUN) --config "$(ENCRYPTED_PACK_CONFIG)" --out "$(ENCRYPTED_BOOT_BIN)" -v
	python3 "$(BIN_TO_SPI)" "$(ENCRYPTED_BOOT_BIN)" "$@"

# Removes every variant, not just $(BUILD_DIR): a `make clean` that left build_ot/
# behind would let a stale OT image survive into the next run and boot silently.
clean:
	rm -rf "$(BUILD_DIR)" build build_ot build_ot_pio
	$(MAKE) -C "$(BL1_TEST_DIR)" clean 2>/dev/null || true
