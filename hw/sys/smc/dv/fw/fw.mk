# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# SMC DV firmware build.
#
# Built via the DV firmware dispatcher: make dv-fw-libs TARGET=smc
FW_NAME := smc
FW_DIR  := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
include $(FW_DIR)/../../../../common/dv/fw/preamble.mk

# SMC runtime driver library. DV tests supply main() and link against it. Layout
# follows the SiFive Metal include convention rooted at include/metal.
FW_C_SRCS   := $(wildcard $(FW_DIR)/drivers/*.c)
FW_ASM_SRCS := $(wildcard $(FW_DIR)/startup/*.s $(FW_DIR)/startup/*.S $(FW_DIR)/drivers/*.S)
FW_INCLUDES := \
  -I$(FW_DIR)/include \
  -I$(FW_DIR)/include/metal \
  -I$(FW_DIR)/include/metal/drivers \
  -I$(FW_DIR)/include/metal/smc

# Register headers via the shared engine helper (umbrella smc.h under
# hw/common/dv/fw + this sys's generated headers).
FW_REG_SYS := smc

# Test discovery is unified in compile.mk; declare only the SMC deltas. coremark
# pulls in the shared core_portme.c harness alongside its own source.
FW_TEST_EXTRA_SRCS_coremark := $(FW_DIR)/tests/core_portme.c
FW_TEST_INCLUDES := -I$(FW_DIR)/tests
# Test sources predate strict prototypes / native register headers; keep these
# relaxations so they compile unchanged.
FW_TEST_EXTRA_CFLAGS += \
  -Wno-incompatible-pointer-types \
  -Wno-implicit-function-declaration \
  -Wno-implicit-int \
  -Wno-strict-prototypes
# Test images link against one of link/modes/{sram,rom}.ld (auto-discovered by
# compile.mk); dv/fw/tests/ defaults to sram (bare main, no crt0). A test opts
# into another mode with FW_TEST_MODE_<name> := rom.
FW_DEFAULT_TEST_MODE := sram
# Link against picolibc like the SEP/KM flows: sram-mode test images keep their
# own entry (-Wl,-e,main) and skip crt0 (-nostartfiles), resolving libc/libm
# from picolibc. (A future rom-mode test under dv/fw/tests/ would need crt0's
# _enter instead -- see hw/sys/smc/bootrom/dummy/Makefile.)
FW_TEST_LDFLAGS = \
  $(FW_OPT) -Wl,--gc-sections -Wl,--as-needed \
  -Wl,--defsym=__stack_size=4K -Wl,--defsym=__heap_size=2K \
  -Wl,--no-relax -Wl,-e,main -nostartfiles \
  -march=$(FW_ARCH) -mabi=$(FW_ABI) --specs=$(FW_PICOLIBC_SPECS) -lgcc
FW_TEST_ARCHIVE_LINK = "$(FW_ARCHIVE)"

# Shared with hw/sys/smc/bootrom/dummy/Makefile so both SMC build entry points
# post-process a linked test image the same way.
include $(FW_DIR)/postprocess.mk

include $(FW_DIR)/toolchain.mk
include $(OCAH_ROOT)/hw/common/dv/fw/compile.mk
