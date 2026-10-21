# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM ROM "POKE": an interpreter for a list of KM bus operations. Not rom_main:
# the Key Manager hardware tests need the KM CPU as a plain, legal master of the
# KM bus, and the command set of rom_main reaches only a few of those accesses.
# The image grades nothing. It executes the operations the host posts and
# writes what the DUT returned to KM SRAM words 0-97 (`km_sram_probe_o`). Every
# golden lives in the host test.
#
# PicoRV32 is RV32E (x0-x15 only). Do not use x16+.
#
# The host side is cocotb/env/sep_km_poke.py (encoding, layout, decode) and
# cocotb/seq_lib/sep_km_poke_seq.py (transport). Both use the layout below,
# and the signature table at ROM 0x80 lets the host check it against this
# image.
#
# ---------------------------------------------------------------------------
# Transport
#
# The host writes a list to SEP_WRITE_DATA. The image reads it from
# KM_READ_DATA into an SRAM buffer, then executes it, so the inbound FIFO is
# empty while the operations run.
#   word 0     list header: [31:24] 0x50, [23:16] tag, [15:0] n
#   words 1..n op words (n <= BUF_WORDS)
#
# Op word 0 of each operation: [7:0] opcode, [8] RAW, [9] F (op-specific),
# [31:16] imm16. Arguments follow in the order of the table.
#
#   code name   args               slots  what the image does
#   0x00 NOP    -                  0      nothing (a re-arm point only)
#   0x01 RD     addr               1      data = lw addr
#   0x02 WR     addr data          1      sw data -> addr; data slot = 0
#   0x03 WR2    a1 d1 a2 d2        1      sw d1 -> a1, sw d2 -> a2 back to back;
#                                         F=1: data = lw a2 right after, else 0
#   0x04 POLL   addr mask val n    2      lw addr until (rd & mask) == val
#                                         (F=1: != val) or n reads (n >= 1);
#                                         slot 0 = last read, slot 1 = reads made
#   0x05 RDLOOP addr count stride  2      count reads, addr += stride each;
#                                         slot 0 = reads that were not 0,
#                                         slot 1 = OR of every read
#   0x06 RDBLK  addr stride        imm16  imm16 reads; one slot each, each with
#                                         its own clear and report
#   0x07 FILL   addr value         1      imm16 stores of value, addr += 4
#   0x08 WRBLK  addr w[imm16]      1      imm16 stores of the listed words
#   0x09 COPY   src dst            1      imm16 words read at src, stored at dst
#   0x0A JUMP   addr a0 a1         1      x10 = a0, x11 = a1, x1 = ENTRY_RESUME,
#                                         armed lines unmasked, jump to addr;
#                                         at ENTRY_RESUME: data = x12
#   0x0B EXEC   a0 a1              1      runs exec-table entry imm16 with every
#                                         CPU IRQ masked; x10 = a0, x11 = a1;
#                                         data = x12 after the entry
#   0x0C ARM    lines action       0      lines = CPU IRQ bits from {3,4,5};
#                                         action [7:0] ACT_*, [15:8] exec entry
#   0x0D CNT    -                  1      data = entries of CPU IRQ line imm16
#   0x0E MARK   value              1      data = value (a list marker)
#   0x0F DELAY  n                  0      n re-arm points
#   0x10 SYNC   -                  1      state SYNC; wait for one host word;
#                                         data = that word
#   0x11 RESETH value              0      handler counts = 0; HWORD = SPIN = value
#
# Clear and report. An op with a report clears IRQ_STATUS.AXI_SLVERR and
# AXI_DECERR (write one) before its access and reads IRQ_STATUS back once
# (pre bits). After the access it reads IRQ_STATUS SETTLE_READS times and ORs
# bits 4 and 5 of all reads (slv, dec). RD, WR, WR2, POLL, RDLOOP, RDBLK,
# FILL, WRBLK, COPY, JUMP and EXEC report; RAW=1 turns the clear and the report
# off and leaves the flag nibble 0. CNT, MARK and SYNC never report.
#
# CPU interrupts. Every CPU IRQ line is masked except at a re-arm point, where
# the lines of the last ARM are unmasked for one instruction. Re-arm points:
# before every op, every DELAY iteration, every poll of the mailbox while the
# image waits for a list or a SYNC word, and the whole time a JUMP target runs.
# The handler at 0x10 (the IRQ_ENTRY_ADDR reset value) counts one entry for
# each served line in CNT3/CNT4/CNT5, then masks every line until the next
# re-arm point.
# On a line 3 entry it also does the ARM action:
#   ACT_COUNT 0  nothing more
#   ACT_CLEAR 1  writes IRQ_STATUS & IRQ_ENABLE to IRQ_STATUS (write one)
#   ACT_SPIN  2  stores IRQ_STATUS to HWORD and jumps to ENTRY_SPIN
#   ACT_EXEC  3  runs exec-table entry [15:8] inside the handler
#
# ---------------------------------------------------------------------------
# KM SRAM layout (word index from 0x8000; region 0, never locked by a test)
#   0       STATE  0x504B0000 | state << 8 | tag
#                  state: 1 BOOT, 2 RUN, 3 DONE, 4 SYNC, 5 JUMP, 0xE ERROR
#   1       PROG   [15:0] ops completed, [31:16] slots written
#   2,3,4   CNT3, CNT4, CNT5   handler entries per CPU IRQ line
#   5       HWORD  IRQ_STATUS stored by the ACT_SPIN handler
#   6       SPIN   IRQ_STATUS stored by the ROM spin loop on every pass
#   7       ERR    [31:24] code, [23:0] low bits of the bad header or op word
#   8..17   FLAGS  one nibble per slot: bit 0 slv, 1 dec, 2 pre slv, 3 pre dec
#   18..97  DATA   80 result slots
#   98..127 image context (not in the probe)
#   128..255 list buffer (BUF_WORDS words)
# Boot clears words 1..127 and then writes STATE = BOOT. The start of a list
# clears FLAGS. Words a list does not reach keep their last value.
#
# Fixed ROM addresses: ENTRY_SPIN 0x20 (copies IRQ_STATUS to SPIN for ever),
# ENTRY_RESUME 0x40 (continues the list after a JUMP), signature 0x80, exec
# table 0x100 (EXEC_COUNT entries of 8 bytes: one instruction, then a return
# through x1). Entries: 0 ebreak; 1 the all-zero word; 2/3 lw x12 at x10+1/+2;
# 4/5 sw x11 at x10+1/+2; 6-10 custom0 funct7 0101100 funct3 3-7; 11-13 the
# CRC encodings funct3 0-2 (rd x12, rs1 x10, rs2 x11); 14-21 words of the
# major opcodes custom-1, custom-2, custom-3, OP-FP, OP-V, LOAD-FP, STORE-FP
# and AMO.
#
# Build (output committed as ../km_rom_poke.parhex):
#   make -C hw/sys/sep/dv/cocotb/tests/km_fw ../km_rom_poke.parhex

