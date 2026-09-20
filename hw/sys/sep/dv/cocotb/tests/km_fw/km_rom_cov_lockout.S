# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM ROM for sep_cov_km_rom_lockout_test. Stimulus only. No contract is
# asserted; reaching the end of the image means the path was driven, nothing
# more.
#
# picorv32_wrapper latches rom_lockout_q on the first committed fetch from an
# SRAM address, and a ROM fetch after that raises rom_access_violation_o. SRAM
# execution needs SRAM_EXEC_MODE.enable set AND the region write-locked
# (picorv32_wrapper.sv sram_exec_allowed), both of which live on the KM CPU
# bus, so a KM image is the only vehicle.
#
# The stub is copied into the region BEFORE the lock, because a store into a
# locked region is dropped.
#
# PicoRV32 is RV32E (x0-x15 only). Do not use x16+.
#
# Result at KM SRAM word0 (0x8000): 0xC0000008 written from SRAM execution,
# then 0xC000000C after the ROM load. The first word is written before the
# faulting load so the host observes completion either way.
#
# Build (output committed as ../km_rom_cov_lockout.parhex):
#   make -C hw/sys/sep/dv/cocotb/tests/km_fw ../km_rom_cov_lockout.parhex

#include "key_manager_addr.h"

    .equ KM_SRAM_BASE,     KEY_MANAGER_SRAM_BASE_ADDR
    .equ EXEC_REGION,      2
    .equ EXEC_REGION_ADDR, (KEY_MANAGER_SRAM_BASE_ADDR + (EXEC_REGION * 0x400))
    # A ROM word past this image's own text, inside the ROM window.
    .equ ROM_PROBE_ADDR,   (KEY_MANAGER_ROM_BASE_ADDR + 0x800)

    .section .text
    .globl _start
_start:
    li    x1, KEY_MANAGER_KMCSR_SRAM_EXEC_MODE_BASE_ADDR
    addi  x2, x0, 1
    sw    x2, 0(x1)

    la    x5, stub_start
    la    x7, stub_end
    li    x6, EXEC_REGION_ADDR
1:  lw    x8, 0(x5)
    sw    x8, 0(x6)
    addi  x5, x5, 4
    addi  x6, x6, 4
    bltu  x5, x7, 1b

    li    x9, KEY_MANAGER_KMCSR_SRAM_LOCK_BASE_ADDR
    addi  x10, x0, (1 << EXEC_REGION)
    sw    x10, 0(x9)

    li    x11, EXEC_REGION_ADDR
    jalr  x0, x11, 0

    # The stub runs from SRAM. It uses absolute addresses only, so copying it
    # to another address does not change what it does.
stub_start:
    li    x11, KM_SRAM_BASE
    lui   x10, 0xC0000
    ori   x10, x10, 8
    sw    x10, 0(x11)
    li    x12, ROM_PROBE_ADDR
    lw    x13, 0(x12)            # ROM load after the lockout latched
    lui   x10, 0xC0000
    ori   x10, x10, 0xC
    sw    x10, 0(x11)
2:  j     2b
stub_end:
