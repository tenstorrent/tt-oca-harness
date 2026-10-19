# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM SRAM image IMG-H for sep_km_handover_rand_test. The host streams it with
# CMD_SRAM_LOAD_EXEC (or re-runs it with CMD_SRAM_EXEC), and the ROM hands over
# to it at SRAM 0x8000. The image reads the KM state at the jump and sends what
# it read to the host as one KM mailbox message. It grades nothing; every golden
# lives in the host test, and cocotb/env/sep_km_img_h.py decodes the message.
#
# PicoRV32 is RV32E (x0-x15 only). Do not use x16+.
#
# Position. The code is position-independent (PC-relative branches, jumps and
# `lla`; absolute addresses only for KM registers), so the bytes linked at 0
# are the bytes that run at 0x8000. The image is far below one 1 KiB SRAM
# write-lock region, so the handover locks region 0 only.
#
# Entry state. The first instruction loads the KM mailbox base into x15, the
# store base register. x15 is the only register that the image changes before
# it saves the others, so its entry value is not reported. The next 14 stores
# save x5, x1-x4 and x6-x14 to SRAM 0xF800 (region 30, which the handover does
# not lock), before any other instruction writes a register.
#
# Transport. Every report word goes to KM_WRITE_DATA after a poll of
# KM_STATUS.outbound_full (no bound: a host that stops reading stops the image).
# The message has no response header. Its first word is MAGIC, which has no
# response ID in bits [15:8], and the separator is on the last word (END_MAGIC).
# After the message the image spins.
#
# Report message (word index: content). 263 words.
#     0  MAGIC 0x4B4D4948 ("KMIH")
#     1  LAYOUT: version << 16 | word count
#     2  x5 at entry
#  3-15  x1, x2, x3, x4, x6 ... x14 at entry
#    16  KMCSR IRQ_STATUS (the first KMCSR access of the image)
#    17  KMCSR IRQ_ENABLE
#    18  KM mailbox KM_IRQ_ENABLE
#    19  KMCSR IRQ_ENTRY_ADDR
#    20  KMCSR IRQ_ENTRY_LOCK
#    21  CPU IRQ mask (maskirq with all ones; the old mask, mask stays all ones)
#    22  KMCSR SRAM_EXEC_MODE
#    23  KMCSR OTP_READ_LOCK
# 24-27  VAL_0 of CHIPLET_UID, SIP_UID, SYS_UID, CLASS_KEY
# 28-30  VAL_0 of SEP_CHIPLET_ID, SEP_SIP_ID, SEP_SYS_ID
#    31  KMCSR SRAM_LOCK
#    32  KM mailbox KM_STATUS
# 33-224 for slot s = 0..63, three words at 33 + 3s: KPV CTRL[s], key word 0 of
#        slot s, IRQ_STATUS & (AXI_SLVERR | AXI_DECERR) after that read (both
#        bits cleared by write-one-to-clear just before the read)
#   225  F = the lowest slot with CTRL 0, or 0xFFFFFFFF if there is none
#226-241 the 16 key words of slot F (0 if none)
#   242  key word 0 of slot F read back after a write of CTRL_PROBE 0x4B4D5756
#        (0 if none)
#243-251 KEY_CTRL of HMAC, KMAC, AES, OTBN, ML-DSA seed, ML-KEM seed D,
#        ML-KEM seed Z, ML-KEM message (DEST_VALID bit order), then the ML-KEM
#        shared key
#   252  KMAC KEY_CTRL read back after a write of key_valid = 1
#   253  KMAC KEY_CTRL read back after a write of 0
#   254  SRAM_WRITE_LOCK_VIOLATION after all ones is written to it and to
#        IRQ_STATUS (write one to clear)
#   255  SRAM word 0xFFFC (region 31) before the store
#   256  SRAM word 0xFFFC read back after a store of its complement
#   257  SRAM_WRITE_LOCK_VIOLATION after that store
#   258  the image data word OWN before the store (violation cleared first)
#   259  OWN read back after a store of its complement
#   260  SRAM_WRITE_LOCK_VIOLATION after that store
#   261  the KM byte address of OWN
#   262  END_MAGIC 0x4B4D4945 ("KMIE"), with the separator
#
# Build (output committed as ../km_img_h.parhex; the 32-bit word is the low 8
# hex digits of each line, the parity nibble is not used for an SRAM image):
#   make -C hw/sys/sep/dv/cocotb/tests/km_fw ../km_img_h.parhex

