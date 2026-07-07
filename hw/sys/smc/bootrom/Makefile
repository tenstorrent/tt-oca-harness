# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Standalone build for the open-source SMC DV boot ROM (dv_rom).
#
# Delegates to the shared firmware build engine (compile.mk); driver sources,
# toolchain settings, linker script, and post-process scripts are all
# referenced from the sibling open DV FW tree (../dv/fw). Nothing is
# duplicated here.
#
# Usage: make [-C hw/sys/smc/bootrom] [RISCV_TOOLCHAIN=/path/to/bin]

BOOTROM_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
SMC_FW_DIR  := $(abspath $(BOOTROM_DIR)/../dv/fw)
OCAH_ROOT   ?= $(abspath $(BOOTROM_DIR)/../../../..)

# Shared engine inputs (mirror hw/sys/smc/dv/fw/fw.mk).
FW_NAME      := smc
FW_DIR       := $(SMC_FW_DIR)
FW_BUILD_DIR := $(BOOTROM_DIR)/build

FW_C_SRCS   := $(wildcard $(SMC_FW_DIR)/drivers/*.c)
FW_ASM_SRCS := $(wildcard $(SMC_FW_DIR)/startup/*.s $(SMC_FW_DIR)/startup/*.S \
                           $(SMC_FW_DIR)/drivers/*.S)
FW_INCLUDES  := -I$(SMC_FW_DIR)/include -I$(SMC_FW_DIR)/include/metal \
                -I$(SMC_FW_DIR)/include/metal/drivers -I$(SMC_FW_DIR)/include/metal/smc
FW_REG_SYS  := smc

# IP dv/shims headers (e.g. efuse_shim_ctrl.h) are not covered by
# compile.mk's wildcard; inject via the overlay variable.
OCAH_FW_REG_OVERLAY_INCLUDE_DIRS_smc := \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/hw/ip/*/dv/shims/regs/gen/c)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/hw/ip/*/*/dv/shims/regs/gen/c))

FW_TEST_EXTRA_CFLAGS += \
  -Wno-incompatible-pointer-types -Wno-implicit-function-declaration \
  -Wno-implicit-int -Wno-strict-prototypes

# ROM image: one ROM boot image; source lives in this directory.
FW_ROM_LINKER_SCRIPT  := $(SMC_FW_DIR)/link/smc_rom.ld
FW_ROM_TEST_BUILD_DIR := $(FW_BUILD_DIR)
FW_ROM_TEST_NAMES     := dv_rom
FW_ROM_TEST_SRC_dv_rom := $(BOOTROM_DIR)/dv_rom.c

define FW_ROM_TEST_POSTPROCESS
	$(OBJCOPY) -O binary $(1) "$(FW_ROM_TEST_BUILD_DIR)/$(2)/test.rom.bin"
	python3 "$(FW_DIR)/scripts/bin_to_verilog.py" "$(FW_ROM_TEST_BUILD_DIR)/$(2)/test.rom.bin" \
	  --data_width 64 --out_file "$(FW_ROM_TEST_BUILD_DIR)/$(2)/test.rom.hex"
	python3 "$(FW_DIR)/scripts/bin_to_verilog.py" "$(FW_ROM_TEST_BUILD_DIR)/$(2)/test.rom.bin" \
	  --data_width 1  --out_file "$(FW_ROM_TEST_BUILD_DIR)/$(2)/test.rom.spi"
	python3 "$(FW_DIR)/scripts/update_smc_hex_to_preload_addr.py" \
	  "$(FW_ROM_TEST_BUILD_DIR)/$(2)/test.rom.hex" \
	  --out_file "$(FW_ROM_TEST_BUILD_DIR)/$(2)/test.rom.preload.hex"
	python3 "$(FW_DIR)/scripts/update_smc_hex_to_preload_addr.py" \
	  "$(FW_ROM_TEST_BUILD_DIR)/$(2)/test.rom.spi" \
	  --out_file "$(FW_ROM_TEST_BUILD_DIR)/$(2)/test.rom.spi_preload"
endef

# dv-fw-rom-tests builds the ROM elf + all post-processed outputs.
# .DEFAULT_GOAL must be set explicitly; compile.mk's first rule would otherwise
# become the default (it's a directory-creation rule, not 'all').
FW_DEFAULT_GOAL  := dv-fw-rom-tests
.DEFAULT_GOAL    := all

include $(SMC_FW_DIR)/toolchain.mk
include $(OCAH_ROOT)/hw/common/dv/fw/compile.mk
