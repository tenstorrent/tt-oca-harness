SHELL := /bin/bash
#
# OSS SEP Boot ROM (non-secure ROM boot test subset).
#
# A trimmed copy of fw/sep/bootcode adapted for the OSS DV flow:
#   * SPI is stubbed (src/sep_spi.c) -- the OSS `sep` DUT has no Cadence xSPI, so
#     the ROM skips the SPI manifest and boots from the SMC-SRAM manifest path.
#   * RSA/OTBN are stubbed (src/rsa_verify.c, src/otbn_driver.c) -- non-secure
#     boot never uses them, which drops the OTBN assembler toolchain dependency.
#
# The manifest+BL1 image the ROM boots (from the SMC-SRAM path) is built entirely
# from source in this tree: bl1_pass_test (../tests/bl1_pass_test) is compiled and
# packed by the real tt-boot-manifest packer (vendored under tools/tt_boot_manifest,
# a copy of fw/deps/tt-boot-manifest/src -- NOT a rewrite) using configs/
# non_secure_boot_test.yaml, then rebased to the SMC-SRAM base -> build/smc_mem.hex.
# The old flow that sed-rebased fw/sep/bootcode/prebuilt/non_secure_boot.spi_preload
# is gone; nothing here depends on the internal prebuilt blob.
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
# The packer needs Python 'cryptography' and 'ruamel.yaml'
# (pip3 install --user cryptography ruamel.yaml).

GCC_PREFIX ?= riscv64-unknown-elf

# SEP DV root (bootcode is 2 dirs deep under it: <dv>/fw/bootcode). Everything
# this build needs lives at or below <dv> so the OSS DV tree is self-contained
# (no reach above the DV tree). The SEP top register header (och_sep_top_reg.h) is
# vendored into include/, so no external meta/registers/c include is needed.
DV_ROOT := $(abspath $(CURDIR)/../..)

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
BL1_TEST_DIR := $(CURDIR)/../tests/bl1_pass_test
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
	$(BUILD_DIR)/aes_driver.o $(BUILD_DIR)/kdf.o $(BUILD_DIR)/key_digests.o

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
CFLAGS   := -Os -ffreestanding -fno-builtin -fdata-sections -ffunction-sections -mno-relax \
	-I$(INCLUDE_DIR) -I$(BUILD_DIR) \
	-DDCCM_SCRUB_BYTES=$(DCCM_SCRUB_BYTES) -DSRAM_SCRUB_BYTES=$(SRAM_SCRUB_BYTES) \
	-DPMP_ENABLE=$(PMP_ENABLE) -DPMP_LOCK=$(PMP_LOCK) -DTEST_BUILD=1 -DSEP_BL0 -DDEBUG \
	-DBOOT_SPI_CONTROLLER_OT=$(BOOT_SPI_CONTROLLER_OT) \
	-DBOOT_OT_SPI_USE_PIO=$(BOOT_OT_SPI_USE_PIO) \
	-DBOOT_OT_SPI_PROFILE=$(BOOT_OT_SPI_PROFILE) \
	$(CC_ABI)
ASFLAGS  := -x assembler-with-cpp -mno-relax -I$(INCLUDE_DIR) \
	-DDCCM_SCRUB_BYTES=$(DCCM_SCRUB_BYTES) -DPMP_ENABLE=$(PMP_ENABLE) -DPMP_LOCK=$(PMP_LOCK) \
	$(CC_ABI)
LDFLAGS  := -nostdlib -Wl,--gc-sections -Wl,--no-relax -T $(LINK_DIR)/rom.ld $(CC_ABI)

ROM_ELF_SECTIONS := --only-section=.text --only-section=.text.* --only-section=.metadata --only-section=.metadata.* \
	--only-section=.rodata --only-section=.rodata.* --only-section=.srodata --only-section=.srodata.*
DTCM_ELF_SECTIONS := --only-section=.rodata --only-section=.rodata.* --only-section=.srodata --only-section=.srodata.* \
	--only-section=.data --only-section=.data.* --only-section=.sdata --only-section=.sdata.* \
	--only-section=.bss --only-section=.bss.* --only-section=.sbss --only-section=.sbss.*

.PHONY: all clean bl1_test ensure-pack-deps
all: $(VMEM) $(ITCM_HEX) $(DTCM_HEX) $(SMC_MEM_HEX)

$(BUILD_DIR):
	mkdir -p "$(BUILD_DIR)"

# Static version header (the internal build derives this from git; not needed here).
$(BUILD_DIR)/bl0_version.h: | $(BUILD_DIR)
	echo '#define BL0_VERSION "oss-nonsecure"' > "$@"

$(BUILD_DIR)/vector.o: $(SRC_DIR)/vector.S | $(BUILD_DIR)
	$(GCC_PREFIX)-gcc $(CFLAGS) $(ASFLAGS) -c "$<" -o "$@"

$(BUILD_DIR)/rom_metadata.o: $(SRC_DIR)/rom_metadata.c $(BUILD_DIR)/bl0_version.h | $(BUILD_DIR)
	$(GCC_PREFIX)-gcc $(CFLAGS) -c "$<" -o "$@"

$(BUILD_DIR)/%.o: $(SRC_DIR)/%.c | $(BUILD_DIR)
	$(GCC_PREFIX)-gcc $(CFLAGS) -c "$<" -o "$@"

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

$(DTCM_HEX): $(ELF)
	$(GCC_PREFIX)-objcopy -O verilog "$(ELF)" $(DTCM_ELF_SECTIONS) --change-addresses "-$(DCCM_BASE)" "$@"

# --- manifest+BL1 SMC image ---
# Build the BL1 payload (bl1_pass_test) from source. Phony so the recursive make
# owns its own up-to-date check and we always re-pack against the latest BL1.
bl1_test:
	$(MAKE) -C "$(BL1_TEST_DIR)" GCC_PREFIX=$(GCC_PREFIX)

# The packer runs as `python3 -m tt_boot_manifest.pack_images`; tt_boot_manifest
# is vendored under tools/, so PYTHONPATH=tools makes it importable. OCH_ROOT
# resolves the config's payload file_path; ROOT (signing keys) is unused for the
# non-secure config (signature_type 0) so it points at a harmless local dir.
ensure-pack-deps:
	@python3 -c "import cryptography, ruamel.yaml" 2>/dev/null || \
		{ echo "ERROR: manifest packer needs Python 'cryptography' and 'ruamel.yaml'."; \
		  echo "       Install: pip3 install --user cryptography ruamel.yaml"; exit 1; }

# manifest+BL1 -> raw image -> Verilog hex -> rebased to the SMC-SRAM base.
$(SMC_MEM_HEX): bl1_test ensure-pack-deps | $(BUILD_DIR)
	PYTHONPATH="$(TOOLS_DIR)$(if $(PYTHONPATH),:$(PYTHONPATH))" OCH_ROOT="$(DV_ROOT)" ROOT="$(TOOLS_DIR)" \
		python3 -m tt_boot_manifest.pack_images --config "$(PACK_CONFIG)" --out "$(NS_BOOT_BIN)" -v
	python3 "$(BIN_TO_SPI)" "$(NS_BOOT_BIN)" "$(NS_SPI_HEX)"
	sed 's/@00000000/@$(SMC_SRAM_BASE)/' "$(NS_SPI_HEX)" > "$@"

clean:
	rm -rf "$(BUILD_DIR)"
	$(MAKE) -C "$(BL1_TEST_DIR)" clean 2>/dev/null || true