#include "key_manager_addr.h"
#include "hmac_wrapper_key_addr.h"
#include "kmac_wrapper_key_addr.h"
#include "aes_wrapper_key_addr.h"
#include "otbn_wrapper_key_addr.h"
#include "abr_wrapper_key_addr.h"
#include "km_fields.inc"

    .option norelax

    .equ MAGIC,         0x4B4D4948
    .equ END_MAGIC,     0x4B4D4945
    .equ LAYOUT_VERSION, 1
    .equ REPORT_WORDS,  263
    .equ LAYOUT,        ((LAYOUT_VERSION << 16) | REPORT_WORDS)
    .equ CTRL_PROBE,    0x4B4D5756
    .equ KEY_VALID,     1           // KEY_CTRL.key_valid, bit 0 (kmac_wrapper_key.adoc)
    .equ N_GPR,         14
    .equ N_SLOTS,       KEY_MANAGER_KPV_CTRL_NUM
    .equ N_TBL_A,       5           // entries of tbl_a, tbl_b, tbl_c
    .equ N_TBL_B,       11
    .equ N_TBL_C,       9

    .equ MBOX,          KEY_MANAGER_MAILBOX_KM_BASE_ADDR
    .equ MB_WDATA,      (KEY_MANAGER_MAILBOX_KM_KM_WRITE_DATA_BASE_ADDR - MBOX)
    .equ MB_WSEP,       (KEY_MANAGER_MAILBOX_KM_KM_WRITE_SEPARATOR_BASE_ADDR - MBOX)
    .equ MB_STATUS,     (KEY_MANAGER_MAILBOX_KM_KM_STATUS_BASE_ADDR - MBOX)
    .equ OUT_FULL,      KM_MAILBOX_KM__STATUS_REG__OUTBOUND_FULL_bm
    .equ SRAM_END,      (KEY_MANAGER_SRAM_BASE_ADDR + KEY_MANAGER_SRAM_SIZE)
    .equ SNAP_OFF,      (SRAM_END - 0x800 - MBOX)   // SRAM 0xF800, region 30
    .equ R31_OFF,       (SRAM_END - 4 - MBOX)       // SRAM 0xFFFC, region 31

    .equ CSR,           KEY_MANAGER_KMCSR_BASE_ADDR
    .equ C_IRQ_STATUS,  (KEY_MANAGER_KMCSR_IRQ_STATUS_BASE_ADDR - CSR)
    .equ C_VIOL,        (KEY_MANAGER_KMCSR_SRAM_WRITE_LOCK_VIOLATION_BASE_ADDR - CSR)
    .equ BUS_ERR,       (KM_CSR__IRQ_STATUS_REG__AXI_SLVERR_bm | KM_CSR__IRQ_STATUS_REG__AXI_DECERR_bm)
    .equ KMAC_KEY_CTRL, (KEY_MANAGER_KMAC_WRAPPER_KEY_BASE_ADDR + KMAC_WRAPPER_KEY_KEY_CTRL_BASE_ADDR)

    // PicoRV32 custom0: mask = rs, rd = old mask.
    .macro maskirq rd, rs
    .word ((0b0000011 << 25) | (\rs << 15) | (0b110 << 12) | (\rd << 7) | 0b0001011)
    .endm

    // Registers after the save:
    //   x15 mailbox base   x14 KMCSR base   x10 report word   x11 put scratch
    //   x1 link of put     x9 link of put_blk / put_tbl
    //   x12 pointer        x13 count        x2-x8 scratch

    .section .text
    .globl _start
