SHELL := /bin/bash
#
# OSS SEP Boot ROM (non-secure ROM boot test subset).
#
# A trimmed copy of fw/sep/bootcode adapted for the OSS DV flow:
#   * SPI is stubbed (src/sep_spi.c) -- the OSS `sep` DUT has no Cadence xSPI, so
#     the ROM skips the SPI manifest and boots from the SMC-SRAM manifest path.
#
# The manifest+BL1 image the ROM boots (from the SMC-SRAM path) is built entirely
# from source in this tree: bl1_pass_test (<sep>/dv/fw/tests/bl1_pass_test) is compiled and
# packed by the real tt-boot-manifest packer from the tools/tt-boot-manifest
# submodule, using configs/non_secure_boot_test.yaml, then rebased to the SMC-SRAM
# base -> build/smc_mem.hex. The old flow that sed-rebased
# fw/sep/bootcode/prebuilt/non_secure_boot.spi_preload is gone; nothing here
# depends on the internal prebuilt blob.
#
# Code (.text) links to Boot ROM (ROM_BASE) -> loaded via +sep_boot_rom_hex.
# Data (.rodata/.data/.bss) links to DCCM -> backdoor-loaded via the TCM responder.
#
# Outputs (build/, gitignored):
#   boot_rom.vmem     - 64-bit VMEM for the Boot ROM responder ($readmemh)
#   boot_rom.itcm.hex - ROM .text as TCM-relative byte hex (legacy/optional)
#   boot_rom.dtcm.hex - .rodata/.data/.bss as DCCM-relative byte hex
#   smc_mem.hex       - manifest+BL1 image at SMC-SRAM base (+sep_smc_mem_hex)
#
# Prereqs: riscv toolchain in PATH (default riscv64-unknown-elf-*). No picolibc.
# The packer's Python dependencies come from the submodule's own pyproject.toml,
# installed on demand by uv -- see PACK_RUN below.

GCC_PREFIX ?= riscv64-unknown-elf

# hw/sys/sep -- this ROM lives at <sep>/bootrom/prod, the DV tree is its sibling.
SEP_ROOT := $(abspath $(CURDIR)/../..)
DV_ROOT  := $(SEP_ROOT)/dv

OCAH_ROOT := $(abspath $(SEP_ROOT)/../../..)

# Generated SEP register headers (sep.h umbrella, sep_addr.h, per-block headers),
# emitted by the open register flow next to the RDL they come from
# (`make ocah-regen-regs`). They used to be copies vendored into include/;
# reading the generated ones instead is what keeps them from drifting away from
# the RDL the RTL is built from. This build drives itself rather than going
# through compile.mk, so it borrows that engine's include set verbatim.
include $(OCAH_ROOT)/hw/common/dv/fw/reg_includes.mk
REG_INCLUDE_DIRS := $(call ocah_fw_nonfree_reg_includes,sep) $(call ocah_fw_reg_includes,sep)

ROM_BASE  ?= 0x10040000
DCCM_BASE ?= 0xC0040000

# DCCM/SRAM scrub disabled for DV (backdoor preloads with correct ECC; the CPU
# store loop is extremely slow in RTL sim). Matches the internal bootcode default.
DCCM_SCRUB_BYTES ?= 0
SRAM_SCRUB_BYTES ?= 0
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
# the same generated RSA-3072 OTBN application the fw test engine builds. The
# app (IMEM/DMEM images + DMEM symbol offsets) is emitted by the shared engine
# under <sep>/dv/fw/build/otbn/; the $(OTBN_APP_C) rule below regenerates it.
OTBN_APP_DIR := $(DV_ROOT)/fw/build/otbn/rsa_3072_app
OTBN_APP_C   := $(OTBN_APP_DIR)/rsa_3072_app_otbn.c

# Optional extra sources injected by a nonfree overlay build (absolute .c paths).
# Their strong symbols override the weak stubs in src/ at link time (e.g. the
# Cadence xSPI driver nonfree/hw/sys/sep/dv/fw/bootcode/src/sep_spi_cdns.c
# overriding the weak src/sep_spi.c stub). Same pattern as the SMC prod ROM's
# NONFREE_DRIVER_SOURCES.
NONFREE_BOOTCODE_SOURCES ?=
NONFREE_BOOTCODE_OBJS := $(patsubst %.c,$(BUILD_DIR)/%.o,$(notdir $(NONFREE_BOOTCODE_SOURCES)))
OBJS += $(NONFREE_BOOTCODE_OBJS)

