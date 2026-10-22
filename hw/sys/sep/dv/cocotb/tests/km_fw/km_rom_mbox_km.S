# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM ROM "IMG-MBOX-KM": the KM-side script of sep_km_mailbox_km_side_rand_test.
# The image is a legal master of the KM side of the mailbox. It runs a fixed
# list of phases, takes every drawn value (counts, words, orders, the enable
# subset S) from the parameter block at ROM word 0xF00, and writes what the DUT
# returned to KM SRAM words 0-97 (`km_sram_probe_o`). The image grades nothing.
# Every golden lives in the host test.
#
# PicoRV32 is RV32E (x0-x15 only). Do not use x16+.
#
# ---------------------------------------------------------------------------
# Parameter block (cocotb/env/sep_km_img_param.py, MboxPlan)
#
# dv_sim_prestage.py appends the block of the leaf seed to a copy of this
# image at ROM byte PARAM_BASE (word 0xF00). Words: magic, version and block
# id, payload length, payload, XOR check word. The image checks all four
# before its first phase and reports the check word. The payload offsets
# below are those of MboxPlan.OFF_*; the host compares them with the table at
# SIG_ADDR before it grades.
#   flush_one: bit 0 is the KM "one FIFO" cell, bit 1 the SEP one;
#              0 = the outbound FIFO is the filled one, 1 = the inbound FIFO.
#   err_first: bit 0 is the first response-bit value of the underflow pair,
#              bit 1 that of the overflow pair.
#   flush_order: cell id of position i in bits [3i+2:3i]. Cell ids: 0 KM both
#              empty, 1 KM one non-empty, 2 KM both non-empty, 3-5 the same for
#              a SEP flush.
#   src_order: source of step j in bits [2j+1:2j].
#
# ---------------------------------------------------------------------------
# Host handshake
#
# The image publishes a phase in STATE (word 0) after it has written the
# report words of that phase. STATE = STATE_MAGIC | seq << 8 | phase; seq
# counts publishes, so the host waits for one exact (seq, phase) pair. The
# image then waits for the host action of the phase, which it sees on the KM
# side of the mailbox:
#   - the sync word: one SYNC_WORD written to SEP_WRITE_DATA while the inbound
#     FIFO is empty. The image reads it, checks its value, and checks that the
#     inbound FIFO is empty again. It is a handshake, not stimulus;
#   - an inbound fill level, an outbound slot, or the flushed_by_sep status,
#     where the host action of the phase is that FIFO event.
# Every wait is bounded (POLL_BOUND reads). A failed wait, a wrong sync word
# or a bad parameter block writes ERR (word 1) and STATE phase PH_ERROR, and
# the image stops.
#
# Phases and report words (R<i> = SRAM word W_R + i):
#   PH_RST       R0-R4 KM_STATUS, KM_CTRL, KM_IRQ_ENABLE, KM_WRITE_SEPARATOR,
#                KM_IRQ_STATUS as read first after reset; R5 the check word;
#                R6/R7 the drawn N and M. Then sync.
#   PH_OUT       one outbound pass: R0 k, R1 n, R2 KM_WRITE_SEPARATOR after the
#                arm, R3 after the last write, R4 KM_STATUS. Then sync (the
#                host reads the n words first).
#   PH_IN_READY  R0 k, R1 m; the image waits for m inbound words.
#   PH_IN_MID    R2 KM_STATUS with the m words queued, R3/R4 KM_IRQ_STATUS
#                before and after the reads (pass 0 only), R5+2i/R6+2i the
#                word i and KM_STATUS after it. The image waits for one more
#                word.
#   PH_IN        R5+2m/R6+2m the extra word and KM_STATUS after it. Then sync.
#   PH_ERR       one error pass (see err_udf / err_ovf). Then sync.
#   PH_FL_FILLED one flush cell is filled on the KM side; the image waits for
#                the host fill and a sync word behind it.
#   PH_FL_PRE    SEP cells: the pre-flush KM_STATUS is in R3; the image waits
#                for flushed_by_sep and the post-flush sync word.
#   PH_FL_DONE   R0-R12 of the cell (see flush_cell). Then sync.
#   PH_IRQ_START R0 KM_CTRL, R1/R2 IRQ_STATUS before and after the clear, R3
#                IRQ_ENABLE. Then sync.
#   PH_IRQ_NEED  ERR word = run << 8 | source; the host raises that source.
#   PH_IRQ_RUN   R0 run, R1 enable, R2/R3 KM_STATUS/KM_IRQ_STATUS after the
#                sticky clear, R4 the word read to clear source 0, R5 the data
#                of the source 3 read, R7 KM_STATUS after the 16 writes,
#                R8+5c.. check cycle c (see cycle). Then sync.
#   PH_IRQ_CTL   R0-R4 the KMCSR control cycle, R5 IRQ_STATUS after the clear,
#                R6 IRQ_ENABLE, R7 KM_IRQ_ENABLE. Then sync.
#   PH_END       R0 KM_STATUS. The image idles with no mailbox access.
#
# Check cycle (5 words): KM_IRQ_STATUS, KM_IRQ_ENABLE, IRQ_STATUS, then the
# entries of the CPU IRQ 4 and the CPU IRQ 3 handler over one quiet window.
# The quiet window unmasks CPU IRQ bits 3 and 4 for QUIET_ITERS loop passes
# with no bus access but instruction fetch. Bits 3-5 of the KM CPU are level
# inputs. The handler at 0x10 counts the served lines 3 and 4 in CNT3/CNT4
# and masks every line, so a line adds at most one entry per window. Outside a
# window every line is masked.
#
# KM SRAM layout (word index from 0x8000; region 0)
#   0       STATE
#   1       ERR / AUX: [31:24] error code, [23:0] detail; the source request
#           of PH_IRQ_NEED
#   2,3     CNT3, CNT4
#   4       BUS    KMCSR IRQ_STATUS as read just before each publish; its
#                  AXI_SLVERR and AXI_DECERR bits show an error response on
#                  any KM bus access since they were last cleared
#   5..97   report words R0..R92
#   98..127 image context
#   128..255 stack (grows down from the end of region 0)
# Boot clears words 1..127.
#
# The field masks below that km_fields.inc does not carry are typed from
# km_mailbox_km.adoc and km_csr.adoc. The table at SIG_ADDR lists every mask,
# offset and constant the image uses; the host checks it against the
# generated register header and MboxPlan, and fails the leaf on a difference.
#
# Build (output committed as ../km_rom_mbox_km.parhex):
#   make -C hw/sys/sep/dv/cocotb/tests/km_fw ../km_rom_mbox_km.parhex