_start:
    lui   x15, (MBOX >> 12)
    sw    x5,  (SNAP_OFF + 0)(x15)
    sw    x1,  (SNAP_OFF + 4)(x15)
    sw    x2,  (SNAP_OFF + 8)(x15)
    sw    x3,  (SNAP_OFF + 12)(x15)
    sw    x4,  (SNAP_OFF + 16)(x15)
    sw    x6,  (SNAP_OFF + 20)(x15)
    sw    x7,  (SNAP_OFF + 24)(x15)
    sw    x8,  (SNAP_OFF + 28)(x15)
    sw    x9,  (SNAP_OFF + 32)(x15)
    sw    x10, (SNAP_OFF + 36)(x15)
    sw    x11, (SNAP_OFF + 40)(x15)
    sw    x12, (SNAP_OFF + 44)(x15)
    sw    x13, (SNAP_OFF + 48)(x15)
    sw    x14, (SNAP_OFF + 52)(x15)

    lui   x14, (CSR >> 12)
    li    x10, MAGIC
    jal   x1, put
    li    x10, LAYOUT
    jal   x1, put
    addi  x12, x15, SNAP_OFF
    li    x13, N_GPR
    jal   x9, put_blk

    lla   x12, tbl_a
    li    x13, N_TBL_A
    jal   x9, put_tbl
    li    x2, -1
    maskirq 10, 2
    jal   x1, put
    lla   x12, tbl_b
    li    x13, N_TBL_B
    jal   x9, put_tbl

    // KPV: x2 slot, x3 CTRL address, x4 key word 0 address, x6 free slot,
    // x5 free slot key word 0 address, x8 bus error bits.
    li    x2, 0
    li    x3, KEY_MANAGER_KPV_CTRL_BASE_ADDR(0)
    li    x4, KEY_MANAGER_KPV_KEY_ENTRY_WORD_BASE_ADDR(0, 0)
    li    x6, -1
    li    x8, BUS_ERR
kpv_loop:
    lw    x10, 0(x3)
    bnez  x10, 1f
    bgez  x6, 1f
    mv    x6, x2
    mv    x5, x4
1:  jal   x1, put
    sw    x8, C_IRQ_STATUS(x14)
    lw    x10, 0(x4)
    jal   x1, put
    lw    x10, C_IRQ_STATUS(x14)
    and   x10, x10, x8
    jal   x1, put
    addi  x2, x2, 1
    addi  x3, x3, 4
    addi  x4, x4, (KEY_MANAGER_KPV_KEY_ENTRY_STRIDE)
    li    x7, N_SLOTS
    bne   x2, x7, kpv_loop

    mv    x10, x6
    jal   x1, put
    bltz  x6, no_free
    mv    x12, x5
    li    x13, KEY_MANAGER_KPV_KEY_ENTRY_WORD_NUM
    jal   x9, put_blk
    li    x7, CTRL_PROBE
    sw    x7, 0(x5)
    lw    x10, 0(x5)
    jal   x1, put
    j     free_done
no_free:
    li    x13, (KEY_MANAGER_KPV_KEY_ENTRY_WORD_NUM + 1)
2:  li    x10, 0
    jal   x1, put
    addi  x13, x13, -1
    bnez  x13, 2b
free_done:

    lla   x12, tbl_c
    li    x13, N_TBL_C
    jal   x9, put_tbl
    li    x3, KMAC_KEY_CTRL
    li    x7, KEY_VALID
    sw    x7, 0(x3)
    lw    x10, 0(x3)
    jal   x1, put
    sw    x0, 0(x3)
    lw    x10, 0(x3)
    jal   x1, put

    // SRAM store test.
    li    x7, -1
    sw    x7, C_VIOL(x14)
    sw    x7, C_IRQ_STATUS(x14)
    lw    x10, C_VIOL(x14)
    jal   x1, put
    lw    x10, R31_OFF(x15)
    not   x7, x10
    jal   x1, put
    sw    x7, R31_OFF(x15)
    lw    x10, R31_OFF(x15)
    jal   x1, put
    lw    x10, C_VIOL(x14)
    jal   x1, put
    li    x7, -1
    sw    x7, C_VIOL(x14)
    lla   x3, own
    lw    x10, 0(x3)
    not   x7, x10
    jal   x1, put
    sw    x7, 0(x3)
    lw    x10, 0(x3)
    jal   x1, put
    lw    x10, C_VIOL(x14)
    jal   x1, put
    mv    x10, x3
    jal   x1, put

    li    x10, END_MAGIC
3:  lw    x11, MB_STATUS(x15)
    andi  x11, x11, OUT_FULL
    bnez  x11, 3b
    li    x7, KM_MAILBOX_KM__WRITE_SEPARATOR_REG__SET_bm
    sw    x7, MB_WSEP(x15)
    sw    x10, MB_WDATA(x15)
halt:
    j     halt

    // One report word (x10). Changes x11.
put:
    lw    x11, MB_STATUS(x15)
    andi  x11, x11, OUT_FULL
    bnez  x11, put
    sw    x10, MB_WDATA(x15)
    jalr  x0, 0(x1)

    // x13 words from x12 up. Changes x10-x13.
