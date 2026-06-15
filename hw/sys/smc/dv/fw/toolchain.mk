# SPDX-License-Identifier: Apache-2.0
# (c) 2026 Tenstorrent USA Inc

# SMC DV firmware toolchain settings.
#
# Target CPU: Rocket (RV64GC + Zb*/Zihpm), lp64d ABI, medany code model.
# C library: newlib + libgloss (-lgcc -lgloss -lm), provided by the
# (Docker-provisioned) toolchain. Uses the SiFive Freedom Metal HAL + generated
# BSP (copied in-tree; see PROVENANCE).
# Mirrors tt-oca-hw/fw/smc/Makefile.
FW_ARCH ?= rv64imafdczicsr_zba_zbb_zbc_zbs_zifencei_zihpm
FW_ABI  ?= lp64d
FW_TUNE ?= -mtune=rocket

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
  -mabi=$(FW_ABI) -march=$(FW_ARCH)

FW_ASFLAGS ?= -mabi=$(FW_ABI) -march=$(FW_ARCH) $(FW_TUNE)

# libgloss/newlib pulled in via --start-group/--end-group around the libs.
FW_LIBS ?= -lgcc -lgloss -lm -Wl,--start-group -Wl,--end-group
FW_LDFLAGS ?= \
  $(FW_OPT) -Wl,--gc-sections -Wl,--as-needed \
  -Wl,--defsym=__stack_size=4K -Wl,--defsym=__heap_size=2K \
  -Wl,--no-relax -nostartfiles \
  -march=$(FW_ARCH) -mabi=$(FW_ABI) $(FW_LIBS)
