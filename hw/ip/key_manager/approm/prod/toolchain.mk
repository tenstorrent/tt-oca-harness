# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# Key Manager application ROM compiler, assembler and linker flags.
#
# Target CPU: PicoRV32, RV32EMC, ilp32e ABI, bare metal (-nostdlib).
# picolibc.specs supplies compile-time headers only; picolibc is not linked in.
KM_ARCH ?= rv32emc
KM_ABI  ?= ilp32e
KM_PICOLIBC_SPECS ?= picolibc.specs

KM_WARNINGS ?= \
  -Wall -Wextra -Werror -std=c11 -Wpedantic \
  -Wshadow -Wundef -Wcast-align -Wcast-qual \
  -Wconversion -Wsign-conversion \
  -Wstrict-prototypes -Wmissing-prototypes -Wredundant-decls \
  -Wnull-dereference -Wswitch-enum \
  -Wduplicated-cond -Wduplicated-branches -Wlogical-op \
  -Wformat=2 -Wstack-usage=512

KM_OPT ?= \
  -Os -ffreestanding -fno-builtin -fno-tree-loop-distribute-patterns \
  -fdata-sections -ffunction-sections -fno-common -fno-unwind-tables \
  -fno-asynchronous-unwind-tables -fomit-frame-pointer -flto

KM_CFLAGS  ?= -march=$(KM_ARCH) -mabi=$(KM_ABI) --specs=$(KM_PICOLIBC_SPECS) -msmall-data-limit=16 $(KM_OPT) $(KM_WARNINGS)
KM_ASFLAGS ?= -march=$(KM_ARCH) -mabi=$(KM_ABI)

# --undefined=memcpy keeps rom_memcpy's memcpy alias alive under LTO + gc-sections.
# __rom_max_stack is the worst-case ROM main-stack budget; km_sram_layout.ld bounds
# the mutable firmware load area by it.
KM_LDFLAGS ?= \
  -march=$(KM_ARCH) -mabi=$(KM_ABI) -flto \
  -Wl,--gc-sections -Wl,--undefined=memcpy -nostartfiles -nostdlib \
  -Wl,--defsym=__rom_max_stack=0x600
