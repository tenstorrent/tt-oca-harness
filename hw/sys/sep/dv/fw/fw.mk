# SPDX-License-Identifier: Apache-2.0
# (c) 2026 Tenstorrent USA Inc

# SEP DV firmware build.
#
# Invoked as a standalone recursive sub-make by hw/dv/fw.mk:
#   make dv-fw TARGET=sep [RISCV_TOOLCHAIN=/path/to/bin]
FW_NAME := sep
FW_DIR  := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
OCAH_ROOT ?= $(abspath $(FW_DIR)/../../../../..)

# Ported runtime sources (from tt-oca-hw fw/sep/tests/common; see
# doc/dv-firmware.md). Tests supply their own main() and
# link against the runtime library produced here.
FW_C_SRCS   := $(wildcard $(FW_DIR)/common/*.c)
FW_ASM_SRCS := $(wildcard $(FW_DIR)/common/*.s $(FW_DIR)/common/*.S)
FW_INCLUDES := -I$(FW_DIR)/include

# Register headers. The umbrella sep.h is hand-maintained under hw/common/dv/fw
# and includes generated headers by basename. Overlay generated dirs come first
# so same-named adopter shim headers override the open placeholders.
OCAH_SEP_REG_GEN_C := $(OCAH_ROOT)/hw/sys/sep/regs/gen/c
OCAH_SEP_ADOPTER_OVERLAY_FW_INCLUDE_DIRS ?= \
  $(wildcard $(OCAH_ROOT)/overlay/*/hw/sys/sep/regs/gen/c) \
  $(wildcard $(OCAH_ROOT)/overlay/*/hw/sys/sep/dv/shims/regs/gen/c) \
  $(wildcard $(OCAH_ROOT)/overlay/*/hw/ip/*/dv/shims/regs/gen/c)
OCAH_ADOPTER_OVERLAY_FW_INCLUDE_DIRS ?=
FW_INCLUDES += \
  -I$(OCAH_ROOT)/hw/common/dv/fw \
  $(addprefix -I,$(OCAH_ADOPTER_OVERLAY_FW_INCLUDE_DIRS)) \
  $(addprefix -I,$(OCAH_SEP_ADOPTER_OVERLAY_FW_INCLUDE_DIRS)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/nonfree/vendor/*/hw/sys/sep/regs/gen/c)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/nonfree/vendor/*/hw/sys/sep/dv/shims/regs/gen/c)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/nonfree/vendor/*/hw/ip/*/dv/shims/regs/gen/c)) \
  -I$(OCAH_SEP_REG_GEN_C) \
  -I$(OCAH_SEP_REG_GEN_C)/blocks \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/hw/sys/sep/dv/shims/regs/gen/c)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/hw/ip/*/dv/shims/regs/gen/c)) \
  $(addprefix -I,$(wildcard $(OCAH_ROOT)/hw/ip/*/regs/gen/c))

# Full SEP compile additionally needs the VeeR EL2 snapshot (defines.h with
# ICCM/DCCM addresses). That snapshot is not vendored; see toolchain.mk +
# doc/dv-firmware.md. Until it is provided, `all` builds libsep_fw.a from the
# staged runtime sources.

include $(FW_DIR)/toolchain.mk
include $(OCAH_ROOT)/hw/common/dv/fw/common.mk
