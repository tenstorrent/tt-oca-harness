# SPDX-License-Identifier: Apache-2.0
# (c) 2026 Tenstorrent USA Inc

# SMC DV firmware build.
#
# Invoked as a standalone recursive sub-make by hw/dv/fw.mk:
#   make dv-fw TARGET=smc [RISCV_TOOLCHAIN=/path/to/bin]
FW_NAME := smc
FW_DIR  := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
OCAH_ROOT ?= $(abspath $(FW_DIR)/../../../../..)

# Ported SMC runtime driver library (from tt-oca-hw fw/smc/common; see
# doc/dv-firmware.md). This is the full driver library MINUS the out-of-scope
# suites: occp/* (BL0), core_portme.c + ee_printf.c (CoreMark/performance),
# i2c_controller_driver.c (BL0 I2C path), and the unused 1-core "cpl" BSP.
# The DV tests (not ported) supply their own main() and link against this set;
# --gc-sections drops any functions a given image does not use.
#
# Layout mirrors the upstream SiFive Metal include convention (<metal/...>
# rooted at common/), so headers resolve unchanged.
FW_C_SRCS   := $(wildcard $(FW_DIR)/common/*.c $(FW_DIR)/common/drivers/*.c)
FW_ASM_SRCS := $(wildcard $(FW_DIR)/common/*.S)
FW_INCLUDES := \
  -I$(FW_DIR)/common \
  -I$(FW_DIR)/common/drivers \
  -I$(FW_DIR)/common/metal \
  -I$(FW_DIR)/common/metal/drivers \
  -I$(FW_DIR)/common/metal/smc

# Register headers. The umbrella smc.h is hand-maintained under hw/common/dv/fw
# and includes generated headers by basename. Overlay generated dirs come first
# so same-named adopter shim headers override the open placeholders.
OCAH_SMC_REG_GEN_C := $(OCAH_ROOT)/hw/sys/smc/regs/gen/c
OCAH_SMC_ADOPTER_OVERLAY_FW_INCLUDE_DIRS ?= \
  $(wildcard $(OCAH_ROOT)/overlay/*/hw/sys/smc/regs/gen/c) \
  $(wildcard $(OCAH_ROOT)/overlay/*/hw/sys/smc/dv/shims/regs/gen/c) \
  $(wildcard $(OCAH_ROOT)/overlay/*/hw/ip/*/dv/shims/regs/gen/c)
OCAH_ADOPTER_OVERLAY_FW_INCLUDE_DIRS ?=
FW_INCLUDES += \
  -I$(OCAH_ROOT)/hw/common/dv/fw \
  $(addprefix -I,$(OCAH_ADOPTER_OVERLAY_FW_INCLUDE_DIRS)) \
  $(addprefix -I,$(OCAH_SMC_ADOPTER_OVERLAY_FW_INCLUDE_DIRS)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/nonfree/vendor/*/hw/sys/smc/regs/gen/c)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/nonfree/vendor/*/hw/sys/smc/dv/shims/regs/gen/c)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/nonfree/vendor/*/hw/ip/*/dv/shims/regs/gen/c)) \
  -I$(OCAH_SMC_REG_GEN_C) \
  -I$(OCAH_SMC_REG_GEN_C)/blocks \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/hw/sys/smc/dv/shims/regs/gen/c)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/hw/ip/*/dv/shims/regs/gen/c)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/hw/ip/*/regs/gen/c))

include $(FW_DIR)/toolchain.mk
include $(OCAH_ROOT)/hw/common/dv/fw/common.mk