# rv32im (no C) + no relax, matching the internal ROM build. zifencei is spelled
# out because binutils >= 2.38 rejects fence.i (rom_handoff.c) without it.
CC_ABI   := -march=rv32im_zicsr_zifencei -mabi=ilp32
# The ROM itself is freestanding and links -nostdlib, but the generated register
# headers close their packing checks with static_assert, i.e. <assert.h>. That is
# not a freestanding header, and in the toolchain container it only resolves
# through the picolibc spec file - hence the specs on the compile line only.
CFLAGS   := -Os -ffreestanding -fno-builtin -fdata-sections -ffunction-sections -mno-relax \
	--specs=picolibc.specs \
	-I$(INCLUDE_DIR) -I$(BUILD_DIR) -I$(OTBN_APP_DIR) $(REG_INCLUDE_DIRS) \
	-DDCCM_SCRUB_BYTES=$(DCCM_SCRUB_BYTES) -DSRAM_SCRUB_BYTES=$(SRAM_SCRUB_BYTES) \
	-DPMP_ENABLE=$(PMP_ENABLE) -DPMP_LOCK=$(PMP_LOCK) -DTEST_BUILD=1 -DSEP_BL0 -DDEBUG \
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
# .rodata/.srodata are deliberately NOT here: link/rom.ld keeps read-only data in
# the ROM image (VMA just past .text, e.g. 0x1004_4348) and ROM_ELF_SECTIONS above
# already carries it. Claiming it for the DTCM image too made objcopy subtract
# DCCM_BASE from a ROM address, wrapping negative (@FFFFFFFF5000_4348) and failing
# the load with "$readmem file address beyond bounds of array".
DTCM_ELF_SECTIONS := --only-section=.data --only-section=.data.* --only-section=.sdata --only-section=.sdata.* \
	--only-section=.bss --only-section=.bss.* --only-section=.sbss --only-section=.sbss.*

.PHONY: all clean bl1_test ensure-pack-deps toolchain-images pack-images \
        ot-toolchain-images ot-pio-toolchain-images
all: toolchain-images pack-images

# OpenTitan SPI-host ROM variants. Same sources, built with the OT transport
# selected (boot_flash.h picks the driver on BOOT_SPI_CONTROLLER_OT) and each into
# its own BUILD_DIR so the variants coexist instead of clobbering one another.
# Named targets rather than raw knobs: the variant-to-directory mapping is the
# thing that must not be got wrong, so it lives here and not in every caller.
#
# These build the ROM only. The packed flash image is transport- and
# drain-agnostic -- the same manifest+BL1 bytes are what any of the three ROMs
# read -- so it is built ONCE by `pack-images` into the default build/ and shared.
# Packing it per variant would be pure duplication with three copies to drift.
ot-toolchain-images:
	$(MAKE) BUILD_DIR=build_ot BOOT_SPI_CONTROLLER_OT=1 toolchain-images
ot-pio-toolchain-images:
	$(MAKE) BUILD_DIR=build_ot_pio BOOT_SPI_CONTROLLER_OT=1 BOOT_OT_SPI_USE_PIO=1 \
		toolchain-images

# Split by tool dependency so callers can run each half in the right environment:
# toolchain-images needs the RISC-V/picolibc toolchain (i.e. the ocah-toolchain
# container), while pack-images is pure Python and needs cryptography +
# ruamel.yaml, which the container image does not carry. See
# nonfree/hw/sys/sep/dv/tb/scripts/build_sep_fw_tests.sh.
toolchain-images: $(VMEM) $(ITCM_HEX) $(DTCM_HEX) bl1_test
pack-images: $(SMC_MEM_HEX)

$(BUILD_DIR):
	mkdir -p "$(BUILD_DIR)"

# --- Rebuild on build-flag changes ---
# Objects are keyed on source mtime only, but their content also depends on the
# -D flags injected into CFLAGS/ASFLAGS. Without this, `make BOOT_OT_SPI_USE_PIO=1`
# over an existing build dir finds every .o newer than its source, does nothing,
# and hands back the PREVIOUS variant under the new name -- a ROM that boots and
# passes, but is not the one asked for. Record the codegen-affecting flags in a
# stamp, rewrite it only when they actually change (so unchanged builds stay
# incremental), and make every object depend on it.
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

# Static version header (the internal build derives this from git; not needed here).
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