#include "key_manager_addr.h"
#include "km_fields.inc"

    .equ MB_BASE,   KEY_MANAGER_MAILBOX_KM_BASE_ADDR
    .equ MB_WDATA,  (KEY_MANAGER_MAILBOX_KM_KM_WRITE_DATA_BASE_ADDR - MB_BASE)
    .equ MB_WSEP,   (KEY_MANAGER_MAILBOX_KM_KM_WRITE_SEPARATOR_BASE_ADDR - MB_BASE)
    .equ MB_RDATA,  (KEY_MANAGER_MAILBOX_KM_KM_READ_DATA_BASE_ADDR - MB_BASE)
    .equ MB_STATUS, (KEY_MANAGER_MAILBOX_KM_KM_STATUS_BASE_ADDR - MB_BASE)
    .equ MB_IRQST,  (KEY_MANAGER_MAILBOX_KM_KM_IRQ_STATUS_BASE_ADDR - MB_BASE)
    .equ MB_IRQEN,  (KEY_MANAGER_MAILBOX_KM_KM_IRQ_ENABLE_BASE_ADDR - MB_BASE)
    .equ MB_CTRL,   (KEY_MANAGER_MAILBOX_KM_KM_CTRL_BASE_ADDR - MB_BASE)
    .equ CSR_IRQ_STATUS, KEY_MANAGER_KMCSR_IRQ_STATUS_BASE_ADDR
    .equ CSR_EN_OFF,  (KEY_MANAGER_KMCSR_IRQ_ENABLE_BASE_ADDR - CSR_IRQ_STATUS)
    .equ CSR_SET_OFF, (KEY_MANAGER_KMCSR_IRQ_SET_BASE_ADDR - CSR_IRQ_STATUS)
    .equ SRAM_BASE, KEY_MANAGER_SRAM_BASE_ADDR

    // KM_STATUS
    .equ ST_IN_EMPTY,     KM_MAILBOX_KM__STATUS_REG__INBOUND_EMPTY_bm
    .equ ST_OUT_FULL,     KM_MAILBOX_KM__STATUS_REG__OUTBOUND_FULL_bm
    .equ ST_IN_DEPTH_LSB, 4
    .equ ST_DEPTH_FIELD,  0xFF
    .equ ST_OUT_OVF,      (1 << 21)
    .equ ST_IN_UDF,       (1 << 22)
    .equ ST_STICKY,       (0xF << 20)
    // KM_IRQ_STATUS
    .equ IRQ_OUT_OVF,     (1 << 2)
    .equ IRQ_IN_UDF,      (1 << 3)
    .equ IRQ_FLUSHED,     (1 << 4)
    .equ IRQ_STICKY,      (IRQ_OUT_OVF | IRQ_IN_UDF | IRQ_FLUSHED)
    // KM_CTRL
    .equ CTRL_OVF_RESP,   (1 << 0)
    .equ CTRL_UDF_RESP,   (1 << 1)
    .equ CTRL_FLUSH,      (1 << 2)
    // KM_WRITE_SEPARATOR
    .equ SEP_SET,         KM_MAILBOX_KM__WRITE_SEPARATOR_REG__SET_bm
    // KMCSR IRQ_STATUS / IRQ_ENABLE / IRQ_SET
    .equ CSR_SLVERR,      KM_CSR__IRQ_STATUS_REG__AXI_SLVERR_bm
    .equ CSR_DRBG,        KM_CSR__IRQ_STATUS_REG__DRBG_ERR_bm
    .equ CSR_DRBG_EN,     (1 << 6)
    .equ CSR_DRBG_SET,    (1 << 6)
    .equ CSR_IRQ_ALL,     0xFFF

    .if (ST_IN_EMPTY != 0x1) || (ST_OUT_FULL != 0x8) || (SEP_SET != 0x1)
    .error "KM_STATUS / KM_WRITE_SEPARATOR fields moved; update the typed masks"
    .endif
    .if (CSR_DRBG != CSR_DRBG_EN) || (CSR_SLVERR != 0x10)
    .error "KMCSR IRQ fields moved; update the typed masks"
    .endif

    // SRAM words
    .equ W_STATE, 0
    .equ W_AUX,   1
    .equ W_CNT3,  2
    .equ W_CNT4,  3
    .equ W_BUS,   4
    .equ W_R,     5
    .equ N_R,     93
    .equ W_SEQ,   98
    .equ W_CYC,   99            // address of the next check-cycle record
    .equ W_SRC,   100           // source of the current interrupt step
    .equ W_SAVE,  101           // handler save area
    .equ W_CLEAR_END, 128
    .equ STACK_TOP, (SRAM_BASE + 1024)
    .if (W_R + N_R) != 98
    .error "the report words must end at word 97"
    .endif

    .equ STATE_MAGIC, 0x4D420000
    .equ PH_RST,       0x01
    .equ PH_OUT,       0x02
    .equ PH_IN_READY,  0x03
    .equ PH_IN_MID,    0x04
    .equ PH_IN,        0x05
    .equ PH_ERR,       0x06
    .equ PH_FL_FILLED, 0x07
    .equ PH_FL_PRE,    0x08
    .equ PH_FL_DONE,   0x09
    .equ PH_IRQ_START, 0x0A
    .equ PH_IRQ_NEED,  0x0B
    .equ PH_IRQ_RUN,   0x0C
    .equ PH_IRQ_CTL,   0x0D
    .equ PH_END,       0x0E
    .equ PH_ERROR,     0xEE

    .equ ERR_PARAM,     1       // detail: 1 magic, 2 id, 3 length, 4 check word
    .equ ERR_SYNC_TO,   2       // detail: STATE when the wait started
    .equ ERR_SYNC_WORD, 3       // detail: low bits of the word read
    .equ ERR_SYNC_LEFT, 4       // detail: low bits of KM_STATUS
    .equ ERR_WAIT_TO,   5       // detail: wait point

    // Parameter block
    .equ PARAM_BASE,    0x3C00
    .equ PARAM_MAGIC,   0x4B4D5052
    .equ PARAM_ID_WORD, ((1 << 16) | 2)
    .equ PAYLOAD_WORDS, 133
    .equ PAYLOAD,       (PARAM_BASE + 12)
    .equ OFF_N,           0
    .equ OFF_M,           1
    .equ OFF_ERR_FIRST,   2
    .equ OFF_FLUSH_ORDER, 3
    .equ OFF_FLUSH_ONE,   4
    .equ OFF_IRQ_S,       5
    .equ OFF_SRC_ORDER,   6
    .equ OFF_OUT_PASS,    7
    .equ OFF_OVERFLOW,    55
    .equ OFF_OUT_FLUSH,   73
    .equ OFF_OUT_IRQ,     97
    .equ IRQ_RUN_WORDS,   18
    .equ FLUSH_FILL,      4

    .equ SYNC_WORD,    0x53594E43   // "SYNC"
    .equ QUIET_ITERS,  64
    .equ QUIET_MASK,   0xFFFFFFE7   // CPU IRQ bits 3 and 4 unmasked
    .equ SETTLE_READS, 32
    .equ POLL_BOUND,   200000
    .equ FLUSH_POLL,   1024
    .equ SIG_ADDR,     0x80

    // PicoRV32 custom0 instructions (q-register IRQ mode).
    .macro maskirq rd, rs       // mask = rs, rd = old mask
    .word ((0b0000011 << 25) | (\rs << 15) | (0b110 << 12) | (\rd << 7) | 0b0001011)
    .endm
    .macro getq rd, qs          // rd = q[qs]
    .word ((0b0000000 << 25) | (\qs << 15) | (0b100 << 12) | (\rd << 7) | 0b0001011)
    .endm
    .macro setq qd, rs          // q[qd] = rs
    .word ((0b0000001 << 25) | (\rs << 15) | (0b010 << 12) | (\qd << 7) | 0b0001011)
    .endm
    .macro retirq
    .word ((0b0000010 << 25) | 0b0001011)
    .endm

    .macro PUSH r
    addi  x2, x2, -4
    sw    \r, 0(x2)
    .endm
    .macro POP r
    lw    \r, 0(x2)
    addi  x2, x2, 4
    .endm
    // Store register \r to report word R\i.
    .macro RST r, i
    sw    \r, (W_R + \i) * 4(x3)
    .endm
    .macro PUB ph
    li    x10, \ph
    jal   x1, publish
    .endm
    .macro FAIL code, detail
    li    x10, \code
    li    x11, \detail
    j     fail
    .endm
    // Load payload word \off into \rd.
    .macro PW rd, off
    lw    \rd, (\off * 4)(x6)
    .endm

    # Registers: x2 stack, x3 SRAM_BASE, x4 MB_BASE, x5 KMCSR IRQ_STATUS,
    # x6 payload, x7-x12 scratch and arguments, x13-x15 phase locals. A helper
    # changes only x7-x12.

    .section .text
    .globl _start
