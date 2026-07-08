# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# key_manager DV firmware build.
#
# Built via the DV firmware dispatcher: make dv-fw TARGET=key_manager
FW_NAME := key_manager
FW_DIR  := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
include $(FW_DIR)/../../../../common/dv/fw/preamble.mk

# Runtime driver/startup sources. rom_main.c (the production entry) is excluded:
# DV tests / the production build supply the entry and link against libkey_manager.a.
FW_C_SRCS   := $(wildcard $(FW_DIR)/drivers/*.c)
FW_ASM_SRCS := $(wildcard $(FW_DIR)/startup/*.s $(FW_DIR)/startup/*.S $(FW_DIR)/drivers/*.S)

# Register headers: KM uses only its own generated headers (no umbrella), so
# FW_REG_SYS is left unset.
FW_REGS_GEN := $(OCAH_ROOT)/hw/ip/key_manager/regs/gen/c
FW_INCLUDES := \
  -I$(FW_DIR)/include -I$(FW_REGS_GEN)

# Test discovery is unified in compile.mk; declare only the KM deltas.
FW_TEST_INCLUDES := -I$(FW_DIR)/tests/common
# Only one link mode exists today: link/modes/vrom.ld, auto-discovered by
# compile.mk. A second mode only requires adding another link/modes/<mode>.ld.
FW_DEFAULT_TEST_MODE := vrom
FW_TEST_LDFLAGS = \
  $(FW_LDFLAGS) -Wl,--defsym=__rom_max_stack=0x600
FW_TEST_ARCHIVE_LINK = "$(FW_ARCHIVE)"

define FW_TEST_POSTPROCESS
	$(OBJCOPY) -O verilog $(1) \
	  --only-section=.text.reset --only-section=.text.irq_vec --only-section=.text.irq_handler \
	  --change-addresses "-0x00000000" "$(FW_TEST_BUILD_DIR)/$(2)/$(2).rom.hex"
	python3 "$(FW_DIR)/scripts/add_rom_parity.py" "$(FW_TEST_BUILD_DIR)/$(2)/$(2).rom.hex" "$(FW_TEST_BUILD_DIR)/$(2)/$(2).rom.parhex"
	$(OBJCOPY) -O verilog $(1) \
	  --only-section=.text --only-section=.text.alt_irq --only-section=.rodata --only-section=.data \
	  --change-addresses "-0x10000000" "$(FW_TEST_BUILD_DIR)/$(2)/$(2).vrom.hex"
endef

# Default artifact: libkey_manager.a. A linked ELF/hex additionally requires
# FW_LINKER_SCRIPT and FW_ENTRY_SRCS (a DV/production entry providing main()).

include $(FW_DIR)/toolchain.mk
include $(OCAH_ROOT)/hw/common/dv/fw/compile.mk
