# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM ROM for sep_km_drbg_sampler_timeout_reset_test. Not rom_main: only code on
# the KM CPU can read the DRBG sampler, and no mailbox command reads it with a
# chosen CFG.TIMEOUT.
#
# PicoRV32 is RV32E (x0-x15 only). Do not use x16+.
#
# This image makes each sampler access, copies raw words to KM SRAM, and grades
# nothing. Every verdict lives in the host test. seq_lib/sep_km_drbg_sampler_seq.py
# holds the same word layout, markers and TIMEOUT_CYCLES for the host.
#
# KMCSR BOOT_STATUS.COLD_BOOT_DONE survives a warm reset (km_csr.rdl), so the
# image takes the cold path once and the warm path on every later boot.
#
# Cold path:
#   1. Set COLD_BOOT_DONE.
#   2. Timeout leg: CFG.TIMEOUT = TIMEOUT_CYCLES, clear the watched IRQ_STATUS
#      bits, read DATA, poll IRQ_STATUS for AXI_SLVERR and DRBG_ERR, read
#      STATUS. The host has not enabled the entropy chain, so no beat arrives.
#   3. Reset leg: CFG = 0 (timeout disabled), store MK_BLOCK, read DATA. Only a
#      KM reset ends this read. MK_R_DONE is stored if it completes.
# Warm path:
#   4. Store BOOT_STATUS, CFG, STATUS and IRQ_STATUS as found, then MK_WARM.
#   5. Control leg: CFG.TIMEOUT = TIMEOUT_CYCLES, poll STATUS until DRBG_READY,
#      clear the watched IRQ_STATUS bits, read DATA, poll IRQ_STATUS, read
#      STATUS, store MK_DONE.
#
# Build (output committed as ../km_rom_drbg_sampler.parhex):
#   make -C hw/sys/sep/dv/cocotb/tests/km_fw ../km_rom_drbg_sampler.parhex

#include "key_manager_addr.h"
#include "km_fields.inc"

#define IRQ_AXI_SLVERR  KM_CSR__IRQ_STATUS_REG__AXI_SLVERR_bm
#define IRQ_AXI_DECERR  KM_CSR__IRQ_STATUS_REG__AXI_DECERR_bm
#define IRQ_DRBG_ERR    KM_CSR__IRQ_STATUS_REG__DRBG_ERR_bm
#define IRQ_WATCHED     (IRQ_AXI_SLVERR | IRQ_AXI_DECERR | IRQ_DRBG_ERR)
#define IRQ_TIMEOUT     (IRQ_AXI_SLVERR | IRQ_DRBG_ERR)
#define COLD_BOOT_DONE  KM_CSR__BOOT_STATUS_REG__COLD_BOOT_DONE_bm
#define DRBG_READY      KM_DRBG_SAMPLER__STATUS_REG__DRBG_READY_bm
#define TIMEOUT_BP      KM_DRBG_SAMPLER__CFG_REG__TIMEOUT_bp

    .equ SRAM_BASE,      KEY_MANAGER_SRAM_BASE_ADDR
    .equ SMP_BASE,       KEY_MANAGER_DRBG_SAMPLER_DATA_BASE_ADDR
    .equ SMP_CFG,        KEY_MANAGER_DRBG_SAMPLER_CFG_BASE_ADDR - SMP_BASE
    .equ SMP_STATUS,     KEY_MANAGER_DRBG_SAMPLER_STATUS_BASE_ADDR - SMP_BASE

    .equ TIMEOUT_CYCLES, 40
    .equ CFG_SHORT,      TIMEOUT_CYCLES << TIMEOUT_BP

    # KM SRAM word offsets. seq_lib/sep_km_drbg_sampler_seq.py holds the same list.
    .equ W_MARKER,       0x00
    .equ W_T_BOOT,       0x04
    .equ W_T_STATUS_PRE, 0x08
    .equ W_T_CFG,        0x0C
    .equ W_T_CLEAN,      0x10
    .equ W_T_DATA,       0x14
    .equ W_T_IRQ,        0x18
    .equ W_T_STATUS,     0x1C
    .equ W_R_CFG,        0x20
    .equ W_R_STATUS,     0x24
    .equ W_R_DATA,       0x28
    .equ W_W_BOOT,       0x2C
    .equ W_W_CFG,        0x30
    .equ W_W_STATUS,     0x34
    .equ W_W_IRQ,        0x38
    .equ W_P_CFG,        0x3C
    .equ W_P_STATUS_PRE, 0x40
    .equ W_P_CLEAN,      0x44
    .equ W_P_DATA,       0x48
    .equ W_P_IRQ,        0x4C
    .equ W_P_STATUS,     0x50

    .equ MK_BLOCK,       0xD5A70001
    .equ MK_R_DONE,      0xD5A70002
    .equ MK_WARM,        0xD5A70003
    .equ MK_DONE,        0xD5A70004
    .equ POLL_COUNT,     32

    .section .text
    .globl _start
_start:
    # x1  IRQ_STATUS        x2  KM SRAM base     x3  sampler base
    # x4  poll count        x5  readback         x6  DATA
    # x7  poll mask         x8  scratch          x9  BOOT_STATUS
    # x13 return address
    li    x1, KEY_MANAGER_KMCSR_IRQ_STATUS_BASE_ADDR
    li    x2, SRAM_BASE
    li    x3, SMP_BASE
    li    x9, KEY_MANAGER_KMCSR_BOOT_STATUS_BASE_ADDR
    lw    x5, 0(x9)
    andi  x8, x5, COLD_BOOT_DONE
    bnez  x8, warm_boot

    # 1. Cold path.
    sw    x5, W_T_BOOT(x2)
    li    x8, COLD_BOOT_DONE
    sw    x8, 0(x9)

    # 2. Timeout leg.
    lw    x5, SMP_STATUS(x3)
    sw    x5, W_T_STATUS_PRE(x2)
    li    x8, CFG_SHORT
    sw    x8, SMP_CFG(x3)
    lw    x5, SMP_CFG(x3)
    sw    x5, W_T_CFG(x2)
    jal   x13, irq_clean
    sw    x5, W_T_CLEAN(x2)
    lw    x6, 0(x3)
    sw    x6, W_T_DATA(x2)
    li    x7, IRQ_TIMEOUT
    jal   x13, irq_poll_all
    sw    x5, W_T_IRQ(x2)
    lw    x5, SMP_STATUS(x3)
    sw    x5, W_T_STATUS(x2)

    # 3. Reset leg.
    sw    x0, SMP_CFG(x3)
    lw    x5, SMP_CFG(x3)
    sw    x5, W_R_CFG(x2)
    lw    x5, SMP_STATUS(x3)
    sw    x5, W_R_STATUS(x2)
    li    x8, MK_BLOCK
    sw    x8, W_MARKER(x2)
    lw    x6, 0(x3)
    sw    x6, W_R_DATA(x2)
    li    x8, MK_R_DONE
    sw    x8, W_MARKER(x2)
1:  j     1b

    # 4. Warm path.
warm_boot:
    sw    x5, W_W_BOOT(x2)
    lw    x5, SMP_CFG(x3)
    sw    x5, W_W_CFG(x2)
    lw    x5, SMP_STATUS(x3)
    sw    x5, W_W_STATUS(x2)
    lw    x5, 0(x1)
    sw    x5, W_W_IRQ(x2)
    li    x8, MK_WARM
    sw    x8, W_MARKER(x2)

    # 5. Control leg.
    li    x8, CFG_SHORT
    sw    x8, SMP_CFG(x3)
    lw    x5, SMP_CFG(x3)
    sw    x5, W_P_CFG(x2)
2:  lw    x5, SMP_STATUS(x3)
    andi  x8, x5, DRBG_READY
    beqz  x8, 2b
    sw    x5, W_P_STATUS_PRE(x2)
    jal   x13, irq_clean
    sw    x5, W_P_CLEAN(x2)
    lw    x6, 0(x3)
    sw    x6, W_P_DATA(x2)
    li    x7, IRQ_WATCHED
    jal   x13, irq_poll_any
    sw    x5, W_P_IRQ(x2)
    lw    x5, SMP_STATUS(x3)
    sw    x5, W_P_STATUS(x2)
    li    x8, MK_DONE
    sw    x8, W_MARKER(x2)
3:  j     3b

    # Write 1 to clear the watched IRQ_STATUS bits; x5 = the readback.
irq_clean:
    li    x8, IRQ_WATCHED
    sw    x8, 0(x1)
    lw    x5, 0(x1)
    jr    x13

    # Read IRQ_STATUS until every bit of x7 is set, at most POLL_COUNT times;
    # x5 = the last value read.
irq_poll_all:
    li    x4, POLL_COUNT
4:  lw    x5, 0(x1)
    and   x8, x5, x7
    beq   x8, x7, 5f
    addi  x4, x4, -1
    bnez  x4, 4b
5:  jr    x13

    # Read IRQ_STATUS until a bit of x7 is set, at most POLL_COUNT times;
    # x5 = the last value read.
irq_poll_any:
    li    x4, POLL_COUNT
6:  lw    x5, 0(x1)
    and   x8, x5, x7
    bnez  x8, 7f
    addi  x4, x4, -1
    bnez  x4, 6b
7:  jr    x13
