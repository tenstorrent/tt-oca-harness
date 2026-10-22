# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM ROM IMG-SCR for sep_km_sram_scrambler_key_rand_test. Not rom_main: the
# test needs the SRAM scrambler key, enable and lock driven in a fixed order
# with drawn keys, addresses and words, and rom_main sets the lock at boot.
#
# PicoRV32 is RV32E (x0-x15 only). Do not use x16+.
#
# The image grades nothing. It reports every value it reads through the KM
# mailbox write register, and the host test compares them with the plan.
#
# Configuration. The drawn keys, addresses and words are in the parameter block
# at KM ROM byte PARAM_BASE (word 0xF00). cocotb/dv_sim_prestage.py appends the
# block of the leaf seed to a copy of this image (cocotb/env/sep_km_img_param.py,
# ScrPlan), and +km_rom_hex loads the copy at t=0. Block layout: magic, version
# and id, payload length, payload, XOR check word. The image checks the header
# and reports ERR_PARAM if it does not match.
#
# SRAM. The image performs no SRAM store other than the drawn stores and keeps
# all of its state in registers: a scrambled store can reach any row, so a
# result store could overwrite a drawn word that is still in use.
#
# Transport. Each boot starts with a bounded poll of KM_STATUS.inbound_empty
# for one phase word (PHASE_MAGIC | n, n = 1..4) that the host posts. Each
# report is one message of at most 16 words with the separator on its last
# word. After each message the image polls KM_STATUS.outbound_depth until it
# is 0 (bounded), so the outbound FIFO never holds more than one message. A
# timeout of either poll stops the image in the halt loop.
#
# Phase 1 (boot after the first release), messages in order:
#   8   the 8 words under kA          9   SCRAMBLER_CTRL with enable 0, 8 words
#   8   the 8 words under kB          1   MSG_READY, then the 64 stores
#   8   the 8 words under kA again    1   MSG_DONE
#   4 x 16  the 64 words under kA
#   1   SCRAMBLER_KEY read after kA is written, before the lock
#   2   SCRAMBLER_CTRL, SCRAMBLER_KEY after the lock (enable 1, lock 1)
#   8   the 8 words after kB is written with the lock set
#   9   SCRAMBLER_CTRL after a write of enable 0 / lock 1, 8 words
#   9   SCRAMBLER_CTRL after a write of enable 1 / lock 0, 8 words
# Phase 2 (after a warm reset): 9   SCRAMBLER_CTRL, the 8 words, no key write
# Phase 3 (after a cold reset): 2   SCRAMBLER_CTRL, SCRAMBLER_KEY after kB
# Phase 4 (after a cold reset): 1   MSG_READY; kA, store 1 with the lock clear
#                               1   MSG_ONE;   lock 1 / enable 0, store 2
#                               2   SCRAMBLER_CTRL, MSG_DONE
#
# The signature at SIG_ADDR lets the host check this layout and the field
# masks that are typed here against the generated register map.
#
# Build (output committed as ../km_rom_scr.parhex):
#   make -C hw/sys/sep/dv/cocotb/tests/km_fw ../km_rom_scr.parhex

#include "key_manager_addr.h"
#include "km_fields.inc"

