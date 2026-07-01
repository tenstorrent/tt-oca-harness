# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# SMC DV firmware toolchain settings.
#
# Target CPU: Rocket (RV64GC + Zb*/Zihpm), lp64d ABI, medany code model.
# picolibc via --specs=picolibc.specs (Docker toolchain). Uses the SiFive Freedom
# Metal HAL + generated BSP (copied in-tree).
FW_ARCH ?= rv64imafdczicsr_zba_zbb_zbc_zbs_zifencei_zihpm
FW_ABI  ?= lp64d
FW_TUNE ?= -mtune=rocket
# FW_PICOLIBC_SPECS defaults to picolibc.specs in the shared engine (compile.mk).

FW_OPT ?= \
  -Os -flto -fno-plt -fno-jump-tables $(FW_TUNE) \
  -fno-math-errno -mstrict-align

FW_WARNINGS ?= \
  -Wall -Wextra -Wstrict-prototypes \
  -Wno-address-of-packed-member -Wno-missing-braces

FW_CFLAGS ?= \
  -std=gnu17 $(FW_OPT) $(FW_WARNINGS) \
  -ffunction-sections -fdata-sections -fno-common \
  -fmerge-all-constants -fno-builtin -mcmodel=medany \
  -mabi=$(FW_ABI) -march=$(FW_ARCH) --specs=$(FW_PICOLIBC_SPECS)

FW_ASFLAGS ?= -mabi=$(FW_ABI) -march=$(FW_ARCH) $(FW_TUNE)

FW_LIBS ?= -lgcc
FW_LDFLAGS ?= \
  $(FW_OPT) -Wl,--gc-sections -Wl,--as-needed \
  -Wl,--defsym=__stack_size=4K -Wl,--defsym=__heap_size=2K \
  -Wl,--no-relax -nostartfiles --specs=$(FW_PICOLIBC_SPECS) \
  -march=$(FW_ARCH) -mabi=$(FW_ABI) $(FW_LIBS)