_start:
    j     boot

    .org 0x10
irq_vec:
    j     irq_handler

    // Layout table: the host reads it from the committed .parhex.
    .org SIG_ADDR
    .word 0x4D424B4D            // "MBKM"
    .word 1                     // layout version
    .word PARAM_BASE
    .word PARAM_ID_WORD
    .word PAYLOAD_WORDS
    .word OFF_N, OFF_M, OFF_ERR_FIRST, OFF_FLUSH_ORDER, OFF_FLUSH_ONE, OFF_IRQ_S
    .word OFF_SRC_ORDER, OFF_OUT_PASS, OFF_OVERFLOW, OFF_OUT_FLUSH, OFF_OUT_IRQ
    .word IRQ_RUN_WORDS, FLUSH_FILL
    .word SYNC_WORD, QUIET_ITERS, SETTLE_READS, W_R
    .word ST_IN_EMPTY, ST_OUT_FULL, ST_IN_DEPTH_LSB, ST_DEPTH_FIELD
    .word ST_OUT_OVF, ST_IN_UDF, ST_STICKY
    .word IRQ_OUT_OVF, IRQ_IN_UDF, IRQ_FLUSHED
    .word CTRL_OVF_RESP, CTRL_UDF_RESP, CTRL_FLUSH, SEP_SET
    .word CSR_SLVERR, CSR_DRBG, CSR_DRBG_EN, CSR_DRBG_SET, CSR_IRQ_ALL
    .word STATE_MAGIC
sig_end:

boot:
    li    x1, 0
    li    x7, -1
    maskirq 0, 7
    li    x3, SRAM_BASE
    li    x2, STACK_TOP
    li    x4, MB_BASE
    li    x5, CSR_IRQ_STATUS
    li    x6, PAYLOAD
    li    x8, 0
    li    x9, 0
    li    x10, 0
    li    x11, 0
    li    x12, 0
    li    x13, 0
    li    x14, 0
    li    x15, 0
    addi  x7, x3, 4
    addi  x8, x3, W_CLEAR_END * 4
