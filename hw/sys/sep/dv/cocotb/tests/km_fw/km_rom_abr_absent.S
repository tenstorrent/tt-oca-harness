# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM ROM for sep_abr_absent_decerr_test. The Key Manager ABR key bus is private
# to the KM, so only code on the KM CPU can present a transaction to it.
#
# PicoRV32 is RV32E (x0-x15 only). Do not use x16+.
#
# Four legs. Each leg first W1Cs the two AXI error bits of IRQ_STATUS and
# requires them to read back clear, then issues one access and records the
# AXI error bits that access set, as a 2-bit code: bit 0 AXI_SLVERR, bit 1
# AXI_DECERR, 0 for neither.
#
#   leg 0  store to the HMAC wrapper key aperture   (a live path: the control)
#   leg 1  store to the ABR wrapper key aperture
#   leg 2  load from the ABR wrapper key aperture
#   leg 3  load from KMCSR base + KMCSR size, the first address after the
#          generated KMCSR register block and inside its 2 KB (0x800) decode
#          window (hw/ip/key_manager/regs/key_manager.rdl)
#
# The host grades every code. The image publishes them in KM SRAM word0 (the
# km_sram_word0_o probe) and blocks on an inbound mailbox word before each
# publish after the first:
#
#   word0 = 0xB3 << 24 | payload << 4 | phase
#   phase 1  payload[1:0] leg 0, [3:2] leg 1, [5:4] leg 2, [7:6] leg 3,
#            payload[8] every leg started with both error bits clear
#   phase 2  payload[15:0] = leg 3 read data [15:0]
#   phase 3  payload[15:0] = leg 3 read data [31:16]
#
# Build (output committed as ../km_rom_abr_absent.parhex):
#   make -C hw/sys/sep/dv/cocotb/tests/km_fw ../km_rom_abr_absent.parhex

#include "key_manager_addr.h"
#include "km_fields.inc"

    .equ MBOX_READ_DATA,   (KEY_MANAGER_MAILBOX_KM_KM_READ_DATA_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ MBOX_STATUS,      (KEY_MANAGER_MAILBOX_KM_KM_STATUS_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)

    # The KM SRAM is a memory, not a register block, so the generated register
    # header carries no symbol for its base. km_csr.rdl documents SRAM lock
    # region 0 as 0x8000-0x83FF, which is where the memory starts.
    .equ KM_SRAM_BASE, 0x00008000

    .equ SLVERR_BIT,   KM_CSR__IRQ_STATUS_REG__AXI_SLVERR_bm
    .equ DECERR_BIT,   KM_CSR__IRQ_STATUS_REG__AXI_DECERR_bm
    .equ AXI_ERR_BITS, (SLVERR_BIT | DECERR_BIT)
    .equ POLL_LIMIT,   32
    .equ KMCSR_PAST_END, (KEY_MANAGER_KMCSR_BASE_ADDR + KEY_MANAGER_KMCSR_SIZE)

    .section .text
    .globl _start
_start:
    # x1  mailbox base
    # x2  access address of the current leg
    # x5  payload
    # x8  leg 3 read data
    # x9  IRQ_STATUS
    # x10 KM SRAM base
    # x15 precondition flag
    # x6,x7,x11-x14 scratch
    li    x1, KEY_MANAGER_MAILBOX_KM_BASE_ADDR
    li    x9, KEY_MANAGER_KMCSR_IRQ_STATUS_BASE_ADDR
    li    x10, KM_SRAM_BASE
    addi  x5, x0, 0
    addi  x15, x0, 1

    jal   x13, wait_mbox           # host: go

    # ---- leg 0: HMAC key store (control) ------------------------------
    li    x2, KEY_MANAGER_HMAC_WRAPPER_KEY_BASE_ADDR
    jal   x13, clear_errs
    and   x15, x15, x14
    sw    x0, 0(x2)
    jal   x13, poll_code
    or    x5, x5, x14

    # ---- leg 1: ABR key store -----------------------------------------
    li    x2, KEY_MANAGER_ABR_WRAPPER_KEY_BASE_ADDR
    jal   x13, clear_errs
    and   x15, x15, x14
    sw    x0, 0(x2)
    jal   x13, poll_code
    slli  x14, x14, 2
    or    x5, x5, x14

    # ---- leg 2: ABR key load ------------------------------------------
    jal   x13, clear_errs
    and   x15, x15, x14
    lw    x7, 0(x2)
    jal   x13, poll_code
    slli  x14, x14, 4
    or    x5, x5, x14

    # ---- leg 3: KMCSR load past the generated block -------------------
    li    x2, KMCSR_PAST_END
    jal   x13, clear_errs
    and   x15, x15, x14
    lw    x8, 0(x2)
    jal   x13, poll_code
    slli  x14, x14, 6
    or    x5, x5, x14

    slli  x15, x15, 8
    or    x5, x5, x15
    addi  x11, x0, 1
    jal   x13, publish

    jal   x13, wait_mbox           # host: phase 1 read
    li    x6, 0xFFFF
    and   x5, x8, x6
    addi  x11, x0, 2
    jal   x13, publish

    jal   x13, wait_mbox           # host: phase 2 read
    srli  x5, x8, 16
    addi  x11, x0, 3
    jal   x13, publish
1:  j     1b

# --- helpers; x13 holds the return address, x14 the result ------------

    # Block until the inbound mailbox holds a word, then consume it.
wait_mbox:
    lw    x6, MBOX_STATUS(x1)
    andi  x6, x6, 0x1              # inbound_empty
    bnez  x6, wait_mbox
    lw    x6, MBOX_READ_DATA(x1)
    jr    x13

    # W1C both AXI error bits and require them to read back clear.
    # x14 = 1 when the bus started clean.
clear_errs:
    addi  x6, x0, AXI_ERR_BITS
    sw    x6, 0(x9)
    lw    x6, 0(x9)
    andi  x6, x6, AXI_ERR_BITS
    addi  x14, x0, 1
    beqz  x6, clear_errs_done
    addi  x14, x0, 0
clear_errs_done:
    jr    x13

    # Poll IRQ_STATUS a bounded number of times, then return the 2-bit code
    # of the error bits seen: bit 0 AXI_SLVERR, bit 1 AXI_DECERR. The bits
    # are sticky, so a set bit cannot be missed once it appears.
poll_code:
    addi  x12, x0, POLL_LIMIT
poll_code_loop:
    lw    x6, 0(x9)
    andi  x6, x6, AXI_ERR_BITS
    bnez  x6, poll_code_seen
    addi  x12, x12, -1
    bnez  x12, poll_code_loop
poll_code_seen:
    addi  x14, x0, 0
    andi  x12, x6, SLVERR_BIT
    beqz  x12, poll_code_dec
    ori   x14, x14, 1
poll_code_dec:
    andi  x12, x6, DECERR_BIT
    beqz  x12, poll_code_done
    ori   x14, x14, 2
poll_code_done:
    jr    x13

    # Publish the payload in x5 plus the phase in x11 to KM SRAM word0.
publish:
    lui   x6, 0xB3000              # magic 0xB3 in [31:24]
    slli  x7, x5, 4
    or    x6, x6, x7
    or    x6, x6, x11
    sw    x6, 0(x10)
    jr    x13
