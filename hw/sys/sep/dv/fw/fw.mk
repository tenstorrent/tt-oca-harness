# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# SEP DV firmware build.
#
# Built via the DV firmware dispatcher: make dv-fw-libs TARGET=sep
FW_NAME := sep
FW_DIR  := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
include $(FW_DIR)/../../../../common/dv/fw/preamble.mk

# Runtime sources. Tests supply their own main() and link against libsep.a.
FW_C_SRCS   := $(wildcard $(FW_DIR)/drivers/*.c)
FW_ASM_SRCS := $(wildcard $(FW_DIR)/startup/*.s $(FW_DIR)/startup/*.S $(FW_DIR)/drivers/*.S)
FW_INCLUDES := -I$(FW_DIR)/include

# Register headers via the shared engine helper (umbrella sep.h under
# hw/common/dv/fw + this sys's generated headers).
FW_REG_SYS := sep

# Test discovery is unified in compile.mk; declare only the SEP deltas.
FW_TEST_EXCLUDE_NAMES := bl1_pass_test
FW_TEST_INCLUDES := -I$(FW_DIR)/tests/common
FW_TEST_COMMON_SRCS := $(FW_DIR)/tests/common/sha256.c
# Test sources predate strict prototypes / native register headers; keep these
# relaxations so they compile unchanged.
FW_TEST_EXTRA_CFLAGS += \
  -Wno-implicit-function-declaration \
  -Wno-incompatible-pointer-types \
  -Wno-strict-prototypes
# Only one link mode exists today: link/modes/tcm.ld, auto-discovered by
# compile.mk. A second mode only requires adding another link/modes/<mode>.ld.
FW_DEFAULT_TEST_MODE := tcm
FW_TEST_LDFLAGS = $(FW_LDFLAGS)

define FW_TEST_POSTPROCESS
	$(OBJCOPY) -O verilog $(1) --only-section=.text --only-section=.nmi_handler \
	  --change-addresses "-0xC0000000" "$(FW_TEST_BUILD_DIR)/$(2)/$(2).itcm.hex"
	$(OBJCOPY) -O verilog $(1) \
	  --only-section=.data --only-section=.sdata --only-section=.rodata --only-section=.srodata \
	  --only-section=.bss --only-section=.sbss \
	  --change-addresses "-0xC0040000" "$(FW_TEST_BUILD_DIR)/$(2)/$(2).dtcm.hex"
endef

# A full SEP compile also needs the external VeeR EL2 snapshot (see toolchain.mk).
# Until then `all` just builds libsep.a.

include $(FW_DIR)/toolchain.mk
include $(OCAH_ROOT)/hw/common/dv/fw/compile.mk