put_blk:
    lw    x10, 0(x12)
    jal   x1, put
    addi  x12, x12, 4
    addi  x13, x13, -1
    bnez  x13, put_blk
    jalr  x0, 0(x9)

    // The word at each of x13 addresses listed from x12 up. Changes x3, x10-x13.
put_tbl:
    lw    x3, 0(x12)
    lw    x10, 0(x3)
    jal   x1, put
    addi  x12, x12, 4
    addi  x13, x13, -1
    bnez  x13, put_tbl
    jalr  x0, 0(x9)

    .balign 4
tbl_a:
    .word KEY_MANAGER_KMCSR_IRQ_STATUS_BASE_ADDR
    .word KEY_MANAGER_KMCSR_IRQ_ENABLE_BASE_ADDR
    .word KEY_MANAGER_MAILBOX_KM_KM_IRQ_ENABLE_BASE_ADDR
    .word KEY_MANAGER_KMCSR_IRQ_ENTRY_ADDR_BASE_ADDR
    .word KEY_MANAGER_KMCSR_IRQ_ENTRY_LOCK_BASE_ADDR
tbl_b:
    .word KEY_MANAGER_KMCSR_SRAM_EXEC_MODE_BASE_ADDR
    .word KEY_MANAGER_KMCSR_OTP_READ_LOCK_BASE_ADDR
    .word KEY_MANAGER_KMCSR_OTP_CHIPLET_UID_VAL_0_BASE_ADDR
    .word KEY_MANAGER_KMCSR_OTP_SIP_UID_VAL_0_BASE_ADDR
    .word KEY_MANAGER_KMCSR_OTP_SYS_UID_VAL_0_BASE_ADDR
    .word KEY_MANAGER_KMCSR_OTP_CLASS_KEY_VAL_0_BASE_ADDR
    .word KEY_MANAGER_KMCSR_OTP_SEP_CHIPLET_ID_VAL_0_BASE_ADDR
    .word KEY_MANAGER_KMCSR_OTP_SEP_SIP_ID_VAL_0_BASE_ADDR
    .word KEY_MANAGER_KMCSR_OTP_SEP_SYS_ID_VAL_0_BASE_ADDR
    .word KEY_MANAGER_KMCSR_SRAM_LOCK_BASE_ADDR
    .word KEY_MANAGER_MAILBOX_KM_KM_STATUS_BASE_ADDR
tbl_c:
    .word (KEY_MANAGER_HMAC_WRAPPER_KEY_BASE_ADDR + HMAC_WRAPPER_KEY_KEY_CTRL_BASE_ADDR)
    .word KMAC_KEY_CTRL
    .word (KEY_MANAGER_AES_WRAPPER_KEY_BASE_ADDR + AES_WRAPPER_KEY_KEY_CTRL_BASE_ADDR)
    .word (KEY_MANAGER_OTBN_WRAPPER_KEY_BASE_ADDR + OTBN_WRAPPER_KEY_KEY_CTRL_BASE_ADDR)
    .word (KEY_MANAGER_ABR_WRAPPER_KEY_BASE_ADDR + ABR_WRAPPER_KEY_MLDSA_SEED_KEY_CTRL_BASE_ADDR)
    .word (KEY_MANAGER_ABR_WRAPPER_KEY_BASE_ADDR + ABR_WRAPPER_KEY_MLKEM_SEED_D_KEY_CTRL_BASE_ADDR)
    .word (KEY_MANAGER_ABR_WRAPPER_KEY_BASE_ADDR + ABR_WRAPPER_KEY_MLKEM_SEED_Z_KEY_CTRL_BASE_ADDR)
    .word (KEY_MANAGER_ABR_WRAPPER_KEY_BASE_ADDR + ABR_WRAPPER_KEY_MLKEM_MSG_KEY_CTRL_BASE_ADDR)
    .word (KEY_MANAGER_ABR_WRAPPER_KEY_BASE_ADDR + ABR_WRAPPER_KEY_MLKEM_SHARED_KEY_KEY_CTRL_BASE_ADDR)
own:
    .word 0x4F574E31            // "OWN1": the data word of the image-region store

    .if ((tbl_b - tbl_a) != 4 * N_TBL_A) || ((tbl_c - tbl_b) != 4 * N_TBL_B) || ((own - tbl_c) != 4 * N_TBL_C)
    .error "N_TBL_A, N_TBL_B or N_TBL_C does not match its table"
    .endif
