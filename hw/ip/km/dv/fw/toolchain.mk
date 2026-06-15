# SPDX-License-Identifier: Apache-2.0
# (c) 2026 Tenstorrent USA Inc

# KM DV firmware toolchain settings.
#
# Target CPU: PicoRV32, RV32E (16 registers), multiply + compressed.
# RV32E requires the ilp32e ABI. Bare metal: no libc (-nostdlib / -ffreestanding).
# Mirrors tt-oca-hw/hw/comp/key_manager/tb/firmware/Makefile.
FW_ARCH ?= rv32emc
FW_ABI  ?= ilp32e
FW_SMALL_DATA ?= -msmall-data-limit=16

FW_WARNINGS ?= \
  -Wall -Wextra -Werror -std=c11 -Wpedantic \
  -Wshadow -Wundef -Wcast-align -Wcast-qual \
  -Wconversion -Wsign-conversion \
  -Wstrict-prototypes -Wmissing-prototypes -Wredundant-decls \
  -Wnull-dereference -Wswitch-enum \
  -Wduplicated-cond -Wduplicated-branches -Wlogical-op \
  -Wformat=2 -Wstack-usage=512

FW_OPT ?= \
  -Os -ffreestanding -fno-builtin -fno-tree-loop-distribute-patterns \
  -fdata-sections -ffunction-sections -fno-common -fno-unwind-tables \
  -fno-asynchronous-unwind-tables -fomit-frame-pointer -flto

FW_CFLAGS  ?= -march=$(FW_ARCH) -mabi=$(FW_ABI) $(FW_SMALL_DATA) $(FW_OPT) $(FW_WARNINGS)
FW_ASFLAGS ?= -march=$(FW_ARCH) -mabi=$(FW_ABI)
# VROM-linked DV images keep -mno-relax to avoid unsafe long-jump relaxations.
# --undefined=memcpy keeps rom_memcpy's memcpy alias alive under LTO + gc-sections.
FW_LDFLAGS ?= \
  -march=$(FW_ARCH) -mabi=$(FW_ABI) -mno-relax -flto \
  -Wl,--gc-sections -Wl,--undefined=memcpy -nostartfiles -nostdlib