1:  sw    x0, 0(x7)
    addi  x7, x7, 4
    bltu  x7, x8, 1b

    // Reset phase: the first mailbox accesses after reset.
    lw    x7, MB_STATUS(x4)
    RST   x7, 0
    lw    x7, MB_CTRL(x4)
    RST   x7, 1
    lw    x7, MB_IRQEN(x4)
    RST   x7, 2
    lw    x7, MB_WSEP(x4)
    RST   x7, 3
    lw    x7, MB_IRQST(x4)
    RST   x7, 4

    // Parameter block checks.
    li    x11, PARAM_BASE
    lw    x7, 0(x11)
    li    x8, PARAM_MAGIC
    beq   x7, x8, 2f
    FAIL  ERR_PARAM, 1
2:  lw    x7, 4(x11)
    li    x8, PARAM_ID_WORD
    beq   x7, x8, 3f
    FAIL  ERR_PARAM, 2
3:  lw    x7, 8(x11)
    li    x8, PAYLOAD_WORDS
    beq   x7, x8, 4f
    FAIL  ERR_PARAM, 3
4:  li    x12, PAYLOAD_WORDS + 3
    li    x10, 0
    mv    x9, x11
5:  lw    x7, 0(x9)
    xor   x10, x10, x7
    addi  x9, x9, 4
    addi  x12, x12, -1
    bnez  x12, 5b
    lw    x7, 0(x9)
    beq   x7, x10, 6f
    FAIL  ERR_PARAM, 4
6:  RST   x10, 5
    PW    x7, OFF_N
    RST   x7, 6
    PW    x7, OFF_M
    RST   x7, 7
    PUB   PH_RST
    jal   x1, sync

    jal   x1, phase_out
    jal   x1, phase_in
    jal   x1, phase_err
    jal   x1, phase_flush
    jal   x1, phase_irq

    lw    x7, MB_STATUS(x4)
    RST   x7, 0
    PUB   PH_END
end_idle:
    j     end_idle

# ---------------------------------------------------------------------------
# Helpers (change x7-x12 only).

    # x10 = phase. BUS = KMCSR IRQ_STATUS, then STATE = magic | ++seq << 8 | phase.
publish:
    lw    x7, 0(x5)
    sw    x7, W_BUS*4(x3)
    lw    x7, W_SEQ*4(x3)
    addi  x7, x7, 1
    andi  x7, x7, 0xFF
    sw    x7, W_SEQ*4(x3)
    slli  x7, x7, 8
    or    x7, x7, x10
    li    x8, STATE_MAGIC
    or    x7, x7, x8
    sw    x7, W_STATE*4(x3)
    jalr  x0, 0(x1)

    # x10 = code, x11 = detail. Never returns.
fail:
    slli  x10, x10, 24
    li    x8, 0xFFFFFF
    and   x11, x11, x8
    or    x10, x10, x11
    sw    x10, W_AUX*4(x3)
    lw    x7, W_SEQ*4(x3)
    slli  x7, x7, 8
    ori   x7, x7, PH_ERROR
    li    x8, STATE_MAGIC
    or    x7, x7, x8
    sw    x7, W_STATE*4(x3)
1:  j     1b

    # Bounded waits: x10 = 1 when the condition held, 0 after POLL_BOUND reads.
wait_in_nonempty:
    li    x9, POLL_BOUND
1:  lw    x7, MB_STATUS(x4)
    andi  x7, x7, ST_IN_EMPTY
    beqz  x7, 2f
    addi  x9, x9, -1
    bnez  x9, 1b
    li    x10, 0
    jalr  x0, 0(x1)
2:  li    x10, 1
    jalr  x0, 0(x1)

    # x11 = the inbound depth to wait for.
wait_in_depth:
    li    x9, POLL_BOUND
1:  lw    x7, MB_STATUS(x4)
    srli  x7, x7, ST_IN_DEPTH_LSB
    andi  x7, x7, ST_DEPTH_FIELD
    beq   x7, x11, 2f
    addi  x9, x9, -1
    bnez  x9, 1b
    li    x10, 0
    jalr  x0, 0(x1)
2:  li    x10, 1
    jalr  x0, 0(x1)

wait_out_not_full:
    li    x9, POLL_BOUND
1:  lw    x7, MB_STATUS(x4)
    andi  x7, x7, ST_OUT_FULL
    beqz  x7, 2f
    addi  x9, x9, -1
    bnez  x9, 1b
    li    x10, 0
    jalr  x0, 0(x1)
2:  li    x10, 1
    jalr  x0, 0(x1)

wait_irq_flushed:
    li    x9, POLL_BOUND
1:  lw    x7, MB_IRQST(x4)
    andi  x7, x7, IRQ_FLUSHED
    bnez  x7, 2f
    addi  x9, x9, -1
    bnez  x9, 1b
    li    x10, 0
    jalr  x0, 0(x1)
2:  li    x10, 1
    jalr  x0, 0(x1)

    # Read one inbound word and require SYNC_WORD and an empty inbound FIFO.
pop_sync:
    lw    x7, MB_RDATA(x4)
    li    x8, SYNC_WORD
    beq   x7, x8, 1f
    li    x10, ERR_SYNC_WORD
    mv    x11, x7
    j     fail
1:  lw    x7, MB_STATUS(x4)
    andi  x8, x7, ST_IN_EMPTY
    bnez  x8, 2f
    li    x10, ERR_SYNC_LEFT
    mv    x11, x7
    j     fail
2:  jalr  x0, 0(x1)

    # Wait for the sync word and take it.
sync:
    PUSH  x1
    jal   x1, wait_in_nonempty
    bnez  x10, 1f
    li    x10, ERR_SYNC_TO
    lw    x11, W_STATE*4(x3)
    j     fail
1:  jal   x1, pop_sync
    POP   x1
    jalr  x0, 0(x1)

    # x10 = OR of SETTLE_READS reads of KMCSR IRQ_STATUS.
