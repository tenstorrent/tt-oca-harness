# Build bl1_pass_test as a single flat binary for SRAM execution.
#
# Produces:
#   build/bl1_pass_test.bin  — flat binary for SRAM (code + data)
#
# IFU and LSU both access SRAM via the AXI system bus, so all sections
# (.text, .rodata, .data, .bss) are linked into a single SRAM region.
#
# Self-contained: no RV_ROOT / OCH_ROOT / picolibc dependencies.
# No crt0 needed — BL1 inherits CPU state (SP, PMA, mtvec) from the ROM.
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

CFLAGS  = -Os -ffreestanding -fno-builtin \
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
