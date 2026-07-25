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

# rom_main: the real KM production ROM, built from tracked KM firmware source
# (hw/comp/key_manager/firmware/src/rom_main.c) via the KM tb firmware Makefile.
# PROD_BOOT_WIPE=0 / PROD_UNREC_WIPE=0 disable the boot/unrecoverable-fault SRAM
# shred so rom_main's SRAM-scrambler cold-boot does not trip a parity fault on the
# behavioral SRAM responder -- matching the OCAH subsystem tb. The output is
# gitignored (not a committed blob). Requires the rv32emc/ilp32e toolchain on PATH
# (module load riscv-gnu-toolchain/2025.01.20-rhel-8.10).
# FIXME(SEP-DV): rom_main cannot build in this repository yet -- the KM tb
# firmware tree (legacy hw/comp/key_manager/tb/firmware) was not ported; the
# key manager now lives at hw/ip/key_manager without a tb/ directory. The 5
# tests consuming rom_main.rom.parhex stay blocked until it is restored.
OCH_ROOT ?= $(abspath $(CURDIR)/../../../../../../..)
KM_FW_TB := $(OCH_ROOT)/hw/ip/key_manager/tb/firmware

rom_main:
	$(MAKE) -C $(KM_FW_TB) clean build_production \
	    FW_SRC=$(OCH_ROOT)/hw/comp/key_manager/firmware/src/rom_main.c \
	    BUILD_DIR=build/rom_main PROD_BOOT_WIPE=0 PROD_UNREC_WIPE=0
	cp $(KM_FW_TB)/build/rom_main/rom_main.rom.parhex $(OUT_DIR)/rom_main.rom.parhex
	@echo "[km_fw] staged rom_main.rom.parhex -> $(OUT_DIR)/rom_main.rom.parhex"

$(OUT_DIR)/%.parhex: %.S gen_parhex.py
	$(RISCV_CC) -nostdlib -march=rv32i -mabi=ilp32 -Ttext=0 -o $*.elf $<
	$(RISCV_OBJCOPY) -O binary $*.elf $*.bin
	$(PYTHON) gen_parhex.py $*.bin > $@

clean:
	rm -f *.elf *.bin $(PARHEX) $(OUT_DIR)/rom_main.rom.parhex
	rm -rf $(KM_FW_TB)/build/rom_main