settle:
    li    x8, SETTLE_READS
    li    x10, 0
1:  lw    x7, 0(x5)
    or    x10, x10, x7
    addi  x8, x8, -1
    bnez  x8, 1b
    jalr  x0, 0(x1)

    # Write x12 words from ROM address x11 to KM_WRITE_DATA; x11 ends past them.
wr_words:
    beqz  x12, 2f
1:  lw    x7, 0(x11)
    sw    x7, MB_WDATA(x4)
    addi  x11, x11, 4
    addi  x12, x12, -1
    bnez  x12, 1b
2:  jalr  x0, 0(x1)

    # Quiet window: CPU IRQ bits 3 and 4 unmasked for QUIET_ITERS passes.
qwin:
    li    x7, QUIET_MASK
    maskirq 0, 7
    li    x8, QUIET_ITERS
1:  addi  x8, x8, -1
    bnez  x8, 1b
    li    x7, -1
    maskirq 0, 7
    jalr  x0, 0(x1)

    # One check cycle; the record goes to W_CYC, which then moves on.
cycle:
    PUSH  x1
    lw    x10, W_CYC*4(x3)
    lw    x7, MB_IRQST(x4)
    sw    x7, 0(x10)
    lw    x7, MB_IRQEN(x4)
    sw    x7, 4(x10)
    lw    x7, 0(x5)
    sw    x7, 8(x10)
    lw    x11, W_CNT4*4(x3)
    lw    x12, W_CNT3*4(x3)
    jal   x1, qwin
    lw    x7, W_CNT4*4(x3)
    sub   x7, x7, x11
    sw    x7, 12(x10)
    lw    x7, W_CNT3*4(x3)
    sub   x7, x7, x12
    sw    x7, 16(x10)
    addi  x10, x10, 20
    sw    x10, W_CYC*4(x3)
    POP   x1
    jalr  x0, 0(x1)

# ---------------------------------------------------------------------------
# Outbound passes: n = 16, 1, 15 and the drawn N.

phase_out:
    PUSH  x1
    li    x13, 0
    li    x14, 16
    addi  x15, x6, OFF_OUT_PASS * 4
    jal   x1, out_pass
    li    x13, 1
    li    x14, 1
    addi  x15, x6, (OFF_OUT_PASS + 16) * 4
    jal   x1, out_pass
    li    x13, 2
    li    x14, 15
    addi  x15, x6, (OFF_OUT_PASS + 17) * 4
    jal   x1, out_pass
    li    x13, 3
    PW    x14, OFF_N
    addi  x15, x6, (OFF_OUT_PASS + 32) * 4
    jal   x1, out_pass
    POP   x1
    jalr  x0, 0(x1)

    # x13 = pass, x14 = n, x15 = ROM address of the words.
out_pass:
    PUSH  x1
    RST   x13, 0
    RST   x14, 1
    mv    x11, x15
    addi  x12, x14, -1
    jal   x1, wr_words
    li    x7, SEP_SET
    sw    x7, MB_WSEP(x4)
    lw    x7, MB_WSEP(x4)
    RST   x7, 2
    lw    x7, 0(x11)
    sw    x7, MB_WDATA(x4)
    lw    x7, MB_WSEP(x4)
    RST   x7, 3
    lw    x7, MB_STATUS(x4)
    RST   x7, 4
    PUB   PH_OUT
    jal   x1, sync
    POP   x1
    jalr  x0, 0(x1)

# ---------------------------------------------------------------------------
# Inbound passes: m = 16, 1, 15 and the drawn M.

phase_in:
    PUSH  x1
    li    x13, 0
    li    x14, 16
    jal   x1, in_pass
    li    x13, 1
    li    x14, 1
    jal   x1, in_pass
    li    x13, 2
    li    x14, 15
    jal   x1, in_pass
    li    x13, 3
    PW    x14, OFF_M
    jal   x1, in_pass
    POP   x1
    jalr  x0, 0(x1)

    # x13 = pass, x14 = m.
in_pass:
    PUSH  x1
    RST   x13, 0
    RST   x14, 1
    PUB   PH_IN_READY
    mv    x11, x14
    jal   x1, wait_in_depth
    bnez  x10, 1f
    FAIL  ERR_WAIT_TO, 0x31
1:  lw    x7, MB_STATUS(x4)
    RST   x7, 2
    bnez  x13, 2f
    lw    x7, MB_IRQST(x4)
    RST   x7, 3
2:  addi  x15, x3, (W_R + 5) * 4
    mv    x12, x14
3:  lw    x7, MB_RDATA(x4)
    sw    x7, 0(x15)
    lw    x7, MB_STATUS(x4)
    sw    x7, 4(x15)
    addi  x15, x15, 8
    addi  x12, x12, -1
    bnez  x12, 3b
    bnez  x13, 4f
    lw    x7, MB_IRQST(x4)
    RST   x7, 4
4:  PUB   PH_IN_MID
    jal   x1, wait_in_nonempty
    bnez  x10, 5f
    FAIL  ERR_WAIT_TO, 0x32
5:  lw    x7, MB_RDATA(x4)
    sw    x7, 0(x15)
    lw    x7, MB_STATUS(x4)
    sw    x7, 4(x15)
    PUB   PH_IN
    jal   x1, sync
    POP   x1
    jalr  x0, 0(x1)

# ---------------------------------------------------------------------------
# Error passes: underflow with each response-bit value, then overflow.

