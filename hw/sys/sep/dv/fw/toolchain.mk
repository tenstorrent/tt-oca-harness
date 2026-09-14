# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# SEP DV firmware toolchain settings.
#
# Target CPU: VeeR EL2 (RV32IMC + Zicsr/Zifencei/Zb*), ilp32 ABI. picolibc via
# --specs=picolibc.specs, provided by the Docker toolchain (not bundled).
#
# Zb* is absent from the default. GCC emits sh2add and
# rev8 for ordinary C, and those trap as illegal instructions on the EL2 config
# this testbench runs, so all but a handful of tests are built without the
# bit-manip extensions. FW_ARCH_BITMANIP is the opt-in for the tests that are
# built with them; see FW_TEST_BITMANIP in fw.mk.
FW_ARCH          ?= rv32imc_zicsr_zifencei
FW_ARCH_BITMANIP ?= rv32imc_zicsr_zifencei_zba_zbb_zbc
FW_LD_ARCH       ?= rv32imac
FW_ABI           ?= ilp32

FW_WARNINGS ?= -Wall -Wextra
FW_OPT ?= -Os -fdata-sections -ffunction-sections -fno-common -fstack-usage

# Pin the C standard instead of inheriting the compiler default. Several test and
# driver sources call unprototyped functions, which C23 redefines (`void f()`
# means "takes no arguments"); under GCC >= 15's default -std=gnu23 those calls
# are hard errors that -Wno-implicit-function-declaration / -Wno-strict-prototypes
# cannot relax. Pinning gnu17 keeps the relaxations effective and makes the build
# independent of the toolchain's default standard.
FW_STD ?= -std=gnu17

# picolibc must be on both compile and link paths so GCC resolves picolibc's
# headers, not the default newlib ones. Default spec set in compile.mk.
FW_CFLAGS  ?= -march=$(FW_ARCH) -mabi=$(FW_ABI) --specs=$(FW_PICOLIBC_SPECS) $(FW_STD) $(FW_OPT) $(FW_WARNINGS)
FW_ASFLAGS ?= -march=$(FW_ARCH) -mabi=$(FW_ABI)
FW_LDFLAGS ?= \
  -march=$(FW_LD_ARCH) -mabi=$(FW_ABI) \
  -Wl,--gc-sections --specs=$(FW_PICOLIBC_SPECS) -nostartfiles
