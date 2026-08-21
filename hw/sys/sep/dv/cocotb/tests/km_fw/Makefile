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
OCH_ROOT ?= $(abspath $(CURDIR)/../../../../../../..)
KM_FW_DIR := $(OCH_ROOT)/hw/ip/key_manager/dv/fw
KM_ROM_BUILT := $(KM_FW_DIR)/build/tests/rom_main/rom_main.rom.parhex

# The wipe knobs are COMPILE-TIME DEFINES, not make variables. Upstream's KM tb
# Makefile maps PROD_BOOT_WIPE/PROD_UNREC_WIPE onto them, but the shared DV
# firmware engine has no such mapping -- passing PROD_* here is silently ignored
# and drivers/rom_boot.c falls back to its `#ifndef` defaults of 1 (wipe ENABLED).
# A rom_main built that way runs ~24k instructions, performs the production boot
# wipe and HALTS before posting RESP_KM_READY, which reads exactly like a dead KM
# (km_rom_req_count stops at a fixed value; the mailbox never produces a word).
#
# rom_boot.c is a DRIVER, not a test source, so the define must ride
# FW_EXTRA_CFLAGS (compile.mk applies it to the driver rule);
# FW_TEST_EXTRA_CFLAGS is test-only and would not reach it.
ROM_MAIN_WIPE_DEFINES := -DROM_KM_BOOT_WIPE_DEFAULT=0 -DROM_KM_UNREC_WIPE_DEFAULT=0

# The defines above are COMPILE flags, and compile.mk's dependency tracking
# (-MMD -MP) records HEADER dependencies only -- it cannot see a CFLAGS change.
# So an object left over from a build that did not pass them would be silently
# reused, re-enabling the boot wipe and reproducing the exact dead-KM symptom
# these tests were once parked for.
#
# The object that carries these defines is NOT under build/tests/. rom_boot.c is
# a DRIVER, and compile.mk:118 places driver objects FLAT in $(FW_BUILD_DIR)
# via $(addprefix $(FW_BUILD_DIR)/,$(notdir ...)), while tests go to
# $(FW_BUILD_DIR)/tests (compile.mk:127). So the stale artifacts are
#     $(KM_FW_DIR)/build/rom_boot.o
#     $(KM_FW_DIR)/build/libkey_manager.a
# which are SIBLINGS of build/tests/rom_main -- wiping only the test directory
# leaves them untouched and they get re-linked verbatim. Wipe the whole build
# tree instead; it only happens when the defines actually change.
# Outside $(KM_FW_DIR)/build on purpose: the guard below wipes that whole
# tree, which would delete the stamp it is about to compare against.
ROM_MAIN_STAMP := $(OUT_DIR)/.km_rom_wipe_defines
.PHONY: rom_main_stamp
rom_main_stamp:
	@mkdir -p $(dir $(ROM_MAIN_STAMP))
	@if [ "$$(cat $(ROM_MAIN_STAMP) 2>/dev/null)" != "$(ROM_MAIN_WIPE_DEFINES)" ]; then \
	    echo "[km_fw] wipe defines changed -> rebuilding KM firmware from scratch"; \
	    rm -rf $(KM_FW_DIR)/build; \
	fi

rom_main: rom_main_stamp
	$(MAKE) -C $(KM_FW_DIR) -f fw.mk dv-fw-tests TEST=rom_main \
	    OCAH_ROOT=$(OCH_ROOT) FW_EXTRA_CFLAGS="$(ROM_MAIN_WIPE_DEFINES)"
	@mkdir -p $(dir $(ROM_MAIN_STAMP))
	@printf '%s' "$(ROM_MAIN_WIPE_DEFINES)" > $(ROM_MAIN_STAMP)
	cp $(KM_ROM_BUILT) $(OUT_DIR)/rom_main.rom.parhex
	@echo "[km_fw] staged rom_main.rom.parhex -> $(OUT_DIR)/rom_main.rom.parhex"

$(OUT_DIR)/%.parhex: %.S gen_parhex.py
	$(RISCV_CC) -nostdlib -march=rv32i -mabi=ilp32 -Ttext=0 -o $*.elf $<
	$(RISCV_OBJCOPY) -O binary $*.elf $*.bin
	$(PYTHON) gen_parhex.py $*.bin > $@

clean:
	rm -f *.elf *.bin $(PARHEX) $(OUT_DIR)/rom_main.rom.parhex
	# Whole build tree, not just build/tests/rom_main: the driver objects that
	# carry the wipe defines (rom_boot.o, libkey_manager.a) live flat in build/.
	rm -rf $(KM_FW_DIR)/build
