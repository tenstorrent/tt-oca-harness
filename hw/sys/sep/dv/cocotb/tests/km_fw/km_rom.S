# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM (PicoRV32) ROM firmware for the SEP DV KM memory smoke test
# (sep_km_mem_smoke_test). It fetches from the KM ROM, reads KM SRAM through
# the enabled SRAM scrambler, and stores one known marker word to KM SRAM
# word0, so the ROM-fetch counter, the SRAM request/write counters, the
# scrambled read-back compare and the SRAM word0 value-compare all have a
# source.
#
#   KM SRAM base = 0x0000_8000  (Key Manager specification, KM private memory
#   map: SRAM region 0x0000_8000-0x0000_FFFF, 32 KB, direct R/W). The image
#   takes it, and the KMCSR scrambler registers, from the generated map.
#
# Scrambled read-back. With KMCSR SCRAMBLER_CTRL.ENABLE set and LOCK clear,
# the image stores four different plaintexts to four different SRAM words,
# then reads them back with four consecutive loads. Each read must be
# descrambled with its own address, not the address of the read before it.
# The image then clears ENABLE and stores the four loaded values to SRAM
# words 1..4, where the host reads them unscrambled. The marker is the last
# store, so a host that sees it knows the results are in place.
#
# This image decides nothing. The host compares words 1..4 with the
# plaintexts and word0 with the marker, and checks that no other probed SRAM
# word (CELL0 and CELL1 included) holds a plaintext. The plaintexts, the
# cell offsets, the marker and the scrambler key are mirrored by KM_SMOKE_* in
# cocotb/seq_lib/sep_km_mem_smoke_seq.py; a divergence between the two fails
# the test's value-compare loudly.
#
# PicoRV32 on the KM is RV32E (x0-x15 only). This image uses x1-x14.
#
# Build (output committed as ../km_rom.parhex):
#   make -C hw/sys/sep/dv/cocotb/tests/km_fw ../km_rom.parhex

#include "key_manager_addr.h"
#include "km_fields.inc"

#define SCR_ENABLE  KM_CSR__SCRAMBLER_CTRL_REG__ENABLE_bm

    // SCRAMBLER_CTRL as an offset from SCRAMBLER_KEY.
    .equ SCR_CTRL_OFF, (KEY_MANAGER_KMCSR_SCRAMBLER_CTRL_BASE_ADDR - KEY_MANAGER_KMCSR_SCRAMBLER_KEY_BASE_ADDR)

    // Scrambled cells, as byte offsets from the SRAM base: two adjacent words,
    // one mid-window word, and the last word of the 32 KB window. None is a
    // result word (words 0..4).
    .equ CELL0, 0x0100
    .equ CELL1, 0x0104
    .equ CELL2, 0x3FF8
    .equ CELL3, 0x7FFC

    .section .text
    .globl _start
_start:
    # x1  SRAM base          x5  KMCSR SCRAMBLER_KEY address
    # x2  marker             x4, x6  scratch
    # x7..x10  loaded words  x11..x14  cell addresses
    li    x1, KEY_MANAGER_SRAM_BASE_ADDR
    li    x11, KEY_MANAGER_SRAM_BASE_ADDR + CELL0
    li    x12, KEY_MANAGER_SRAM_BASE_ADDR + CELL1
    li    x13, KEY_MANAGER_SRAM_BASE_ADDR + CELL2
    li    x14, KEY_MANAGER_SRAM_BASE_ADDR + CELL3

    li    x5, KEY_MANAGER_KMCSR_SCRAMBLER_KEY_BASE_ADDR
    li    x4, 0x6C8E3A5B         # scrambler key (KM_SMOKE_SCRAMBLER_KEY)
    sw    x4, 0(x5)
    addi  x4, x0, SCR_ENABLE
    sw    x4, SCR_CTRL_OFF(x5)   # ENABLE = 1, LOCK = 0

    li    x6, 0x1E2D3C4B         # KM_SMOKE_SCR_PLAINTEXT[0]
    sw    x6, 0(x11)
    li    x6, 0xA5968778         # KM_SMOKE_SCR_PLAINTEXT[1]
    sw    x6, 0(x12)
    li    x6, 0x0F1E2D3C         # KM_SMOKE_SCR_PLAINTEXT[2]
    sw    x6, 0(x13)
    li    x6, 0xC3B4A596         # KM_SMOKE_SCR_PLAINTEXT[3]
    sw    x6, 0(x14)

    # Four consecutive loads of four different addresses.
    lw    x7, 0(x11)
    lw    x8, 0(x12)
    lw    x9, 0(x13)
    lw    x10, 0(x14)

    sw    x0, SCR_CTRL_OFF(x5)   # ENABLE = 0: the results below land unscrambled
    sw    x7, 4(x1)
    sw    x8, 8(x1)
    sw    x9, 12(x1)
    sw    x10, 16(x1)

    li    x2, 0x5A               # marker word (KM_SMOKE_SRAM_WORD0)
    sw    x2, 0(x1)              # store the marker to SRAM word0, last
1:  j     1b                     # spin
