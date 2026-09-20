# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Standalone build for the SMC DV boot ROM (dummy stub).
#
# Built on the shared engine (compile.mk) as a "test" named dummy, linked in
# "rom" mode. Drivers, toolchain, and post-processing come from the sibling
# hw/sys/smc/dv/fw tree.
#
# Usage: make [-C hw/sys/smc/bootrom/dummy] [RISCV_TOOLCHAIN=/path/to/bin]
# Unset RISCV_TOOLCHAIN uses scripts/docker-run.sh run-here.

DUMMY_DIR  := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
SMC_FW_DIR := $(abspath $(DUMMY_DIR)/../../dv/fw)
OCAH_ROOT  ?= $(abspath $(DUMMY_DIR)/../../../../..)
OCAH_DOCKER_RUN := $(OCAH_ROOT)/scripts/docker-run.sh
PYTHON ?= python3

# Shared engine inputs (mirror hw/sys/smc/dv/fw/fw.mk).
FW_NAME      := smc
FW_DIR       := $(SMC_FW_DIR)
FW_BUILD_DIR := $(DUMMY_DIR)/build

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

# One fixed test named dummy (source: rom.c, next to this Makefile), opting
# out of compile.mk's directory-based test discovery.
FW_TEST_NAMES        := dummy
FW_TEST_SRC_dummy    := $(DUMMY_DIR)/rom.c
FW_DEFAULT_TEST_MODE := rom

# Shared with hw/sys/smc/dv/fw/fw.mk.
include $(SMC_FW_DIR)/postprocess.mk
FW_TEST_POSTPROCESS_PRIMARY_SUFFIX := .ecc.hex

# Set explicitly: compile.mk's first rule is a directory-creation rule, not 'all'.
FW_DEFAULT_GOAL  := dummy-images
.DEFAULT_GOAL    := all

include $(SMC_FW_DIR)/toolchain.mk
include $(OCAH_ROOT)/hw/common/dv/fw/compile.mk

DUMMY_IMAGE_DIR := $(FW_TEST_BUILD_DIR)/dummy
DUMMY_ELF       := $(DUMMY_IMAGE_DIR)/dummy.rom.elf
DUMMY_BIN       := $(DUMMY_IMAGE_DIR)/dummy.rom.bin

.PHONY: dummy-images toolchain-images toolchain-images-build pack-images
dummy-images:
	$(MAKE) toolchain-images
	$(MAKE) pack-images

toolchain-images:
	@if [ -n "$(RISCV_TOOLCHAIN)" ]; then \
	  $(MAKE) toolchain-images-build; \
	elif [ -x "$(OCAH_DOCKER_RUN)" ]; then \
	  echo "[dummy-rom] RISCV_TOOLCHAIN is unset; building in the OCAH toolchain container"; \
	  env -u RISCV_TOOLCHAIN -u RISCV_PREFIX -u MAKEFLAGS -u MFLAGS \
	    "$(OCAH_DOCKER_RUN)" run-here \
	    $(MAKE) -C "$(DUMMY_DIR)" \
	    RISCV_PREFIX=riscv64-unknown-elf- toolchain-images-build; \
	else \
	  echo "error: scripts/docker-run.sh is required when RISCV_TOOLCHAIN is unset" >&2; \
	  exit 1; \
	fi

toolchain-images-build: $(DUMMY_BIN)

$(DUMMY_BIN): $(DUMMY_ELF)
	$(OBJCOPY) -O binary "$<" "$@"

pack-images:
	@test -f "$(DUMMY_BIN)" || { \
	  echo "error: dummy ROM toolchain image is missing; run 'make toolchain-images' first" >&2; \
	  exit 1; \
	}
	$(PYTHON) "$(FW_DIR)/scripts/bin_to_verilog.py" "$(DUMMY_BIN)" \
	    --data_width 64 --out_file "$(DUMMY_IMAGE_DIR)/dummy.rom.hex"
	$(PYTHON) "$(FW_DIR)/scripts/bin_to_verilog.py" "$(DUMMY_BIN)" \
	    --data_width 1 --out_file "$(DUMMY_IMAGE_DIR)/dummy.rom.spi"
	$(PYTHON) "$(FW_DIR)/scripts/update_smc_hex_to_preload_addr.py" \
	    "$(DUMMY_IMAGE_DIR)/dummy.rom.hex" \
	    --out_file "$(DUMMY_IMAGE_DIR)/dummy.rom.preload.hex"
	$(PYTHON) "$(FW_DIR)/scripts/update_smc_hex_to_preload_addr.py" \
	    "$(DUMMY_IMAGE_DIR)/dummy.rom.spi" \
	    --out_file "$(DUMMY_IMAGE_DIR)/dummy.rom.spi_preload"
	$(PYTHON) "$(FW_DIR)/scripts/bin_to_verilog.py" "$(DUMMY_BIN)" \
	    --data_width 72 --out_file "$(DUMMY_IMAGE_DIR)/dummy.ecc.hex"
