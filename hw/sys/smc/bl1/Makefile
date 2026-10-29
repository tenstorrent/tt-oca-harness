# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Reference SMC BL1, and the test fixtures that replace its main().
#
#   make                          # debug build: build/debug/smc_bl1.{elf,bin,dis}
#   make BUILD_TYPE=release       # defines SMU_BL1_RELEASE, no console
#   make RISCV_TOOLCHAIN=<bin>    # build on the host instead of the toolchain container
#
# A fixture build passes NAME, MAIN_SRC and OUT_DIR; release builds refuse it.

BUILD_TYPE ?= debug
NAME       ?= smc_bl1

SMC_BL1_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
OCAH_ROOT   ?= $(abspath $(SMC_BL1_DIR)/../../../..)
OCAH_DOCKER_RUN := $(OCAH_ROOT)/scripts/docker-run.sh
SMC_ROM_DIR := $(OCAH_ROOT)/hw/sys/smc/bootrom/prod

MAIN_SRC ?= $(SMC_BL1_DIR)/src/main.c
BUILD_DIR ?= $(SMC_BL1_DIR)/build
OUT_DIR   ?= $(BUILD_DIR)/$(BUILD_TYPE)

ifneq ($(MAIN_SRC),$(SMC_BL1_DIR)/src/main.c)
  ifeq ($(BUILD_TYPE),release)
    $(error release builds refuse the test fixture $(NAME))
  endif
endif

OCAH_FW_REG_OVERLAY_INCLUDE_DIRS_smc :=
include $(OCAH_ROOT)/hw/common/dv/fw/reg_includes.mk

RISCV_TOOLCHAIN ?=
_TC_PREFIX := $(if $(RISCV_TOOLCHAIN),$(RISCV_TOOLCHAIN)/)
GCC := $(_TC_PREFIX)riscv64-unknown-elf-gcc
OC  := $(_TC_PREFIX)riscv64-unknown-elf-objcopy
OD  := $(_TC_PREFIX)riscv64-unknown-elf-objdump

# No F or D: mstatus.FS is off after the reset pulse that starts SMC BL1.
ARCH := rv64imac_zicsr_zifencei
ABI  := lp64
PICOLIBC_SPECS ?= picolibc.specs
ARCHFLAGS := -march=$(ARCH) -mabi=$(ABI) -mcmodel=medany -mno-relax -mstrict-align

ifeq ($(BUILD_TYPE),debug)
  BUILD_DEFINES := -DDEBUG=1
else ifeq ($(BUILD_TYPE),release)
  BUILD_DEFINES := -DSMU_BL1_RELEASE=1 -DNDEBUG=1
else
  $(error BUILD_TYPE must be debug or release, not $(BUILD_TYPE))
endif

INCLUDES := -I$(SMC_BL1_DIR)/include -I$(OCAH_ROOT)/hw/sys/smu/bl1/include \
	-I$(SMC_ROM_DIR)/include -I$(SMC_ROM_DIR)/lib/include \
	$(call ocah_fw_reg_includes,smc) -I$(OCAH_ROOT)/hw/sys/sep/regs/gen/c

CFLAGS := -std=c11 -Os -g $(ARCHFLAGS) $(BUILD_DEFINES) $(INCLUDES) \
	-ffreestanding -fno-builtin -fno-common -ffunction-sections -fdata-sections \
	-Wall -Wextra -Werror --specs=$(PICOLIBC_SPECS) -MMD -MP
LDFLAGS := $(ARCHFLAGS) -nostdlib -nostartfiles -static \
	-Wl,--gc-sections -Wl,--no-relax -Wl,--orphan-handling=error \
	-Wl,-Map=$(OUT_DIR)/$(NAME).map

SRCS := $(SMC_BL1_DIR)/src/start.S $(SMC_BL1_DIR)/src/ring.c $(SMC_BL1_DIR)/src/post.c \
	$(SMC_BL1_DIR)/src/mailbox.c $(MAIN_SRC)
OBJ_DIR := $(OUT_DIR)/obj/$(NAME)
OBJS := $(foreach s,$(SRCS),$(OBJ_DIR)/$(basename $(notdir $(s))).o)
LD_SCRIPT := $(OBJ_DIR)/smc_bl1.ld

ELF := $(OUT_DIR)/$(NAME).elf
BIN := $(OUT_DIR)/$(NAME).bin
DIS := $(OUT_DIR)/$(NAME).dis

.PHONY: all toolchain-images toolchain-images-build check-multilib clean
all: toolchain-images

toolchain-images:
	@if [ -n "$(RISCV_TOOLCHAIN)" ]; then \
	  $(MAKE) -f $(SMC_BL1_DIR)/Makefile toolchain-images-build; \
	elif [ -x "$(OCAH_DOCKER_RUN)" ]; then \
	  echo "[smc_bl1] RISCV_TOOLCHAIN is unset; building in the OCAH toolchain container"; \
	  env -u RISCV_TOOLCHAIN -u MAKEFLAGS -u MFLAGS \
	    "$(OCAH_DOCKER_RUN)" run-here \
	    $(MAKE) -f "$(SMC_BL1_DIR)/Makefile" \
	    BUILD_TYPE="$(BUILD_TYPE)" NAME="$(NAME)" MAIN_SRC="$(MAIN_SRC)" \
	    BUILD_DIR="$(BUILD_DIR)" OUT_DIR="$(OUT_DIR)" toolchain-images-build; \
	else \
	  echo "error: scripts/docker-run.sh is required when RISCV_TOOLCHAIN is unset" >&2; \
	  exit 1; \
	fi

toolchain-images-build: check-multilib $(ELF) $(BIN) $(DIS)

# Without an lp64 multilib, GCC silently falls back to the default lp64d one.
check-multilib:
	@dir=$$($(GCC) -march=$(ARCH) -mabi=$(ABI) --specs=$(PICOLIBC_SPECS) \
	  -print-multi-directory); \
	case "$$dir" in */$(ABI)) ;; \
	  *) echo "error: $(GCC) has no picolibc multilib for $(ARCH)/$(ABI) (got '$$dir')" >&2; \
	     exit 1 ;; \
	esac

$(OBJ_DIR)/%.o: $(SMC_BL1_DIR)/src/%.S
	@mkdir -p $(@D)
	$(GCC) $(CFLAGS) -c -o $@ $<

$(OBJ_DIR)/%.o: $(SMC_BL1_DIR)/src/%.c
	@mkdir -p $(@D)
	$(GCC) $(CFLAGS) -c -o $@ $<

$(OBJ_DIR)/$(basename $(notdir $(MAIN_SRC))).o: $(MAIN_SRC)
	@mkdir -p $(@D)
	$(GCC) $(CFLAGS) -c -o $@ $<

$(LD_SCRIPT): $(SMC_BL1_DIR)/link/smc_bl1.ld $(SMC_BL1_DIR)/include/smc_bl1_layout.h
	@mkdir -p $(@D)
	$(GCC) -E -P -x c -I$(SMC_BL1_DIR)/include -o $@ $<

$(ELF): $(OBJS) $(LD_SCRIPT)
	$(GCC) $(LDFLAGS) -T $(LD_SCRIPT) -o $@ $(OBJS)

$(BIN): $(ELF)
	$(OC) -O binary $< $@

$(DIS): $(ELF)
	$(OD) -d -S $< > $@

clean:
	rm -rf $(BUILD_DIR)

-include $(OBJS:.o=.d)
