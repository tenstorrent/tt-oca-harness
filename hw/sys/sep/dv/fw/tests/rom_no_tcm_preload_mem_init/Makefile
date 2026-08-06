# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# Pure-assembly ROM image; not built by the shared fw engine (compile.mk only
# discovers C tests). Build standalone, like bl1_pass_test.

TEST = rom_no_tcm_preload_mem_init

GCC_PREFIX ?= riscv64-unknown-elf
ROM_BASE ?= 0x10040000

BUILD_DIR = build

ELF = $(BUILD_DIR)/$(TEST).elf
VMEM = $(BUILD_DIR)/$(TEST).vmem

CC_ABI = -march=rv32im_zicsr_zifencei -mabi=ilp32
ASFLAGS = $(CC_ABI) -mno-relax -I../common
LDFLAGS = -nostdlib -Wl,--gc-sections -Wl,--no-relax -T rom_only.ld $(CC_ABI)

.PHONY: all clean

all: $(ELF) $(VMEM)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(BUILD_DIR)/$(TEST).o: $(TEST).S | $(BUILD_DIR)
	$(GCC_PREFIX)-gcc $(ASFLAGS) -c $< -o $@

$(ELF): $(BUILD_DIR)/$(TEST).o rom_only.ld
	$(GCC_PREFIX)-gcc $(LDFLAGS) $(BUILD_DIR)/$(TEST).o -o $@
	$(GCC_PREFIX)-objdump -d -S $@ > $(BUILD_DIR)/$(TEST).dis
	$(GCC_PREFIX)-nm -B -n $@ > $(BUILD_DIR)/$(TEST).sym

$(VMEM): $(ELF)
	python3 ../../bootcode/tools/elf-to-vmem.py \
		--base $(ROM_BASE) --gcc-prefix $(GCC_PREFIX) -o $@ $<

clean:
	rm -rf $(BUILD_DIR)