#define SCR_ENABLE          KM_CSR__SCRAMBLER_CTRL_REG__ENABLE_bm
#define MBOX_INBOUND_EMPTY  KM_MAILBOX_KM__STATUS_REG__INBOUND_EMPTY_bm
    // Not in km_fields.inc; the host checks both against km_csr.h and
    // km_mailbox_km.h through the signature.
    .equ SCR_LOCK,        0x2
    .equ OUTBOUND_DEPTH_BP, 12
    .equ OUTBOUND_DEPTH_BW, 8

    .equ MBOX_WRITE_DATA, (KEY_MANAGER_MAILBOX_KM_KM_WRITE_DATA_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ MBOX_WRITE_SEP,  (KEY_MANAGER_MAILBOX_KM_KM_WRITE_SEPARATOR_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ MBOX_READ_DATA,  (KEY_MANAGER_MAILBOX_KM_KM_READ_DATA_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ MBOX_STATUS,     (KEY_MANAGER_MAILBOX_KM_KM_STATUS_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ SCR_CTRL_OFF,    (KEY_MANAGER_KMCSR_SCRAMBLER_CTRL_BASE_ADDR - KEY_MANAGER_KMCSR_SCRAMBLER_KEY_BASE_ADDR)

    // Parameter block (sep_km_img_param.py: PARAM_BASE_WORD, PARAM_MAGIC,
    // PARAM_VERSION, BLOCK_SCR, ScrPlan.OFF_* and PAYLOAD_WORDS).
    .equ PARAM_BASE,      (KEY_MANAGER_ROM_BASE_ADDR + 0xF00 * 4)
    .equ PARAM_MAGIC,     0x4B4D5052
    .equ PARAM_ID,        ((1 << 16) | 1)
    .equ PAYLOAD,         (PARAM_BASE + 12)
    .equ OFF_KA,          0
    .equ OFF_KB,          1
    .equ OFF_ADDRS8,      2
    .equ OFF_DATA8,       10
    .equ OFF_ORDER8,      18
    .equ OFF_ADDRS64,     19
    .equ OFF_DATA64,      83
    .equ OFF_ADDRS_LOCK,  147
    .equ OFF_DATA_LOCK,   149
    .equ PAYLOAD_WORDS,   151

    .equ PHASE_MAGIC,     0x50480000
    .equ MSG_READY,       0x52454459
    .equ MSG_ONE,         0x4F4E4531
    .equ MSG_DONE,        0x444F4E45
    .equ ERR_PARAM,       0xEEEE0001
    .equ ERR_PHASE,       0xEEEE0002
    .equ POLL_BOUND,      0x400000

    .equ SIG_ADDR,        0x40
    .equ SIG_MAGIC,       0x53435231   // "SCR1"
    .equ LAYOUT_VERSION,  1

    // Registers:
    //   x1  link (calls from the phase code)   x2  KM mailbox base
    //   x3  payload base (ROM)                 x4  SCRAMBLER_KEY address
    //   x5  scratch, poll count                x6..x13  the 8 words
    //   x14 scratch, phase word, status        x15 link (calls from routines)
    // drain and wait_in change x5 and x14 only.

    // \reg = payload word \off
    .macro pw reg, off
    lw    \reg, ((\off) * 4)(x3)
    .endm

    // One word into the outbound FIFO.
    .macro put reg
    sw    \reg, MBOX_WRITE_DATA(x2)
    .endm

    // The last word of a message, then wait until the host drained the FIFO.
    .macro put_last reg
    addi  x5, x0, 1
    sw    x5, MBOX_WRITE_SEP(x2)
    sw    \reg, MBOX_WRITE_DATA(x2)
    jal   x15, drain
    .endm

    .macro put_last_imm value
    li    x14, \value
    put_last x14
    .endm

    .section .text
    .globl _start
_start:
    j     boot

    // IRQ_ENTRY_ADDR reset value. Every CPU IRQ line stays masked (PicoRV32
    // reset mask), so this entry is not reached.
    .org 0x10
irq_vec:
    j     halt

    .org SIG_ADDR
    .word SIG_MAGIC
    .word LAYOUT_VERSION
    .word PARAM_BASE
    .word OFF_KA, OFF_KB, OFF_ADDRS8, OFF_DATA8, OFF_ORDER8
    .word OFF_ADDRS64, OFF_DATA64, OFF_ADDRS_LOCK, OFF_DATA_LOCK, PAYLOAD_WORDS
    .word SCR_ENABLE
    .word SCR_LOCK
    .word OUTBOUND_DEPTH_BP
    .word OUTBOUND_DEPTH_BW
    .word MBOX_INBOUND_EMPTY
    .word PHASE_MAGIC
    .word MSG_READY, MSG_ONE, MSG_DONE, ERR_PARAM, ERR_PHASE

boot:
    li    x2, KEY_MANAGER_MAILBOX_KM_BASE_ADDR
    li    x3, PAYLOAD
    li    x4, KEY_MANAGER_KMCSR_SCRAMBLER_KEY_BASE_ADDR

    // Header check: magic, version and id, payload length.
    li    x6, PARAM_BASE
    lw    x7, 0(x6)
    li    x8, PARAM_MAGIC
    bne   x7, x8, bad_param
    lw    x7, 4(x6)
    li    x8, PARAM_ID
    bne   x7, x8, bad_param
    lw    x7, 8(x6)
    li    x8, PAYLOAD_WORDS
    bne   x7, x8, bad_param

    // Phase word from the host.
    jal   x15, wait_in
    li    x5, 0xFFFF0000
    and   x6, x14, x5
    li    x5, PHASE_MAGIC
    bne   x6, x5, bad_phase
    li    x5, 0xFFFF
    and   x14, x14, x5
    addi  x5, x0, 1
    beq   x14, x5, phase1
    addi  x5, x0, 2
    beq   x14, x5, phase2
    addi  x5, x0, 3
    beq   x14, x5, phase3
    addi  x5, x0, 4
    beq   x14, x5, phase4
bad_phase:
    put_last_imm ERR_PHASE
    j     halt
bad_param:
    put_last_imm ERR_PARAM
halt:
    j     halt

    // ------------------------------------------------------------- phase 1
phase1:
    pw    x6, OFF_KA
    sw    x6, 0(x4)                 // SCRAMBLER_KEY = kA
    addi  x6, x0, SCR_ENABLE
    sw    x6, SCR_CTRL_OFF(x4)      // enable 1, lock 0

    // Scrambled writes 1-3: P at a1 and a2 under kA, P at a1 under kB.
    pw    x7, OFF_ADDRS8            // a1
    pw    x8, OFF_ADDRS8 + 1        // a2
    pw    x9, OFF_DATA8             // P
    sw    x9, 0(x7)
    sw    x9, 0(x8)
    pw    x6, OFF_KB
    sw    x6, 0(x4)                 // SCRAMBLER_KEY = kB
    sw    x9, 0(x7)
    pw    x6, OFF_KA
    sw    x6, 0(x4)                 // SCRAMBLER_KEY = kA

    // The 8 stores in the drawn order (nibble i = index of store i). Store 1
    // is scrambled write 4.
    pw    x10, OFF_ORDER8
    addi  x11, x0, 8
1:  andi  x6, x10, 0xF
    slli  x6, x6, 2
    add   x6, x6, x3
    lw    x7, (OFF_ADDRS8 * 4)(x6)
    lw    x8, (OFF_DATA8 * 4)(x6)
    sw    x8, 0(x7)
    srli  x10, x10, 4
    addi  x11, x11, -1
    bnez  x11, 1b

    jal   x1, rd8                   // under kA
    jal   x1, emit8

    pw    x6, OFF_KB
    sw    x6, 0(x4)                 // SCRAMBLER_KEY = kB
    jal   x1, rd8
    jal   x1, emit8

    pw    x6, OFF_KA
    sw    x6, 0(x4)                 // SCRAMBLER_KEY = kA
    jal   x1, rd8
    jal   x1, emit8

    sw    x0, SCR_CTRL_OFF(x4)      // enable 0, lock 0
    lw    x14, SCR_CTRL_OFF(x4)
    put   x14
    jal   x1, rd8
    jal   x1, emit8
    addi  x6, x0, SCR_ENABLE
    sw    x6, SCR_CTRL_OFF(x4)      // enable 1

    put_last_imm MSG_READY

    // The 64 stores under kA.
    mv    x10, x3
    addi  x11, x0, 64
2:  lw    x7, (OFF_ADDRS64 * 4)(x10)
    lw    x8, (OFF_DATA64 * 4)(x10)
    sw    x8, 0(x7)
    addi  x10, x10, 4
    addi  x11, x11, -1
    bnez  x11, 2b

    put_last_imm MSG_DONE

    // The 64 words, 4 messages of 16.
    mv    x10, x3
    addi  x12, x0, 4
3:  addi  x11, x0, 15
4:  lw    x7, (OFF_ADDRS64 * 4)(x10)
    lw    x8, 0(x7)
    put   x8
    addi  x10, x10, 4
    addi  x11, x11, -1
    bnez  x11, 4b
    lw    x7, (OFF_ADDRS64 * 4)(x10)
    lw    x8, 0(x7)
    put_last x8
    addi  x10, x10, 4
    addi  x12, x12, -1
    bnez  x12, 3b

    // Lock leg.
    pw    x6, OFF_KA
    sw    x6, 0(x4)                 // SCRAMBLER_KEY = kA
    lw    x14, 0(x4)
    put_last x14                    // key read before the lock
    addi  x6, x0, (SCR_ENABLE | SCR_LOCK)
    sw    x6, SCR_CTRL_OFF(x4)      // enable 1, lock 1 in one write

    lw    x14, SCR_CTRL_OFF(x4)
    put   x14
    lw    x14, 0(x4)
    put_last x14                    // key read with the lock set

    pw    x6, OFF_KB
    sw    x6, 0(x4)                 // key write with the lock set
    jal   x1, rd8
    jal   x1, emit8

    addi  x6, x0, SCR_LOCK
    sw    x6, SCR_CTRL_OFF(x4)      // enable 0, lock 1
    lw    x14, SCR_CTRL_OFF(x4)
    put   x14
    jal   x1, rd8
    jal   x1, emit8

    addi  x6, x0, SCR_ENABLE
    sw    x6, SCR_CTRL_OFF(x4)      // enable 1, lock 0
    lw    x14, SCR_CTRL_OFF(x4)
    put   x14
    jal   x1, rd8
    jal   x1, emit8
    j     halt

    // ------------------------------------------------------------- phase 2
phase2:
    lw    x14, SCR_CTRL_OFF(x4)
    put   x14
    jal   x1, rd8                   // no key write in this boot
    jal   x1, emit8
    j     halt

    // ------------------------------------------------------------- phase 3
phase3:
    lw    x14, SCR_CTRL_OFF(x4)
    put   x14
    pw    x6, OFF_KB
    sw    x6, 0(x4)                 // SCRAMBLER_KEY = kB
    lw    x14, 0(x4)
    put_last x14
    j     halt

    // ------------------------------------------------------------- phase 4
phase4:
    put_last_imm MSG_READY
    pw    x6, OFF_KA
    sw    x6, 0(x4)                 // SCRAMBLER_KEY = kA; enable 0, lock 0
    pw    x7, OFF_ADDRS_LOCK
    pw    x8, OFF_DATA_LOCK
    sw    x8, 0(x7)                 // store 1, lock clear
    put_last_imm MSG_ONE
    addi  x6, x0, SCR_LOCK
    sw    x6, SCR_CTRL_OFF(x4)      // enable 0, lock 1 in one write
    lw    x14, SCR_CTRL_OFF(x4)
    pw    x7, OFF_ADDRS_LOCK + 1
    pw    x8, OFF_DATA_LOCK + 1
    sw    x8, 0(x7)                 // store 2, lock set
    put   x14
    put_last_imm MSG_DONE
    j     halt

    // ------------------------------------------------------------ routines

    // x6..x13 = the 8 words at addrs8[0..7], 8 loads with no store between.
rd8:
    pw    x5, OFF_ADDRS8
    lw    x6, 0(x5)
    pw    x5, OFF_ADDRS8 + 1
    lw    x7, 0(x5)
    pw    x5, OFF_ADDRS8 + 2
    lw    x8, 0(x5)
    pw    x5, OFF_ADDRS8 + 3
    lw    x9, 0(x5)
    pw    x5, OFF_ADDRS8 + 4
    lw    x10, 0(x5)
    pw    x5, OFF_ADDRS8 + 5
    lw    x11, 0(x5)
    pw    x5, OFF_ADDRS8 + 6
    lw    x12, 0(x5)
    pw    x5, OFF_ADDRS8 + 7
    lw    x13, 0(x5)
    jalr  x0, 0(x1)

    // x6..x13 into the outbound FIFO; x13 ends the message.
emit8:
    put   x6
    put   x7
    put   x8
    put   x9
    put   x10
    put   x11
    put   x12
    put_last x13
    jalr  x0, 0(x1)

    // Bounded poll of KM_STATUS until outbound_depth is 0. Link x15.
drain:
    li    x5, POLL_BOUND
1:  lw    x14, MBOX_STATUS(x2)
    srli  x14, x14, OUTBOUND_DEPTH_BP
    andi  x14, x14, ((1 << OUTBOUND_DEPTH_BW) - 1)
    beqz  x14, 2f
    addi  x5, x5, -1
    bnez  x5, 1b
    j     halt
2:  jalr  x0, 0(x15)

    // Bounded poll of KM_STATUS until inbound_empty is 0; x14 = the word read.
    // Link x15.
wait_in:
    li    x5, POLL_BOUND
1:  lw    x14, MBOX_STATUS(x2)
    andi  x14, x14, MBOX_INBOUND_EMPTY
    beqz  x14, 2f
    addi  x5, x5, -1
    bnez  x5, 1b
    j     halt
2:  lw    x14, MBOX_READ_DATA(x2)
    jalr  x0, 0(x15)

    // The image must end below the parameter block at word 0xF00:
    // sep_km_img_param.staged_text raises when the template reaches it.