phase_err:
    PUSH  x1
    PW    x7, OFF_ERR_FIRST
    andi  x14, x7, 1
    li    x13, 0
    jal   x1, err_udf
    PW    x7, OFF_ERR_FIRST
    andi  x14, x7, 1
    xori  x14, x14, 1
    li    x13, 1
    jal   x1, err_udf
    PW    x7, OFF_ERR_FIRST
    srli  x14, x7, 1
    andi  x14, x14, 1
    li    x13, 2
    jal   x1, err_ovf
    PW    x7, OFF_ERR_FIRST
    srli  x14, x7, 1
    andi  x14, x14, 1
    xori  x14, x14, 1
    li    x13, 3
    jal   x1, err_ovf
    POP   x1
    jalr  x0, 0(x1)

    # x13 = pass, x14 = response bit. R0 pass, R1 0 (underflow), R2 response
    # bit, R3 KM_CTRL, R4-R6 KM_STATUS / KM_IRQ_STATUS / IRQ_STATUS after the
    # clears, R7 data of the empty read, R8 IRQ_STATUS OR after it, R9/R10
    # KM_STATUS / KM_IRQ_STATUS, R11 KM_IRQ_STATUS after a write of 0, R12
    # after a write of 1, R13 KM_STATUS, R14/R15 the second empty read and
    # its IRQ_STATUS OR, R16 KM_STATUS, R17 KM_STATUS after a write of 1,
    # R18 KM_IRQ_STATUS.
err_udf:
    PUSH  x1
    RST   x13, 0
    RST   x0, 1
    RST   x14, 2
    li    x7, 0
    beqz  x14, 1f
    li    x7, CTRL_UDF_RESP
1:  sw    x7, MB_CTRL(x4)
    lw    x7, MB_CTRL(x4)
    RST   x7, 3
    li    x7, ST_IN_UDF
    sw    x7, MB_STATUS(x4)
    li    x7, IRQ_IN_UDF
    sw    x7, MB_IRQST(x4)
    li    x7, CSR_SLVERR
    sw    x7, 0(x5)
    lw    x7, MB_STATUS(x4)
    RST   x7, 4
    lw    x7, MB_IRQST(x4)
    RST   x7, 5
    lw    x7, 0(x5)
    RST   x7, 6
    lw    x7, MB_RDATA(x4)
    RST   x7, 7
    jal   x1, settle
    RST   x10, 8
    lw    x7, MB_STATUS(x4)
    RST   x7, 9
    lw    x7, MB_IRQST(x4)
    RST   x7, 10
    sw    x0, MB_IRQST(x4)
    lw    x7, MB_IRQST(x4)
    RST   x7, 11
    li    x7, IRQ_IN_UDF
    sw    x7, MB_IRQST(x4)
    lw    x7, MB_IRQST(x4)
    RST   x7, 12
    lw    x7, MB_STATUS(x4)
    RST   x7, 13
    lw    x7, MB_RDATA(x4)
    RST   x7, 14
    jal   x1, settle
    RST   x10, 15
    lw    x7, MB_STATUS(x4)
    RST   x7, 16
    li    x7, ST_IN_UDF
    sw    x7, MB_STATUS(x4)
    lw    x7, MB_STATUS(x4)
    RST   x7, 17
    lw    x7, MB_IRQST(x4)
    RST   x7, 18
    PUB   PH_ERR
    jal   x1, sync
    POP   x1
    jalr  x0, 0(x1)

    # x13 = pass, x14 = response bit. As err_udf, with R1 1 (overflow), R7
    # KM_STATUS after 16 words, R8 IRQ_STATUS OR after the 17th word, R14 0,
    # R15 IRQ_STATUS OR after the 18th word.
err_ovf:
    PUSH  x1
    RST   x13, 0
    li    x7, 1
    RST   x7, 1
    RST   x14, 2
    li    x7, 0
    beqz  x14, 1f
    li    x7, CTRL_OVF_RESP
1:  sw    x7, MB_CTRL(x4)
    lw    x7, MB_CTRL(x4)
    RST   x7, 3
    li    x7, ST_OUT_OVF
    sw    x7, MB_STATUS(x4)
    li    x7, IRQ_OUT_OVF
    sw    x7, MB_IRQST(x4)
    li    x7, CSR_SLVERR
    sw    x7, 0(x5)
    lw    x7, MB_STATUS(x4)
    RST   x7, 4
    lw    x7, MB_IRQST(x4)
    RST   x7, 5
    lw    x7, 0(x5)
    RST   x7, 6
    addi  x11, x6, OFF_OVERFLOW * 4
    li    x12, 16
    jal   x1, wr_words
    lw    x7, MB_STATUS(x4)
    RST   x7, 7
    lw    x7, 0(x11)
    sw    x7, MB_WDATA(x4)
    jal   x1, settle
    RST   x10, 8
    lw    x7, MB_STATUS(x4)
    RST   x7, 9
    lw    x7, MB_IRQST(x4)
    RST   x7, 10
    sw    x0, MB_IRQST(x4)
    lw    x7, MB_IRQST(x4)
    RST   x7, 11
    li    x7, IRQ_OUT_OVF
    sw    x7, MB_IRQST(x4)
    lw    x7, MB_IRQST(x4)
    RST   x7, 12
    lw    x7, MB_STATUS(x4)
    RST   x7, 13
    RST   x0, 14
    lw    x7, 4(x11)
    sw    x7, MB_WDATA(x4)
    jal   x1, settle
    RST   x10, 15
    lw    x7, MB_STATUS(x4)
    RST   x7, 16
    li    x7, ST_OUT_OVF
    sw    x7, MB_STATUS(x4)
    lw    x7, MB_STATUS(x4)
    RST   x7, 17
    lw    x7, MB_IRQST(x4)
    RST   x7, 18
    PUB   PH_ERR
    jal   x1, sync
    POP   x1
    jalr  x0, 0(x1)

# ---------------------------------------------------------------------------
# Flush cells in the drawn order.

    # The error passes leave AXI_SLVERR set; from here on BUS shows 0 for a
    # clean bus.
phase_flush:
    PUSH  x1
    li    x7, CSR_SLVERR
    sw    x7, 0(x5)
    li    x13, 0
