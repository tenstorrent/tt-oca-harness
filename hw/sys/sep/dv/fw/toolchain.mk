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

# Pin the C standard instead of inheriting the compiler default. These test/driver
# sources are C17-era: several call unprototyped functions, which C23 redefines
# (`void f()` means "takes no arguments"), turning what -Wno-implicit-function-
# declaration / -Wno-strict-prototypes used to relax into hard errors on GCC >= 15
# (whose default is -std=gnu23). Pinning gnu17 keeps those relaxations effective
# and makes the build independent of the toolchain's default standard.
FW_STD ?= -std=gnu17

# picolibc must be on both compile and link paths so GCC resolves picolibc's
# headers, not the default newlib ones. Default spec set in compile.mk.
FW_CFLAGS  ?= -march=$(FW_ARCH) -mabi=$(FW_ABI) --specs=$(FW_PICOLIBC_SPECS) $(FW_STD) $(FW_OPT) $(FW_WARNINGS)
FW_ASFLAGS ?= -march=$(FW_ARCH) -mabi=$(FW_ABI)
FW_LDFLAGS ?= \
  -march=$(FW_LD_ARCH) -mabi=$(FW_ABI) \
  -Wl,--gc-sections --specs=$(FW_PICOLIBC_SPECS) -nostartfiles
