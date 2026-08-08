# SPDX-License-Identifier: Apache-2.0

GCC_PREFIX ?= riscv64-unknown-elf
RISCV_CC ?= $(GCC_PREFIX)-gcc
RISCV_OBJCOPY ?= $(GCC_PREFIX)-objcopy
PYTHON ?= python3

OUT_DIR := ..
ROMS := km_rom_entropy km_rom_coexist
PARHEX := $(addprefix $(OUT_DIR)/,$(addsuffix .parhex,$(ROMS)))

.PHONY: all clean rom_main

all: $(PARHEX)

# rom_main: the real KM production ROM, built from tracked KM firmware source.
# PROD_BOOT_WIPE=0 / PROD_UNREC_WIPE=0 disable the boot/unrecoverable-fault SRAM
# shred so rom_main's SRAM-scrambler cold-boot does not trip a parity fault --
# matching the OCAH subsystem tb. The output is gitignored (not a committed blob).
# Requires the rv32emc/ilp32e toolchain on PATH.
#
# The firmware is in-tree at hw/ip/key_manager/dv/fw and builds through the shared
# DV firmware engine, the same one SEP's own firmware uses; the entry point is
# production/rom_main and the engine's parity step emits rom_main.rom.parhex.
# (This target previously drove a `hw/ip/key_manager/tb/firmware` tree from a
# `hw/comp/key_manager/...` source path -- both leftovers from the old repository
# layout that never existed here.)
OCH_ROOT ?= $(abspath $(CURDIR)/../../../../../../..)
KM_FW_DIR := $(OCH_ROOT)/hw/ip/key_manager/dv/fw
KM_ROM_BUILT := $(KM_FW_DIR)/build/tests/rom_main/rom_main.rom.parhex

rom_main:
	$(MAKE) -C $(KM_FW_DIR) -f fw.mk dv-fw-tests TEST=rom_main \
	    OCAH_ROOT=$(OCH_ROOT) PROD_BOOT_WIPE=0 PROD_UNREC_WIPE=0
	cp $(KM_ROM_BUILT) $(OUT_DIR)/rom_main.rom.parhex
	@echo "[km_fw] staged rom_main.rom.parhex -> $(OUT_DIR)/rom_main.rom.parhex"

$(OUT_DIR)/%.parhex: %.S gen_parhex.py
	$(RISCV_CC) -nostdlib -march=rv32i -mabi=ilp32 -Ttext=0 -o $*.elf $<
	$(RISCV_OBJCOPY) -O binary $*.elf $*.bin
	$(PYTHON) gen_parhex.py $*.bin > $@

clean:
	rm -f *.elf *.bin $(PARHEX) $(OUT_DIR)/rom_main.rom.parhex
	rm -rf $(KM_FW_DIR)/build/tests/rom_main