1:  PW    x7, OFF_FLUSH_ORDER
    slli  x8, x13, 1
    add   x8, x8, x13
    srl   x7, x7, x8
    andi  x14, x7, 7
    jal   x1, flush_cell
    addi  x13, x13, 1
    li    x7, 6
    bltu  x13, x7, 1b
    POP   x1
    jalr  x0, 0(x1)

    # x13 = position, x14 = cell. x15 = fill: bit 0 outbound, bit 1 inbound.
    # R0 position, R1 cell, R2 KM_IRQ_STATUS after the write of 1 to
    # flushed_by_sep (SEP cells), R3 KM_STATUS before the flush, R4 the KM_CTRL
    # flush write, R5 the last KM_CTRL read of the poll, R6 the reads of the
    # poll, R7 KM_STATUS after the flush, R8-R10 KM_IRQ_STATUS after the flush,
    # after a write of 0 and after a write of 1 (SEP cells), R11 1 when
    # flushed_by_sep was seen (SEP cells), R12 KM_CTRL before the flush write.
flush_cell:
    PUSH  x1
    addi  x7, x3, W_R * 4
    addi  x8, x7, 13 * 4
1:  sw    x0, 0(x7)
    addi  x7, x7, 4
    bltu  x7, x8, 1b
    RST   x13, 0
    RST   x14, 1
    // x8 = fill kind (0 empty, 1 one, 2 both), x9 = 1 for a SEP cell.
    mv    x8, x14
    li    x9, 0
    li    x7, 3
    bltu  x14, x7, 2f
    addi  x8, x14, -3
    li    x9, 1
2:  li    x15, 0
    beqz  x8, 4f
    li    x15, 3
    li    x7, 2
    beq   x8, x7, 4f
    PW    x7, OFF_FLUSH_ONE
    srl   x7, x7, x9
    andi  x7, x7, 1
    li    x15, 1
    beqz  x7, 4f
    li    x15, 2
4:  beqz  x9, 5f
    li    x7, IRQ_FLUSHED
    sw    x7, MB_IRQST(x4)
    lw    x7, MB_IRQST(x4)
    RST   x7, 2
5:  andi  x7, x15, 1
    beqz  x7, 6f
    slli  x11, x14, 4
    add   x11, x11, x6
    addi  x11, x11, OFF_OUT_FLUSH * 4
    li    x12, FLUSH_FILL
    jal   x1, wr_words
6:  PUB   PH_FL_FILLED
    li    x11, 1
    andi  x7, x15, 2
    beqz  x7, 7f
    li    x11, FLUSH_FILL + 1
7:  jal   x1, wait_in_depth
    bnez  x10, 8f
    FAIL  ERR_WAIT_TO, 0x51
8:  andi  x7, x15, 2
    bnez  x7, 9f
    jal   x1, pop_sync
9:  lw    x7, MB_STATUS(x4)
    RST   x7, 3
    li    x7, 3
    bgeu  x14, x7, sep_flush

    // KM flush.
    lw    x7, MB_CTRL(x4)
    RST   x7, 12
    ori   x7, x7, CTRL_FLUSH
    sw    x7, MB_CTRL(x4)
    RST   x7, 4
    li    x9, FLUSH_POLL
    li    x12, 0
10: lw    x7, MB_CTRL(x4)
    addi  x12, x12, 1
    andi  x8, x7, CTRL_FLUSH
    beqz  x8, 11f
    addi  x9, x9, -1
    bnez  x9, 10b
11: RST   x7, 5
    RST   x12, 6
    lw    x7, MB_STATUS(x4)
    RST   x7, 7
    j     flush_done

sep_flush:
    PUB   PH_FL_PRE
    jal   x1, wait_irq_flushed
    RST   x10, 11
    li    x11, 1
    jal   x1, wait_in_depth
    bnez  x10, 12f
    FAIL  ERR_WAIT_TO, 0x52
12: jal   x1, pop_sync
    lw    x7, MB_STATUS(x4)
    RST   x7, 7
    lw    x7, MB_IRQST(x4)
    RST   x7, 8
    sw    x0, MB_IRQST(x4)
    lw    x7, MB_IRQST(x4)
    RST   x7, 9
    li    x7, IRQ_FLUSHED
    sw    x7, MB_IRQST(x4)
    lw    x7, MB_IRQST(x4)
    RST   x7, 10

flush_done:
    PUB   PH_FL_DONE
    jal   x1, sync
    POP   x1
    jalr  x0, 0(x1)

# ---------------------------------------------------------------------------
# Interrupt phase.

phase_irq:
    PUSH  x1
    li    x7, CTRL_OVF_RESP | CTRL_UDF_RESP
    sw    x7, MB_CTRL(x4)
    lw    x7, MB_CTRL(x4)
    RST   x7, 0
    lw    x7, 0(x5)
    RST   x7, 1
    li    x7, CSR_IRQ_ALL
    sw    x7, 0(x5)
    lw    x7, 0(x5)
    RST   x7, 2
    lw    x7, CSR_EN_OFF(x5)
    RST   x7, 3
    sw    x0, W_CNT3*4(x3)
    sw    x0, W_CNT4*4(x3)
    PUB   PH_IRQ_START
    jal   x1, sync

    li    x13, 0
    PW    x14, OFF_IRQ_S
    andi  x14, x14, 0x1F
    jal   x1, irq_run
    li    x13, 1
    PW    x14, OFF_IRQ_S
    xori  x14, x14, 0x1F
    andi  x14, x14, 0x1F
    jal   x1, irq_run

    // KMCSR route: DRBG_ERR through IRQ_SET with its enable on CPU IRQ bit 3.
    sw    x0, MB_IRQEN(x4)
    addi  x7, x3, W_R * 4
    sw    x7, W_CYC*4(x3)
    li    x7, CSR_DRBG_EN
    sw    x7, CSR_EN_OFF(x5)
    li    x7, CSR_DRBG_SET
    sw    x7, CSR_SET_OFF(x5)
    jal   x1, cycle
    li    x7, CSR_DRBG
    sw    x7, 0(x5)
    sw    x0, CSR_EN_OFF(x5)
    lw    x7, 0(x5)
    RST   x7, 5
    lw    x7, CSR_EN_OFF(x5)
    RST   x7, 6
    lw    x7, MB_IRQEN(x4)
    RST   x7, 7
    PUB   PH_IRQ_CTL
    jal   x1, sync
    POP   x1
    jalr  x0, 0(x1)

    # x13 = run, x14 = KM_IRQ_ENABLE value. x15 = ROM address of the run words.
