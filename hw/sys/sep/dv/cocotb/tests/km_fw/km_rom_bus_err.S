# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM ROM for the KM CPU bus-error leaves: sep_km_rom_write_err_test,
# sep_km_otp_shim_unreachable_test and sep_km_vrom_decerr_test. Not rom_main:
# each access below is a KM CPU load or store, and no mailbox command issues
# one.
#
# PicoRV32 is RV32E (x0-x15 only). Do not use x16+.
#
# This image makes each access, copies raw words to KM SRAM, and grades
# nothing. Every verdict lives in the host tests. seq_lib/sep_km_bus_err_seq.py
# holds the same word layout for the host.
#
# Before each access the image writes 1 to clear the IRQ_STATUS bits it
# watches and stores the readback, so the host can prove the bits started
# clear: they are sticky, and an earlier fault would otherwise satisfy a later
# check. After each access it polls IRQ_STATUS a bounded number of times and
# stores the last value.
#
#   1. SLVERR control: store to KPV base + KM_KPV_SIZE, the first byte past
#      the KPV register map and inside its 8 KB decode window.
#   2. DECERR control: load from ROM base + ROM size, the Reserved (future ROM
#      growth) row of the key_manager.rdl memory-map summary.
#   3. ROM write: load a ROM word, store its complement to it, poll, and load
#      it again.
#   4. OTP window past the MMR register map: load from, then store to,
#      KEY_MANAGER_OTP_EFUSE_MMR base + size, the first word after the last
#      register the eFuse controller decodes.
#   5. OKAY control in the same OTP window: load from the mapped
#      OTP_EFUSE_MMR SEC_DISABLE_TOKEN_MATCH register.
#   6. Store PRE_MARKER to KM SRAM word 0 (the km_sram_word0_o probe). Every
#      dump word above is complete when the host sees it.
#   7. Load from the VROM base, store the data and the
#      polled IRQ_STATUS, then store POST_MARKER to KM SRAM word 0.
#
# Build (output committed as ../km_rom_bus_err.parhex):
#   make -C hw/sys/sep/dv/cocotb/tests/km_fw ../km_rom_bus_err.parhex

#include "key_manager_addr.h"
#include "km_fields.inc"

#define IRQ_AXI_SLVERR  KM_CSR__IRQ_STATUS_REG__AXI_SLVERR_bm
#define IRQ_AXI_DECERR  KM_CSR__IRQ_STATUS_REG__AXI_DECERR_bm
#define IRQ_AXI_ERR     (IRQ_AXI_SLVERR | IRQ_AXI_DECERR)
#define IRQ_ROM_WRITE   KM_CSR__IRQ_STATUS_REG__ROM_WRITE_ERR_bm
#define IRQ_WATCHED     (IRQ_AXI_ERR | IRQ_ROM_WRITE)

    .equ SRAM_BASE,     KEY_MANAGER_SRAM_BASE_ADDR
    .equ KPV_PAST_MAP,  KEY_MANAGER_KPV_BASE_ADDR + KEY_MANAGER_KPV_SIZE
    .equ ROM_GROWTH,    KEY_MANAGER_ROM_BASE_ADDR + KEY_MANAGER_ROM_SIZE
    .equ OTP_PAST_MMR,  KEY_MANAGER_OTP_EFUSE_MMR_BASE_ADDR + KEY_MANAGER_OTP_EFUSE_MMR_SIZE
    # key_manager.rdl: the OTP/eFuse pass-through is one 4 KB decode window.
    .equ OTP_PAGE_END,  KEY_MANAGER_OTP_EFUSE_MAP_BASE_ADDR + 0x1000
    # hw/ip/key_manager/doc/architecture.adoc: the virtual ROM base, decoded
    # only under OCAH_KM_VROM.
    # The generated map has no symbol for it.
    .equ VROM_BASE,     0x10000000

    .if OTP_PAST_MMR & 3
    .error "OTP_PAST_MMR is not word-aligned"
    .endif
    .if OTP_PAST_MMR >= OTP_PAGE_END
    .error "OTP_PAST_MMR is outside the OTP/eFuse decode window"
    .endif

    # KM SRAM word offsets. seq_lib/sep_km_bus_err_seq.py holds the same list.
    .equ W_MARKER,       0x00
    .equ W_SLV_CLEAN,    0x04
    .equ W_SLV_IRQ,      0x08
    .equ W_DEC_CLEAN,    0x0C
    .equ W_DEC_IRQ,      0x10
    .equ W_ROM_BEFORE,   0x14
    .equ W_ROM_CLEAN,    0x18
    .equ W_ROM_IRQ,      0x1C
    .equ W_ROM_AFTER,    0x20
    .equ W_OTP_RD_CLEAN, 0x24
    .equ W_OTP_RD_DATA,  0x28
    .equ W_OTP_RD_IRQ,   0x2C
    .equ W_OTP_WR_CLEAN, 0x30
    .equ W_OTP_WR_IRQ,   0x34
    .equ W_OTP_OK_CLEAN, 0x38
    .equ W_OTP_OK_IRQ,   0x3C
    .equ W_VROM_CLEAN,   0x40
    .equ W_VROM_DATA,    0x44
    .equ W_VROM_IRQ,     0x48

    .equ PRE_MARKER,     0xB0E1A000
    .equ POST_MARKER,    0xB0E1A0FF
    .equ ROM_PROBE_WORD, 0x5EC0D0D5
    .equ OTP_WR_VALUE,   0x00000A5C
    .equ POLL_COUNT,     32

    .section .text
    .globl _start