# Boot ROM responder image. elf-to-vmem.py selects allocatable sections by load
# address (LMA): .text/.metadata/.rodata/.srodata reside in ROM, and .data's
# initial image has a ROM LMA (AT> rom) even though it executes from DCCM, so it
# lands in the ROM image and vector.S copies it to DCCM at boot.
$(VMEM): $(ELF) $(ELF_TO_VMEM)
	python3 $(ELF_TO_VMEM) --base $(ROM_BASE) -o "$@" "$(ELF)"

$(ITCM_HEX): $(ELF)
	$(GCC_PREFIX)-objcopy -O verilog "$(ELF)" $(ROM_ELF_SECTIONS) --change-addresses "-$(ROM_BASE)" "$@"

# DCCM preload image. `objcopy -O verilog` emits by LOAD address, and .data's LMA is
# in ROM (`AT> rom` in link/rom.ld) even though its VMA is DCCM -- so rebasing by
# DCCM_BASE subtracted a DCCM base from a ROM address and wrapped negative
# (@FFFFFFFF5000_4EA8), which fails the load with "$readmem file address beyond
# bounds of array". Rebase by __data_load_start (= LOADADDR(.data), the symbol
# link/rom.ld exports for exactly this) so the emitted addresses are DCCM-relative
# offsets. .bss is NOLOAD and contributes no bytes; vector.S still performs the real
# ROM->DCCM copy at boot, so this image only pre-stages identical content.
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

# The packer is the tt-boot-manifest repo, checked out as a submodule here rather
# than copied in, so it tracks the upstream repo as that grows.
TT_BOOT_MANIFEST_DIR := $(TOOLS_DIR)/tt-boot-manifest

# uv installs the packer editable straight from the submodule, which means its
# Python dependencies come from the submodule's own pyproject.toml -- no
# requirements.txt to keep in sync and no pip3 install for a caller to forget.
# --no-project keeps this off the repo-root uv project: the root lockfile must stay
# resolvable in a checkout where submodules were never init'd, or every other uv
# caller (lint, docs) breaks along with this one.
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
$(SMC_MEM_HEX): bl1_test ensure-pack-deps | $(BUILD_DIR)
	OCH_ROOT="$(DV_ROOT)" ROOT="$(TOOLS_DIR)" \
		$(PACK_RUN) --config "$(PACK_CONFIG)" --out "$(NS_BOOT_BIN)" -v
	python3 "$(BIN_TO_SPI)" "$(NS_BOOT_BIN)" "$(NS_SPI_HEX)"
	sed 's/@00000000/@$(SMC_SRAM_BASE)/' "$(NS_SPI_HEX)" > "$@"

# --- signed (secure boot) SPI image ---
# sep_rom_secure_boot_test and sep_rom_ot_secure_boot_test load this image to
# exercise the RSA-3072 signature check. Same packer as the non-secure image; the
# config just turns on secure_boot and names a signing key.
#
# key_digests.c pins slot 0 to the SHA-256 of the dev0 modulus, so only that exact
# key produces an image the ROM will accept. It is a test key that ships in the
# tt-boot-manifest repo, so the submodule brings it along and this builds with no
# extra setup -- $ROOT is what the config resolves signing_key_file against.
#
# To move to a key of your own, generate one, regenerate the digest table with
# tools/generate_key_digests.py, and commit both.
SECURE_PACK_CONFIG := $(CURDIR)/configs/secure_boot_test.yaml
SECURE_BOOT_BIN    := $(BUILD_DIR)/secure_boot.bin
SECURE_SPI_HEX     := $(BUILD_DIR)/secure_boot.spi_preload
SEP_SIGNING_KEY    ?= $(TT_BOOT_MANIFEST_DIR)/tests/signing_keys/rsa_private_key.dev0.pem

.PHONY: secure_boot_spi
secure_boot_spi: $(SECURE_SPI_HEX)

# Fail here with the reason rather than letting the packer die on a missing file
# or, worse, letting the test start and stall waiting for an image nobody built.
$(SECURE_SPI_HEX): bl1_test ensure-pack-deps | $(BUILD_DIR)
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

# Removes every variant, not just $(BUILD_DIR): a `make clean` that left build_ot/
# behind would let a stale OT image survive into the next run and boot silently.
clean:
	rm -rf "$(BUILD_DIR)" build build_ot build_ot_pio
	$(MAKE) -C "$(BL1_TEST_DIR)" clean 2>/dev/null || true
