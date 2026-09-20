# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM ROM for sep_cov_km_kpv_seal_all_slots_test. Stimulus only. No contract is
# asserted; reaching the end of the walk means the path was driven, nothing
# more.
#
# KPV CTRL is on the KM CPU bus (km_axi_lite_xbar has one slave port, the SEP
# mailbox), so a KM image is the only vehicle that reaches it.
#
# This image is the SEALED complement of km_rom_cov_kpv_walk.S. That image
# seals even slots only, so on odd slots slot_sealed stays low and the HW-set
# inputs km_kpv.sv drives from it never assert:
#   km_kpv.sv:227  CTRL[i].lock_write.hwset = slot_sealed[i] & ~wipe_pulse_i
#   km_kpv.sv:230  CTRL[i].lock_use.hwset   = erase_done[i] & slot_sealed[i]
#                                                & ~wipe_pulse_i
# Here every slot takes the sealed leg, so both HW-set inputs assert on all 64
# replicated CTRL instances in km_kpv_reg.
#
# PicoRV32 is RV32E (x0-x15 only). Do not use x16+.
#
# Host writes one mailbox word before this image runs:
#   [5:0]   first slot of the walk
#   [11:8]  slot stride, forced odd here so the walk visits all 64 slots
#
# Every slot takes one CTRL write that sets seal together with lock_write and
# lock_use, one readback, then one erase. Because the slot is sealed, the erase
# retires it: erase_done with slot_sealed drives lock_use.hwset, and lock_write
# stays held by hwset rather than being cleared through hwclr.
#
# Result at KM SRAM word0 (0x8000): 0xC0000002 with an eight-bit fold of the
# received config word at [23:16].
#
# Build (output committed as ../km_rom_cov_kpv_seal.parhex):
#   make -C hw/sys/sep/dv/cocotb/tests/km_fw ../km_rom_cov_kpv_seal.parhex

#include "key_manager_addr.h"
#include "km_fields.inc"

#define CTRL_LOCK_WRITE KM_KPV__CTRL_REG__LOCK_WRITE_bm
#define CTRL_LOCK_USE   KM_KPV__CTRL_REG__LOCK_USE_bm
#define CTRL_ERASE      KM_KPV__CTRL_REG__ERASE_bm
#define CTRL_SEAL       KM_KPV__CTRL_REG__SEAL_bm
#define CTRL_SEALED     (CTRL_SEAL | CTRL_LOCK_WRITE | CTRL_LOCK_USE)

    .equ MBOX_READ_DATA, (KEY_MANAGER_MAILBOX_KM_KM_READ_DATA_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ MBOX_STATUS,    (KEY_MANAGER_MAILBOX_KM_KM_STATUS_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ KM_SRAM_BASE,   KEY_MANAGER_SRAM_BASE_ADDR

    .section .text
    .globl _start
_start:
    li    x1, KEY_MANAGER_MAILBOX_KM_BASE_ADDR
1:  lw    x5, MBOX_STATUS(x1)
    andi  x6, x5, 0x1            # inbound_empty
    bnez  x6, 1b
    lw    x2, MBOX_READ_DATA(x1)

    andi  x7, x2, 0x3F           # idx = first slot
    srli  x4, x2, 8
    andi  x4, x4, 0xF
    ori   x4, x4, 1              # stride, odd
    li    x8, KEY_MANAGER_KPV_CTRL_BASE_ADDR(0)
    addi  x9, x0, 0              # visited count

walk:
    slli  x10, x7, 2
    add   x10, x8, x10           # &CTRL[idx]
    addi  x12, x0, CTRL_SEALED   # every slot takes the sealed leg
    sw    x12, 0(x10)
    lw    x11, 0(x10)            # readback drives the CTRL read mux
    addi  x12, x0, CTRL_ERASE
    sw    x12, 0(x10)
    addi  x13, x0, 256           # bounded: a stuck erase must not hang
2:  lw    x11, 0(x10)
    andi  x14, x11, CTRL_ERASE
    beqz  x14, erased
    addi  x13, x13, -1
    bnez  x13, 2b
erased:
    add   x7, x7, x4
    andi  x7, x7, 0x3F
    addi  x9, x9, 1
    addi  x15, x0, 64
    bltu  x9, x15, walk

    # Fold the whole config word into eight bits and echo it at [23:16].
    srli  x5, x2, 8
    xor   x5, x5, x2
    srli  x6, x2, 16
    xor   x5, x5, x6
    srli  x6, x2, 24
    xor   x5, x5, x6
    andi  x5, x5, 0xFF
    slli  x5, x5, 16
    lui   x6, 0xC0000
    or    x5, x5, x6
    ori   x5, x5, 2
    li    x10, KM_SRAM_BASE
    sw    x5, 0(x10)
3:  j     3b