_start:
    # x1  IRQ_STATUS
    # x2  KM SRAM base
    # x3  access address
    # x4  poll count
    # x5  IRQ_STATUS readback
    # x6  data
    # x7  poll mask
    # x8  scratch
    # x13 return address
    li    x1, KEY_MANAGER_KMCSR_IRQ_STATUS_BASE_ADDR
    li    x2, SRAM_BASE

    # 1. SLVERR control.
    jal   x13, irq_clean
    sw    x5, W_SLV_CLEAN(x2)
    li    x3, KPV_PAST_MAP
    sw    x0, 0(x3)
    li    x7, IRQ_AXI_SLVERR
    jal   x13, irq_poll
    sw    x5, W_SLV_IRQ(x2)

    # 2. DECERR control.
    jal   x13, irq_clean
    sw    x5, W_DEC_CLEAN(x2)
    li    x3, ROM_GROWTH
    lw    x6, 0(x3)
    li    x7, IRQ_AXI_DECERR
    jal   x13, irq_poll
    sw    x5, W_DEC_IRQ(x2)

    # 3. ROM write.
    la    x3, rom_probe
    lw    x6, 0(x3)
    sw    x6, W_ROM_BEFORE(x2)
    jal   x13, irq_clean
    sw    x5, W_ROM_CLEAN(x2)
    xori  x8, x6, -1
    sw    x8, 0(x3)
    li    x7, IRQ_AXI_SLVERR
    jal   x13, irq_poll
    sw    x5, W_ROM_IRQ(x2)
    lw    x6, 0(x3)
    sw    x6, W_ROM_AFTER(x2)

    # 4. OTP window past the MMR register map: load, then store.
    jal   x13, irq_clean
    sw    x5, W_OTP_RD_CLEAN(x2)
    li    x3, OTP_PAST_MMR
    lw    x6, 0(x3)
    sw    x6, W_OTP_RD_DATA(x2)
    li    x7, IRQ_AXI_ERR
    jal   x13, irq_poll
    sw    x5, W_OTP_RD_IRQ(x2)
    jal   x13, irq_clean
    sw    x5, W_OTP_WR_CLEAN(x2)
    li    x6, OTP_WR_VALUE
    sw    x6, 0(x3)
    li    x7, IRQ_AXI_ERR
    jal   x13, irq_poll
    sw    x5, W_OTP_WR_IRQ(x2)

    # 5. OKAY control in the OTP window: a mapped MMR register.
    jal   x13, irq_clean
    sw    x5, W_OTP_OK_CLEAN(x2)
    li    x3, KEY_MANAGER_OTP_EFUSE_MMR_SEC_DISABLE_TOKEN_MATCH_BASE_ADDR
    lw    x6, 0(x3)
    li    x7, IRQ_AXI_ERR
    jal   x13, irq_poll
    sw    x5, W_OTP_OK_IRQ(x2)

    # 6. Every dump word above is written.
    jal   x13, irq_clean
    sw    x5, W_VROM_CLEAN(x2)
    li    x6, PRE_MARKER
    sw    x6, W_MARKER(x2)

    # 7. VROM load.
    li    x3, VROM_BASE
    lw    x6, 0(x3)
    sw    x6, W_VROM_DATA(x2)
    li    x7, IRQ_AXI_ERR
    jal   x13, irq_poll
    sw    x5, W_VROM_IRQ(x2)
    li    x6, POST_MARKER
    sw    x6, W_MARKER(x2)
1:  j     1b

    # Write 1 to clear the watched IRQ_STATUS bits; x5 = the readback.
irq_clean:
    li    x8, IRQ_WATCHED
    sw    x8, 0(x1)
    lw    x5, 0(x1)
    jr    x13

    # Read IRQ_STATUS until a bit of x7 is set, at most POLL_COUNT times;
    # x5 = the last value read.
irq_poll:
    li    x4, POLL_COUNT
2:  lw    x5, 0(x1)
    and   x8, x5, x7
    bnez  x8, 3f
    addi  x4, x4, -1
    bnez  x4, 2b
3:  jr    x13

    .balign 4
rom_probe:
    .word ROM_PROBE_WORD
