# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Standalone build for the open-source SMC DV boot ROM (dummy stub).
#
# Built on the shared engine (compile.mk) as a "test" named dummy, linked in
# "rom" mode. Drivers, toolchain, and post-processing come from the sibling
# hw/sys/smc/dv/fw tree.
#
# Usage: make [-C hw/sys/smc/bootrom/dummy] [RISCV_TOOLCHAIN=/path/to/bin]

DUMMY_DIR  := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
SMC_FW_DIR := $(abspath $(DUMMY_DIR)/../../dv/fw)
OCAH_ROOT  ?= $(abspath $(DUMMY_DIR)/../../../../..)

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

# Set explicitly: compile.mk's first rule is a directory-creation rule, not 'all'.
FW_DEFAULT_GOAL  := dv-fw-tests
.DEFAULT_GOAL    := all

include $(SMC_FW_DIR)/toolchain.mk
include $(OCAH_ROOT)/hw/common/dv/fw/compile.mk
