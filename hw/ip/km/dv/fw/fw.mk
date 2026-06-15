# SPDX-License-Identifier: Apache-2.0
# (c) 2026 Tenstorrent USA Inc

# KM DV firmware build.
#
# Invoked as a standalone recursive sub-make by hw/dv/fw.mk:
#   make dv-fw TARGET=km [RISCV_TOOLCHAIN=/path/to/bin]
FW_NAME := km
FW_DIR  := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
OCAH_ROOT ?= $(abspath $(FW_DIR)/../../../../..)

# Ported runtime sources (from tt-oca-hw key_manager firmware; see
# doc/dv-firmware.md). rom_main.c (the production entry)
# is intentionally excluded: DV tests / the production build supply the entry and
# link against the runtime library produced here.
FW_C_SRCS   := $(wildcard $(FW_DIR)/drivers/*.c)
FW_ASM_SRCS := $(wildcard $(FW_DIR)/startup/*.s $(FW_DIR)/startup/*.S $(FW_DIR)/drivers/*.S)
FW_INCLUDES := -I$(FW_DIR)/include

# Default artifact: libkm_fw.a (compiles + assembles the ported runtime).
# A linked ELF/hex additionally requires:
#   FW_LINKER_SCRIPT = $(FW_DIR)/link/km_exec_from_vrom.ld
#   FW_ENTRY_SRCS    = <a DV/production entry providing main()>
# which is gated on the deferred register-header reconciliation (KM drivers
# include key_manager_regs.h in tt-oca-hw's *_reg_u format; tt-oca emits a
# different peakrdl c-header). See doc/dv-firmware.md.

include $(FW_DIR)/toolchain.mk
include $(OCAH_ROOT)/hw/common/dv/fw/common.mk
