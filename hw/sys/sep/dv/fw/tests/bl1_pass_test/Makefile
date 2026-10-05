# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Build bl1_pass_test as a single flat binary for ICCM execution.
#
# Produces:
#   build/bl1_pass_test.bin  — flat binary for ICCM (.text + .data's load image)
#
# .text runs from ICCM; .rodata/.data/.bss run from DCCM because the EL2 DMA
# port rejects sub-word ICCM accesses.  The blob therefore holds .text followed
# by .data's ICCM load image, and _start copies that down to DCCM.  See bl1.ld.
#
# Builds with no picolibc and no crt0. It includes only the boot ROM bl0_state.h
# and the generated sep_addr.h.
# No crt0 needed — BL1 inherits CPU state (SP, PMA, mtvec) from the ROM, and
# does its own .data copy and .bss clear at the top of _start.
#
# Usage:
#   make                              # uses riscv64-elf prefix
#   make GCC_PREFIX=riscv64-unknown-elf

GCC_PREFIX ?= riscv64-elf

CC      = $(GCC_PREFIX)-gcc
OBJCOPY = $(GCC_PREFIX)-objcopy
OBJDUMP = $(GCC_PREFIX)-objdump
NM      = $(GCC_PREFIX)-nm
SIZE    = $(GCC_PREFIX)-size

MARCH  = rv32im_zicsr
MABI   = ilp32

BUILD_DIR = build

# -MMD/-MP: bl1_pass_test.c reads bl0_state from the address and layout the
# ROM's include/bl0_state.h defines, so a change there must force a rebuild.
CFLAGS  = -Os -ffreestanding -fno-builtin -MMD -MP \
          -fdata-sections -ffunction-sections \
          -mno-relax -march=$(MARCH) -mabi=$(MABI)

LDFLAGS = -nostdlib -Wl,--gc-sections -Wl,--no-relax \
          -T bl1.ld -march=$(MARCH) -mabi=$(MABI)

ELF = $(BUILD_DIR)/bl1_pass_test.elf
BIN = $(BUILD_DIR)/bl1_pass_test.bin

OBJS = $(BUILD_DIR)/bl1_pass_test.o

.PHONY: all clean

all: $(BIN)

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(BUILD_DIR)/bl1_pass_test.o: bl1_pass_test.c | $(BUILD_DIR)
	$(CC) $(CFLAGS) -c $< -o $@

$(ELF): $(OBJS) bl1.ld
	$(CC) $(LDFLAGS) $(OBJS) -o $@
	$(OBJDUMP) -d -S $@ > $(BUILD_DIR)/bl1_pass_test.dis
	$(NM) -B -n $@ > $(BUILD_DIR)/bl1_pass_test.sym
	$(SIZE) $@

$(BIN): $(ELF)
	$(OBJCOPY) -O binary $< $@
	@echo "BL1 binary: $@ ($$(stat -f%z $@ 2>/dev/null || stat -c%s $@) bytes)"

clean:
	rm -rf $(BUILD_DIR)

-include $(OBJS:.o=.d)
