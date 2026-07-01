# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# SEP DV firmware toolchain settings.
#
# Target CPU: VeeR EL2 (RV32IMC + Zicsr/Zifencei/Zb*), ilp32 ABI. picolibc via
# --specs=picolibc.specs, provided by the Docker toolchain (not bundled).
#
# A full SEP compile also needs the VeeR EL2 snapshot (not bundled); set
# FW_SEP_SNAPSHOT_DIR to enable it. Until then the link/hex stages are gated.
FW_ARCH    ?= rv32imc_zicsr_zifencei_zba_zbb_zbc
FW_LD_ARCH ?= rv32imac
FW_ABI     ?= ilp32

FW_WARNINGS ?= -Wall -Wextra
FW_OPT ?= -Os -fdata-sections -ffunction-sections -fno-common -fstack-usage

# picolibc must be on both compile and link paths so GCC resolves picolibc's
# headers, not the default newlib ones. Default spec set in compile.mk.
FW_CFLAGS  ?= -march=$(FW_ARCH) -mabi=$(FW_ABI) --specs=$(FW_PICOLIBC_SPECS) $(FW_OPT) $(FW_WARNINGS)
FW_ASFLAGS ?= -march=$(FW_ARCH) -mabi=$(FW_ABI)
FW_LDFLAGS ?= \
  -march=$(FW_LD_ARCH) -mabi=$(FW_ABI) \
  -Wl,--gc-sections --specs=$(FW_PICOLIBC_SPECS) -nostartfiles