irq_run:
    PUSH  x1
    RST   x13, 0
    RST   x14, 1
    sw    x0, MB_IRQEN(x4)
    slli  x15, x13, 6
    slli  x7, x13, 3
    add   x15, x15, x7
    add   x15, x15, x6
    addi  x15, x15, OFF_OUT_IRQ * 4
    mv    x11, x15
    li    x12, 16
    jal   x1, wr_words
    lw    x7, MB_STATUS(x4)
    RST   x7, 7
    li    x7, ST_STICKY
    sw    x7, MB_STATUS(x4)
    li    x7, IRQ_STICKY
    sw    x7, MB_IRQST(x4)
    lw    x7, MB_STATUS(x4)
    RST   x7, 2
    lw    x7, MB_IRQST(x4)
    RST   x7, 3
    RST   x0, 4
    RST   x0, 5
    sw    x14, MB_IRQEN(x4)
    addi  x7, x3, (W_R + 8) * 4
    sw    x7, W_CYC*4(x3)
    jal   x1, cycle
    li    x14, 0
1:  PW    x7, OFF_SRC_ORDER
    slli  x8, x14, 1
    srl   x7, x7, x8
    andi  x7, x7, 3
    sw    x7, W_SRC*4(x3)
    jal   x1, src_step
    addi  x14, x14, 1
    li    x7, 4
    bltu  x14, x7, 1b
    li    x7, 4
    sw    x7, W_SRC*4(x3)
    jal   x1, src_step
    PUB   PH_IRQ_RUN
    jal   x1, sync
    POP   x1
    jalr  x0, 0(x1)

    # Raise the source in W_SRC, run a cycle, clear it, run a cycle.
    # x13 = run, x15 = ROM address of the run words.
src_step:
    PUSH  x1
    lw    x7, W_SRC*4(x3)
    li    x8, 1
    beqz  x7, r_src0
    beq   x7, x8, r_src1
    li    x8, 2
    beq   x7, x8, r_src2
    li    x8, 3
    beq   x7, x8, r_src3
    j     r_src4
r_src0:
    jal   x1, need
    jal   x1, wait_in_nonempty
    bnez  x10, raised
    FAIL  ERR_WAIT_TO, 0x60
r_src1:
    jal   x1, need
    jal   x1, wait_out_not_full
    bnez  x10, raised
    FAIL  ERR_WAIT_TO, 0x61
r_src2:
    lw    x7, (IRQ_RUN_WORDS - 1) * 4(x15)
    sw    x7, MB_WDATA(x4)
    j     raised
r_src3:
    lw    x7, MB_RDATA(x4)
    RST   x7, 5
    j     raised
r_src4:
    jal   x1, need
    jal   x1, sync
raised:
    jal   x1, cycle
    lw    x7, W_SRC*4(x3)
    li    x8, 1
    beqz  x7, c_src0
    beq   x7, x8, c_src1
    li    x8, 2
    beq   x7, x8, c_src2
    li    x8, 3
    beq   x7, x8, c_src3
    j     c_src4
c_src0:
    lw    x7, MB_RDATA(x4)
    RST   x7, 4
    j     cleared
c_src1:
    lw    x7, (IRQ_RUN_WORDS - 2) * 4(x15)
    sw    x7, MB_WDATA(x4)
    j     cleared
c_src2:
    li    x7, IRQ_OUT_OVF
    sw    x7, MB_IRQST(x4)
    li    x7, ST_OUT_OVF
    sw    x7, MB_STATUS(x4)
    j     cleared
c_src3:
    li    x7, IRQ_IN_UDF
    sw    x7, MB_IRQST(x4)
    li    x7, ST_IN_UDF
    sw    x7, MB_STATUS(x4)
    j     cleared
c_src4:
    li    x7, IRQ_FLUSHED
    sw    x7, MB_IRQST(x4)
cleared:
    jal   x1, cycle
    POP   x1
    jalr  x0, 0(x1)

    # Ask the host to raise the source in W_SRC: AUX = run << 8 | source.
need:
    lw    x7, W_SRC*4(x3)
    slli  x8, x13, 8
    or    x7, x7, x8
    sw    x7, W_AUX*4(x3)
    li    x10, PH_IRQ_NEED
    j     publish

# ---------------------------------------------------------------------------
# Interrupt handler at 0x10 (the IRQ_ENTRY_ADDR reset value).

irq_handler:
    setq  2, 1
    setq  3, 2
    getq  1, 1                  // x1 = served lines
    li    x2, SRAM_BASE
    sw    x3, W_SAVE*4(x2)
    andi  x3, x1, 0x08
    beqz  x3, 1f
    lw    x3, W_CNT3*4(x2)
    addi  x3, x3, 1
    sw    x3, W_CNT3*4(x2)
1:  andi  x3, x1, 0x10
    beqz  x3, 2f
    lw    x3, W_CNT4*4(x2)
    addi  x3, x3, 1
    sw    x3, W_CNT4*4(x2)
2:  li    x3, -1
    maskirq 0, 3                // every line masked until the next window
    lw    x3, W_SAVE*4(x2)
    getq  1, 2
    getq  2, 3
    retirq
    // The image must end below PARAM_BASE; sep_km_img_param.staged_text
    // refuses a template that reaches the block.
