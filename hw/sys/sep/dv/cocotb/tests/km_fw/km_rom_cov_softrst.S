# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM ROM for sep_cov_km_csr_soft_rst_test. Stimulus only. No contract is
# asserted; reaching the end of the image means the path was driven, nothing
# more.
#
# SOFT_RST_CODE is on the KM CPU bus, so a KM image is the only vehicle. The
# magic value is km_csr.sv SOFT_RST_CODE_MAGIC (ASCII "SRST"); the match
# drives soft_rst_o and the reset conditioner returns it as a warm reset, so
# this image restarts.
#
# KM SRAM keeps its contents across the warm reset, so word0 is the boot
# counter: the second entry takes the halt leg instead of writing the magic
# again, which is what stops the reset from repeating.
#
# PicoRV32 is RV32E (x0-x15 only). Do not use x16+.
#
# Result at KM SRAM word0 (0x8000): 0xC0000020 on the first boot, 0xC0000060
# after the soft reset has been taken.
#
# Build (output committed as ../km_rom_cov_softrst.parhex):
#   make -C hw/sys/sep/dv/cocotb/tests/km_fw ../km_rom_cov_softrst.parhex

#include "key_manager_addr.h"

    .equ KM_SRAM_BASE,   KEY_MANAGER_SRAM_BASE_ADDR
    .equ SOFT_RST_MAGIC, 0x53525354

    .section .text
    .globl _start
_start:
    li    x11, KM_SRAM_BASE
    lw    x12, 0(x11)
    lui   x13, 0xC0000
    ori   x13, x13, 0x20
    beq   x12, x13, second_boot

    sw    x13, 0(x11)
    li    x5, KEY_MANAGER_KMCSR_SOFT_RST_CODE_BASE_ADDR
    li    x6, SOFT_RST_MAGIC
    sw    x6, 0(x5)
1:  j     1b

second_boot:
    lui   x13, 0xC0000
    ori   x13, x13, 0x60
    sw    x13, 0(x11)
2:  j     2b