#include "key_manager_addr.h"
#include "km_fields.inc"

#define IRQ_AXI_SLVERR     KM_CSR__IRQ_STATUS_REG__AXI_SLVERR_bm
#define IRQ_AXI_DECERR     KM_CSR__IRQ_STATUS_REG__AXI_DECERR_bm
#define IRQ_AXI_ERR        (IRQ_AXI_SLVERR | IRQ_AXI_DECERR)
#define MBOX_INBOUND_EMPTY KM_MAILBOX_KM__STATUS_REG__INBOUND_EMPTY_bm

    // The report packs slv and dec as bits 0 and 1 of a nibble by a shift of
    // the two IRQ_STATUS bits, so the two must be bits 4 and 5.
    .if (IRQ_AXI_SLVERR != 0x10) || (IRQ_AXI_DECERR != 0x20)
    .error "AXI_SLVERR/AXI_DECERR are not IRQ_STATUS bits 4/5"
    .endif

    .equ MBOX_READ_DATA,  (KEY_MANAGER_MAILBOX_KM_KM_READ_DATA_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ MBOX_STATUS,     (KEY_MANAGER_MAILBOX_KM_KM_STATUS_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ SRAM_BASE,       KEY_MANAGER_SRAM_BASE_ADDR
    .equ IRQ_STATUS_A,    KEY_MANAGER_KMCSR_IRQ_STATUS_BASE_ADDR
    .equ IRQ_ENABLE_OFF,  (KEY_MANAGER_KMCSR_IRQ_ENABLE_BASE_ADDR - KEY_MANAGER_KMCSR_IRQ_STATUS_BASE_ADDR)

    // SRAM word indices.
    .equ W_STATE, 0
    .equ W_PROG,  1
    .equ W_CNT3,  2
    .equ W_CNT4,  3
    .equ W_CNT5,  4
    .equ W_HWORD, 5
    .equ W_SPIN,  6
    .equ W_ERR,   7
    .equ W_FLAGS, 8
    .equ W_DATA,  18
    .equ N_SLOTS, 80
    .equ W_ARM,   98            // CPU IRQ mask value of the armed lines
    .equ W_ACT,   99            // ARM action word
    .equ W_CUR,   100           // JUMP context: cursor, end, slot, pre bits, op word
    .equ W_END,   101
    .equ W_SLOT,  102
    .equ W_PRE,   103
    .equ W_OPW,   104
    .equ W_TAG,   105
    .equ W_OPS,   106           // ops completed
    .equ W_SAVE,  108           // handler save area x3..x15 (13 words)
    .equ W_CLEAR_END, 128
    .equ W_BUF,   128
    .equ BUF_WORDS, 128
    .if (W_DATA + N_SLOTS) != 98
    .error "the result slots must end at word 97"
    .endif
    .if (W_FLAGS + (N_SLOTS + 7) / 8) > W_DATA
    .error "the flag nibbles overlap the data slots"
    .endif
    .if (W_SAVE + 13) > W_BUF
    .error "the save area overlaps the list buffer"
    .endif

    .equ STATE_MAGIC, 0x504B0000
    .equ ST_BOOT,  1
    .equ ST_RUN,   2
    .equ ST_DONE,  3
    .equ ST_SYNC,  4
    .equ ST_JUMP,  5
    .equ ST_ERROR, 0xE

    .equ LIST_MAGIC, 0x50
    .equ F_RAW, 0x100
    .equ F_OPT, 0x200
    .equ IRQ_LINES, 0x38        // CPU IRQ bits 3, 4 and 5
    .equ SETTLE_READS, 32

    .equ ACT_COUNT, 0
    .equ ACT_CLEAR, 1
    .equ ACT_SPIN,  2
    .equ ACT_EXEC,  3

    .equ ERR_HDR,   1           // list header [31:24] is not LIST_MAGIC
    .equ ERR_LEN,   2           // list longer than BUF_WORDS
    .equ ERR_OP,    3           // unknown opcode
    .equ ERR_SLOT,  4           // more than N_SLOTS result slots
    .equ ERR_EXEC,  5           // exec-table index out of range
    .equ ERR_LINE,  6           // CNT line not 3, 4 or 5
    .equ ERR_TRUNC, 7           // op arguments run past the list end

    .equ ENTRY_SPIN,   0x20
    .equ ENTRY_RESUME, 0x40
    .equ SIG_ADDR,     0x80
    .equ EXEC_BASE,    0x100
    .equ EXEC_COUNT,   22
    .equ N_OPS,        18

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

    // Re-arm point: unmask the armed lines for one instruction, then mask
    // every line. Uses x7, x8; needs x2 = SRAM_BASE.
    .macro rearm
    lw    x7, W_ARM*4(x2)
    maskirq 0, 7
    addi  x0, x0, 0
    li    x8, -1
    maskirq 0, 8
    .endm

    // A custom0 CRC-family word: funct7 0101100, rd x12, rs1 x10, rs2 x11.
    .macro crc_word funct3
    .word ((0b0101100 << 25) | (11 << 20) | (10 << 15) | (\funct3 << 12) | (12 << 7) | 0b0001011)
    .endm
    // A word of major opcode \opc with rd x12, rs1 x10, rs2 x11, funct3 2.
    .macro opc_word opc
    .word ((11 << 20) | (10 << 15) | (2 << 12) | (12 << 7) | \opc)
    .endm

    .section .text
    .globl _start
_start:
    j     boot

    .org 0x10
irq_vec:
    j     irq_handler

    .org ENTRY_SPIN
rom_spin:
    li    x6, IRQ_STATUS_A
    li    x2, SRAM_BASE
1:  lw    x7, 0(x6)
    sw    x7, W_SPIN*4(x2)
    j     1b

    .org ENTRY_RESUME
rom_resume:
    j     resume_impl

    // Signature: the host reads this from the committed .parhex and checks
    // it against its own copy of the layout.
    .org SIG_ADDR
    .word 0x504F4B45            // "POKE"
    .word 1                     // layout version
    .word ENTRY_SPIN
    .word ENTRY_RESUME
    .word EXEC_BASE
    .word EXEC_COUNT
    .word W_FLAGS
    .word W_DATA
    .word N_SLOTS
    .word W_BUF
    .word BUF_WORDS
    .word SETTLE_READS

    .org EXEC_BASE
exec_table:
    ebreak                      // 0
    jalr  x0, 0(x1)
    .word 0x00000000            // 1
    jalr  x0, 0(x1)
    lw    x12, 1(x10)           // 2
    jalr  x0, 0(x1)
    lw    x12, 2(x10)           // 3
    jalr  x0, 0(x1)
    sw    x11, 1(x10)           // 4
    jalr  x0, 0(x1)
    sw    x11, 2(x10)           // 5
    jalr  x0, 0(x1)
    crc_word 3                  // 6
    jalr  x0, 0(x1)
    crc_word 4                  // 7
    jalr  x0, 0(x1)
    crc_word 5                  // 8
    jalr  x0, 0(x1)
    crc_word 6                  // 9
    jalr  x0, 0(x1)
    crc_word 7                  // 10
    jalr  x0, 0(x1)
    crc_word 0                  // 11
    jalr  x0, 0(x1)
    crc_word 1                  // 12
    jalr  x0, 0(x1)
    crc_word 2                  // 13
    jalr  x0, 0(x1)
    opc_word 0x2B               // 14 custom-1
    jalr  x0, 0(x1)
    opc_word 0x5B               // 15 custom-2
    jalr  x0, 0(x1)
    opc_word 0x7B               // 16 custom-3
    jalr  x0, 0(x1)
    opc_word 0x53               // 17 OP-FP
    jalr  x0, 0(x1)
    opc_word 0x57               // 18 OP-V
    jalr  x0, 0(x1)
    opc_word 0x07               // 19 LOAD-FP
    jalr  x0, 0(x1)
    opc_word 0x27               // 20 STORE-FP
    jalr  x0, 0(x1)
    opc_word 0x2F               // 21 AMO
    jalr  x0, 0(x1)
exec_table_end:
    .if (exec_table_end - exec_table) != (EXEC_COUNT * 8)
    .error "exec table size does not match EXEC_COUNT"
    .endif

op_table:
    .word op_nop, op_rd, op_wr, op_wr2, op_poll, op_rdloop, op_rdblk, op_fill
    .word op_wrblk, op_copy, op_jump, op_exec, op_arm, op_cnt, op_mark, op_delay
    .word op_sync, op_reseth
op_table_end:
    .if (op_table_end - op_table) != (N_OPS * 4)
    .error "op table size does not match N_OPS"
    .endif

    # Registers while a list runs:
    #   x1 link, x2 SRAM_BASE, x3 cursor, x4 list end, x5 slot,
    #   x6 IRQ_STATUS, x7-x9 helper scratch, x10-x12 and x15 op arguments,
    #   x12 result data, x13 pre bits (nibble bits 2-3), x14 op word.
boot:
    li    x1, 0
    li    x3, 0
    li    x4, 0
    li    x5, 0
    li    x6, 0
    li    x7, 0
    li    x8, 0
    li    x9, 0
    li    x10, 0
    li    x11, 0
    li    x12, 0
    li    x13, 0
    li    x14, 0
    li    x15, 0
    li    x2, SRAM_BASE
    li    x7, -1
    maskirq 0, 7
    addi  x7, x2, 4
    addi  x8, x2, W_CLEAR_END*4
1:  sw    x0, 0(x7)
    addi  x7, x7, 4
    bltu  x7, x8, 1b
    li    x7, -1
    sw    x7, W_ARM*4(x2)
    li    x7, STATE_MAGIC | (ST_BOOT << 8)
    sw    x7, W_STATE*4(x2)

list_wait:
    li    x2, SRAM_BASE
    li    x6, IRQ_STATUS_A
    jal   x1, mbox_get
    mv    x14, x10              // the header, for ERR
    srli  x7, x10, 24
    li    x8, LIST_MAGIC
    beq   x7, x8, 1f
    li    x9, ERR_HDR
    j     list_error
1:  srli  x7, x10, 16
    andi  x7, x7, 0xFF
    sw    x7, W_TAG*4(x2)
    slli  x11, x10, 16
    srli  x11, x11, 16          // n
    li    x8, BUF_WORDS
    bgeu  x8, x11, 2f
    li    x9, ERR_LEN
    j     list_error
2:  addi  x3, x2, W_BUF*4
    slli  x11, x11, 2
    add   x4, x3, x11           // list end
    mv    x11, x3
3:  bgeu  x11, x4, 4f
    jal   x1, mbox_get
    sw    x10, 0(x11)
    addi  x11, x11, 4
    j     3b
4:  sw    x0, W_OPS*4(x2)
    sw    x0, W_PROG*4(x2)
    addi  x7, x2, W_FLAGS*4
    addi  x8, x2, W_DATA*4
5:  sw    x0, 0(x7)
    addi  x7, x7, 4
    bltu  x7, x8, 5b
    li    x5, 0
    li    x9, ST_RUN
    jal   x1, set_state

op_loop:
    lw    x7, W_OPS*4(x2)
    slli  x8, x5, 16
    or    x7, x7, x8
    sw    x7, W_PROG*4(x2)
    bgeu  x3, x4, list_done
    rearm
    lw    x14, 0(x3)
    addi  x3, x3, 4
    li    x13, 0
    andi  x7, x14, 0xFF
    li    x8, N_OPS
    bltu  x7, x8, 1f
    li    x9, ERR_OP
    j     list_error
1:  slli  x7, x7, 2
    la    x8, op_table
    add   x8, x8, x7
    lw    x8, 0(x8)
    jalr  x0, 0(x8)

op_next:
    lw    x7, W_OPS*4(x2)
    addi  x7, x7, 1
    sw    x7, W_OPS*4(x2)
    j     op_loop

list_done:
    li    x9, ST_DONE
    jal   x1, set_state
    j     list_wait

    # x9 = error code, x14 = the bad header or op word.
list_error:
    slli  x9, x9, 24
    slli  x7, x14, 8
    srli  x7, x7, 8
    or    x9, x9, x7
    sw    x9, W_ERR*4(x2)
    li    x9, ST_ERROR
    jal   x1, set_state
    j     list_wait

    # STATE = magic | x9 << 8 | tag. Uses x7, x8.
set_state:
    lw    x7, W_TAG*4(x2)
    slli  x8, x9, 8
    or    x7, x7, x8
    li    x8, STATE_MAGIC
    or    x7, x7, x8
    sw    x7, W_STATE*4(x2)
    jalr  x0, 0(x1)

    # x10 = the next inbound mailbox word. Re-arms on every poll. Uses x7-x9.
mbox_get:
    li    x9, KEY_MANAGER_MAILBOX_KM_BASE_ADDR
1:  rearm
    lw    x7, MBOX_STATUS(x9)
    andi  x7, x7, MBOX_INBOUND_EMPTY
    beqz  x7, 2f                // continue only on a known 0
    j     1b
2:  lw    x10, MBOX_READ_DATA(x9)
    jalr  x0, 0(x1)

    # x15 = the next argument word. Uses x7.
arg:
    bltu  x3, x4, 1f
    li    x9, ERR_TRUNC
    j     list_error
1:  lw    x15, 0(x3)
    addi  x3, x3, 4
    jalr  x0, 0(x1)

    # Clear before an access: x13 = the pre bits. Uses x7.
pre:
    li    x13, 0
    andi  x7, x14, F_RAW
    bnez  x7, 1f
    li    x7, IRQ_AXI_ERR
    sw    x7, 0(x6)
    lw    x7, 0(x6)
    andi  x7, x7, IRQ_AXI_ERR
    srli  x13, x7, 2            // bits 4/5 -> nibble bits 2/3
1:  jalr  x0, 0(x1)

    # Report and store x12 in the next slot. Uses x7-x9.
finish:
    andi  x7, x14, F_RAW
    bnez  x7, put
    li    x8, 0
    li    x9, SETTLE_READS
1:  lw    x7, 0(x6)
    or    x8, x8, x7
    addi  x9, x9, -1
    bnez  x9, 1b
    andi  x8, x8, IRQ_AXI_ERR
    srli  x8, x8, 4
    or    x8, x8, x13
    j     put_flags

    # Store x12 in the next slot with no report. Uses x7-x9.
put:
    li    x8, 0
put_flags:
    li    x7, N_SLOTS
    bltu  x5, x7, 1f
    li    x9, ERR_SLOT
    j     list_error
1:  andi  x7, x5, 7
    slli  x7, x7, 2
    sll   x8, x8, x7
    srli  x9, x5, 3
    slli  x9, x9, 2
    add   x9, x9, x2
    lw    x7, W_FLAGS*4(x9)
    or    x7, x7, x8
    sw    x7, W_FLAGS*4(x9)
    slli  x9, x5, 2
    add   x9, x9, x2
    sw    x12, W_DATA*4(x9)
    addi  x5, x5, 1
    jalr  x0, 0(x1)

op_nop:
    j     op_next

op_rd:
    jal   x1, arg
    mv    x10, x15
    jal   x1, pre
    lw    x12, 0(x10)
    jal   x1, finish
    j     op_next

op_wr:
    jal   x1, arg
    mv    x10, x15
    jal   x1, arg
    mv    x11, x15
    jal   x1, pre
    sw    x11, 0(x10)
    li    x12, 0
    jal   x1, finish
    j     op_next

op_wr2:
    jal   x1, arg
    mv    x10, x15
    jal   x1, arg
    mv    x11, x15
    jal   x1, arg
    mv    x12, x15
    jal   x1, arg               // x15 = d2
    jal   x1, pre
    andi  x7, x14, F_OPT
    bnez  x7, 1f
    sw    x11, 0(x10)
    sw    x15, 0(x12)
    li    x12, 0
    j     2f
1:  sw    x11, 0(x10)
    sw    x15, 0(x12)
    lw    x12, 0(x12)
2:  jal   x1, finish
    j     op_next

op_poll:
    jal   x1, arg
    mv    x10, x15
    jal   x1, arg
    mv    x11, x15
    jal   x1, arg
    mv    x12, x15
    jal   x1, arg               // x15 = read bound
    jal   x1, pre
    li    x8, 0
    andi  x7, x14, F_OPT
    bnez  x7, 3f
1:  lw    x7, 0(x10)
    addi  x8, x8, 1
    and   x9, x7, x11
    beq   x9, x12, 5f           // done only on a known match
    bltu  x8, x15, 1b
    j     5f
3:  lw    x7, 0(x10)
    addi  x8, x8, 1
    and   x9, x7, x11
    bne   x9, x12, 5f           // done only on a known mismatch
    bltu  x8, x15, 3b
5:  mv    x12, x7
    mv    x15, x8
    jal   x1, finish
    mv    x12, x15
    jal   x1, put
    j     op_next

op_rdloop:
    jal   x1, arg
    mv    x10, x15
    jal   x1, arg
    mv    x11, x15              // count
    jal   x1, arg
    mv    x12, x15              // stride
    jal   x1, pre
    li    x15, 0                // reads that were not 0
    li    x8, 0                 // OR
    beqz  x11, 3f
1:  lw    x7, 0(x10)
    or    x8, x8, x7
    beqz  x7, 2f                // an unknown word counts as not 0
    addi  x15, x15, 1
2:  add   x10, x10, x12
    addi  x11, x11, -1
    bnez  x11, 1b
3:  mv    x12, x15
    mv    x15, x8
    jal   x1, finish
    mv    x12, x15
    jal   x1, put
    j     op_next

op_rdblk:
    jal   x1, arg
    mv    x10, x15
    jal   x1, arg
    mv    x11, x15              // stride
    srli  x15, x14, 16          // n
    beqz  x15, 2f
1:  jal   x1, pre
    lw    x12, 0(x10)
    jal   x1, finish
    add   x10, x10, x11
    addi  x15, x15, -1
    bnez  x15, 1b
2:  j     op_next

op_fill:
    jal   x1, arg
    mv    x10, x15
    jal   x1, arg
    mv    x11, x15
    srli  x15, x14, 16
    jal   x1, pre
    beqz  x15, 2f
1:  sw    x11, 0(x10)
    addi  x10, x10, 4
    addi  x15, x15, -1
    bnez  x15, 1b
2:  li    x12, 0
    jal   x1, finish
    j     op_next

op_wrblk:
    jal   x1, arg
    mv    x10, x15
    srli  x11, x14, 16
    slli  x7, x11, 2
    add   x7, x7, x3
    bgeu  x4, x7, 1f
    li    x9, ERR_TRUNC
    j     list_error
1:  jal   x1, pre
    beqz  x11, 3f
2:  lw    x7, 0(x3)
    addi  x3, x3, 4
    sw    x7, 0(x10)
    addi  x10, x10, 4
    addi  x11, x11, -1
    bnez  x11, 2b
3:  li    x12, 0
    jal   x1, finish
    j     op_next

op_copy:
    jal   x1, arg
    mv    x10, x15
    jal   x1, arg
    mv    x11, x15
    srli  x15, x14, 16
    jal   x1, pre
    beqz  x15, 2f
1:  lw    x7, 0(x10)
    sw    x7, 0(x11)
    addi  x10, x10, 4
    addi  x11, x11, 4
    addi  x15, x15, -1
    bnez  x15, 1b
2:  li    x12, 0
    jal   x1, finish
    j     op_next

op_jump:
    jal   x1, arg
    mv    x12, x15              // target, moved to x15 below
    jal   x1, arg
    mv    x10, x15
    jal   x1, arg
    mv    x11, x15
    mv    x15, x12
    jal   x1, pre
    sw    x3, W_CUR*4(x2)
    sw    x4, W_END*4(x2)
    sw    x5, W_SLOT*4(x2)
    sw    x13, W_PRE*4(x2)
    sw    x14, W_OPW*4(x2)
    li    x9, ST_JUMP
    jal   x1, set_state
    li    x12, 0
    li    x1, ENTRY_RESUME
    lw    x7, W_ARM*4(x2)
    maskirq 0, 7
    jalr  x0, 0(x15)

resume_impl:
    li    x7, -1
    maskirq 0, 7
    li    x2, SRAM_BASE
    li    x6, IRQ_STATUS_A
    lw    x3, W_CUR*4(x2)
    lw    x4, W_END*4(x2)
    lw    x5, W_SLOT*4(x2)
    lw    x13, W_PRE*4(x2)
    lw    x14, W_OPW*4(x2)
    li    x9, ST_RUN
    jal   x1, set_state
    jal   x1, finish
    j     op_next

op_exec:
    jal   x1, arg
    mv    x10, x15
    jal   x1, arg
    mv    x11, x15
    srli  x15, x14, 16
    li    x7, EXEC_COUNT
    bltu  x15, x7, 1f
    li    x9, ERR_EXEC
    j     list_error
1:  slli  x15, x15, 3
    li    x7, EXEC_BASE
    add   x15, x15, x7
    li    x12, 0
    jal   x1, pre
    jalr  x1, 0(x15)
    jal   x1, finish
    j     op_next

op_arm:
    jal   x1, arg
    andi  x7, x15, IRQ_LINES
    xori  x7, x7, -1
    sw    x7, W_ARM*4(x2)
    jal   x1, arg
    sw    x15, W_ACT*4(x2)
    j     op_next

op_cnt:
    srli  x7, x14, 16
    addi  x7, x7, -3
    li    x8, 3
    bltu  x7, x8, 1f
    li    x9, ERR_LINE
    j     list_error
1:  slli  x7, x7, 2
    add   x7, x7, x2
    lw    x12, W_CNT3*4(x7)
    jal   x1, put
    j     op_next

op_mark:
    jal   x1, arg
    mv    x12, x15
    jal   x1, put
    j     op_next

op_delay:
    jal   x1, arg
    beqz  x15, 2f
1:  rearm
    addi  x15, x15, -1
    bnez  x15, 1b
2:  j     op_next

op_sync:
    li    x9, ST_SYNC
    jal   x1, set_state
    jal   x1, mbox_get
    mv    x12, x10
    li    x9, ST_RUN
    jal   x1, set_state
    jal   x1, put
    j     op_next

op_reseth:
    jal   x1, arg
    sw    x0, W_CNT3*4(x2)
    sw    x0, W_CNT4*4(x2)
    sw    x0, W_CNT5*4(x2)
    sw    x15, W_HWORD*4(x2)
    sw    x15, W_SPIN*4(x2)
    j     op_next

    # Counting handler. q0 = return address, q1 = the lines being served.
irq_handler:
    setq  2, 1
    setq  3, 2
    li    x1, SRAM_BASE
    sw    x3,  (W_SAVE+0)*4(x1)
    sw    x4,  (W_SAVE+1)*4(x1)
    sw    x5,  (W_SAVE+2)*4(x1)
    sw    x6,  (W_SAVE+3)*4(x1)
    sw    x7,  (W_SAVE+4)*4(x1)
    sw    x8,  (W_SAVE+5)*4(x1)
    sw    x9,  (W_SAVE+6)*4(x1)
    sw    x10, (W_SAVE+7)*4(x1)
    sw    x11, (W_SAVE+8)*4(x1)
    sw    x12, (W_SAVE+9)*4(x1)
    sw    x13, (W_SAVE+10)*4(x1)
    sw    x14, (W_SAVE+11)*4(x1)
    sw    x15, (W_SAVE+12)*4(x1)
    mv    x2, x1
    getq  3, 1                  // x3 = served lines
    lw    x4, W_ACT*4(x2)

    andi  x5, x3, 0x08
    beqz  x5, 4f
    lw    x5, W_CNT3*4(x2)
    addi  x5, x5, 1
    sw    x5, W_CNT3*4(x2)
    andi  x5, x4, 0xFF
    li    x6, ACT_CLEAR
    bne   x5, x6, 1f
    li    x6, IRQ_STATUS_A
    lw    x7, 0(x6)
    lw    x8, IRQ_ENABLE_OFF(x6)
    and   x7, x7, x8
    sw    x7, 0(x6)
    j     4f
1:  li    x6, ACT_SPIN
    bne   x5, x6, 2f
    li    x6, IRQ_STATUS_A
    lw    x7, 0(x6)
    sw    x7, W_HWORD*4(x2)
    j     rom_spin
2:  li    x6, ACT_EXEC
    bne   x5, x6, 4f
    srli  x5, x4, 8
    andi  x5, x5, 0xFF
    li    x6, EXEC_COUNT
    bgeu  x5, x6, 4f
    slli  x5, x5, 3
    li    x6, EXEC_BASE
    add   x5, x5, x6
    li    x10, 0
    li    x11, 0
    jalr  x1, 0(x5)
    li    x2, SRAM_BASE
4:  andi  x5, x3, 0x10
    beqz  x5, 5f
    lw    x5, W_CNT4*4(x2)
    addi  x5, x5, 1
    sw    x5, W_CNT4*4(x2)
5:  andi  x5, x3, 0x20
    beqz  x5, 6f
    lw    x5, W_CNT5*4(x2)
    addi  x5, x5, 1
    sw    x5, W_CNT5*4(x2)
6:  li    x5, -1
    maskirq 0, 5                // every line masked until the next re-arm
    mv    x1, x2
    lw    x3,  (W_SAVE+0)*4(x1)
    lw    x4,  (W_SAVE+1)*4(x1)
    lw    x5,  (W_SAVE+2)*4(x1)
    lw    x6,  (W_SAVE+3)*4(x1)
    lw    x7,  (W_SAVE+4)*4(x1)
    lw    x8,  (W_SAVE+5)*4(x1)
    lw    x9,  (W_SAVE+6)*4(x1)
    lw    x10, (W_SAVE+7)*4(x1)
    lw    x11, (W_SAVE+8)*4(x1)
    lw    x12, (W_SAVE+9)*4(x1)
    lw    x13, (W_SAVE+10)*4(x1)
    lw    x14, (W_SAVE+11)*4(x1)
    lw    x15, (W_SAVE+12)*4(x1)
    getq  1, 2
    getq  2, 3
    retirq
