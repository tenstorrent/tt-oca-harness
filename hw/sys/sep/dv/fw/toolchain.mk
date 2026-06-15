# SPDX-License-Identifier: Apache-2.0
# (c) 2026 Tenstorrent USA Inc

# SEP DV firmware toolchain settings.
#
# Target CPU: VeeR EL2 (RV32IMC + Zicsr/Zifencei/Zb*), ilp32 ABI.
# C library: picolibc, linked via --specs=picolibc.specs. picolibc is provided by
# the (Docker-provisioned) toolchain and is NOT vendored here.
# Mirrors tt-oca-hw/fw/sep/tests/common/common.mk.
#
# NOTE (follow-up): a full SEP compile also needs the VeeR EL2 snapshot
# (defines.h with ITCM/DCCM addresses + perl_configs.pl). That snapshot is not
# vendored; set FW_SEP_SNAPSHOT_DIR to a generated snapshot to enable it. Until
# then SEP sources are staged and wired but the link/hex stages are gated.
FW_ARCH    ?= rv32imc_zicsr_zifencei_zba_zbb_zbc
FW_LD_ARCH ?= rv32imac
FW_ABI     ?= ilp32

FW_WARNINGS ?= -Wall -Wextra
FW_OPT ?= -Os -fdata-sections -ffunction-sections -fno-common -fstack-usage

FW_PICOLIBC_SPECS ?= picolibc.specs

FW_CFLAGS  ?= -march=$(FW_ARCH) -mabi=$(FW_ABI) $(FW_OPT) $(FW_WARNINGS)
FW_ASFLAGS ?= -march=$(FW_ARCH) -mabi=$(FW_ABI)
FW_LDFLAGS ?= \
  -march=$(FW_LD_ARCH) -mabi=$(FW_ABI) \
  -Wl,--gc-sections --specs=$(FW_PICOLIBC_SPECS) -nostartfiles
