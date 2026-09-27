# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM ROM for sep_km_kpv_scrambler_test. Not rom_main: the key/policy vault is
# on the KM CPU bus, and rom_main programs the scrambler key, enables it and
# takes the sticky lock during boot, so by the time the host could act the
# enable toggle this image needs is already gone.
#
# PicoRV32 is RV32E (x0-x15 only). Do not use x16+.
#
# This image reports raw observations. It decides nothing: the counting, the
# index comparison, the keying comparison and the round-trip verdict all live
# in the host test.
#
# Every register address comes from the generated map, included below, so a
# moved register is a build error rather than a stale constant. Field bit
# positions are still literal -- the address header does not carry them.
# KPV_SCRAMBLER_CTRL: ENABLE bit 0, LOCK bit 1.
#
# Request, three words over the KM mailbox:
#   word 0  first scrambler key
#   word 1  second scrambler key, for the keying comparison
#   word 2  three 10-bit logical key-entry indices, packed [9:0] [19:10] [29:20]
#
# The plaintext written at logical index L is (L<<20) ^ (L<<8) ^ 0xA5C3F00D --
# shifts and one XOR, so it needs no multiplier, differs per index, and has
# mixed nibbles so the nibble-wise substitution has something to change. The
# constant occupies the low nibbles that neither shift can reach, so the
# plaintext is never zero and the scan's non-zero test stays meaningful.
#
# Both passes zero the whole file with the scrambler OFF first. With the
# scrambler off the vault addresses the register file logically and passes
# data through, so that is both a legitimate way to reach a known starting
# state without a wipe, and a legitimate frontdoor view of what was stored.
#
# Response, in order:
#   pass A: the number of non-zero words, then that many {index, value} pairs
#   pass B: one {index, value} pair for the first logical index under the
#           second key
#   the round-trip word, the key register read back while still UNLOCKED, the
#   same register read after the sticky lock, the post-lock round-trip word,
#   then a round-trip taken AFTER attempting to rewrite both the key and the
#   enable, and finally KPV_SCRAMBLER_CTRL itself
#
# That is 15 words on the healthy path (1 + 2*3 + 2 + 6) into a 16-deep
# outbound FIFO, and this image does not check for space before writing. The
# margin only holds while the count is 3, so the host raises on a wrong count
# before it drains the pair list -- see the collector in
# cocotb/seq_lib/sep_km_kpv_scrambler_seq.py.
#
# The unlocked readback is the control for the documented lock: without it a
# write-only register would make a later refused write look like a lock.
# The post-lock key-register data value is not claimed.
#
# Build (output committed as ../km_rom_kpv_scrambler.parhex):
#   make -C hw/sys/sep/dv/cocotb/tests/km_fw ../km_rom_kpv_scrambler.parhex

#include "key_manager_addr.h"

    // Mailbox register offsets, derived from the generated map rather than
    // typed: the images hold the block base in a register and index off it.
    .equ MBOX_WRITE_DATA,  (KEY_MANAGER_MAILBOX_KM_KM_WRITE_DATA_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ MBOX_WRITE_SEP,   (KEY_MANAGER_MAILBOX_KM_KM_WRITE_SEPARATOR_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ MBOX_READ_DATA,   (KEY_MANAGER_MAILBOX_KM_KM_READ_DATA_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ MBOX_STATUS,      (KEY_MANAGER_MAILBOX_KM_KM_STATUS_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)

    .equ N_WORDS, 1024

    .section .text
    .globl _start
_start:
    # x1  mailbox base
    # x2  key-entry base
    # x3  loop index
    # x4,x5,x6,x7  scratch
    # x8  scrambler key A, later the non-zero count
    # x9  packed indices
    # x11 first logical index, kept for both round-trip reads
    # x12 scrambler key B
    li    x1, KEY_MANAGER_MAILBOX_KM_BASE_ADDR
    li    x2, KEY_MANAGER_KPV_KEY_ENTRY_BASE_ADDR(0)

    # --- host config: key A, key B, packed indices ---
1:  lw    x4, MBOX_STATUS(x1)
    andi  x5, x4, 0x1           # inbound_empty
    bnez  x5, 1b
    lw    x8, MBOX_READ_DATA(x1)
2:  lw    x4, MBOX_STATUS(x1)
    andi  x5, x4, 0x1
    bnez  x5, 2b
    lw    x12, MBOX_READ_DATA(x1)
3:  lw    x4, MBOX_STATUS(x1)
    andi  x5, x4, 0x1
    bnez  x5, 3b
    lw    x9, MBOX_READ_DATA(x1)

    andi  x11, x9, 0x3FF        # first logical index

    # ================= pass A: key A, three indices =================
    li    x5, KEY_MANAGER_KPV_KPV_SCRAMBLER_CTRL_BASE_ADDR
    sw    x0, 0(x5)             # ENABLE = 0 for the zero fill
    addi  x3, x0, 0
    addi  x6, x0, N_WORDS
zero_a:
    slli  x4, x3, 2
    add   x4, x2, x4
    sw    x0, 0(x4)
    addi  x3, x3, 1
    blt   x3, x6, zero_a

    li    x5, KEY_MANAGER_KPV_KPV_SCRAMBLER_KEY_BASE_ADDR
    sw    x8, 0(x5)             # KPV_SCRAMBLER_KEY = key A
    addi  x4, x0, 1
    sw    x4, 0x4(x5)           # ENABLE = 1

    addi  x3, x0, 0
write_a:
    slli  x4, x3, 3             # 8*i
    slli  x5, x3, 1             # 2*i
    add   x4, x4, x5            # 10*i: the shift of the i-th field
    srl   x5, x9, x4
    andi  x5, x5, 0x3FF         # logical index L
    slli  x6, x5, 20
    slli  x7, x5, 8
    xor   x6, x6, x7
    lui   x7, 0xA5C3F
    addi  x7, x7, 0x00D
    xor   x6, x6, x7            # plaintext
    slli  x7, x5, 2
    add   x7, x2, x7
    sw    x6, 0(x7)
    addi  x3, x3, 1
    addi  x4, x0, 3
    blt   x3, x4, write_a

    li    x5, KEY_MANAGER_KPV_KPV_SCRAMBLER_CTRL_BASE_ADDR
    sw    x0, 0(x5)             # ENABLE = 0 to see the raw file

    addi  x3, x0, 0
    addi  x8, x0, 0             # count; key A is no longer needed
    addi  x6, x0, N_WORDS
count_a:
    slli  x4, x3, 2
    add   x4, x2, x4
    lw    x7, 0(x4)
    beqz  x7, count_a_next
    addi  x8, x8, 1
count_a_next:
    addi  x3, x3, 1
    blt   x3, x6, count_a

    addi  x4, x0, 1
    sw    x4, MBOX_WRITE_SEP(x1)
    sw    x8, MBOX_WRITE_DATA(x1)           # count

    addi  x3, x0, 0
    addi  x6, x0, N_WORDS
emit_a:
    slli  x4, x3, 2
    add   x4, x2, x4
    lw    x7, 0(x4)
    beqz  x7, emit_a_next
    addi  x5, x0, 1
    sw    x5, MBOX_WRITE_SEP(x1)
    sw    x3, MBOX_WRITE_DATA(x1)           # physical index
    addi  x5, x0, 1
    sw    x5, MBOX_WRITE_SEP(x1)
    sw    x7, MBOX_WRITE_DATA(x1)           # stored word
emit_a_next:
    addi  x3, x3, 1
    blt   x3, x6, emit_a

    # ================= pass B: key B, first index only =================
    addi  x3, x0, 0
    addi  x6, x0, N_WORDS
zero_b:
    slli  x4, x3, 2
    add   x4, x2, x4
    sw    x0, 0(x4)
    addi  x3, x3, 1
    blt   x3, x6, zero_b

    li    x5, KEY_MANAGER_KPV_KPV_SCRAMBLER_KEY_BASE_ADDR
    sw    x12, 0(x5)            # KPV_SCRAMBLER_KEY = key B (still unlocked)
    addi  x4, x0, 1
    sw    x4, 0x4(x5)           # ENABLE = 1

    slli  x6, x11, 20
    slli  x7, x11, 8
    xor   x6, x6, x7
    lui   x7, 0xA5C3F
    addi  x7, x7, 0x00D
    xor   x6, x6, x7            # same plaintext as pass A for this index
    slli  x7, x11, 2
    add   x7, x2, x7
    sw    x6, 0(x7)

    li    x5, KEY_MANAGER_KPV_KPV_SCRAMBLER_CTRL_BASE_ADDR
    sw    x0, 0(x5)             # ENABLE = 0

    addi  x3, x0, 0
    addi  x6, x0, N_WORDS
find_b:
    slli  x4, x3, 2
    add   x4, x2, x4
    lw    x7, 0(x4)
    bnez  x7, found_b
    addi  x3, x3, 1
    blt   x3, x6, find_b
    addi  x3, x0, -1            # nothing stored; the host fails on this
    addi  x7, x0, 0
found_b:
    addi  x5, x0, 1
    sw    x5, MBOX_WRITE_SEP(x1)
    sw    x3, MBOX_WRITE_DATA(x1)           # physical index under key B
    addi  x5, x0, 1
    sw    x5, MBOX_WRITE_SEP(x1)
    sw    x7, MBOX_WRITE_DATA(x1)           # stored word under key B

    # ================= round trip, then the sticky lock =================
    li    x5, KEY_MANAGER_KPV_KPV_SCRAMBLER_CTRL_BASE_ADDR
    addi  x4, x0, 1
    sw    x4, 0(x5)             # ENABLE = 1

    slli  x4, x11, 2
    add   x4, x2, x4
    lw    x7, 0(x4)
    addi  x5, x0, 1
    sw    x5, MBOX_WRITE_SEP(x1)
    sw    x7, MBOX_WRITE_DATA(x1)           # round-trip word

    # Read the key register while it is still unlocked. This is the control for
    # the locked readback below.
    li    x5, KEY_MANAGER_KPV_KPV_SCRAMBLER_KEY_BASE_ADDR
    lw    x7, 0(x5)
    addi  x5, x0, 1
    sw    x5, MBOX_WRITE_SEP(x1)
    sw    x7, MBOX_WRITE_DATA(x1)           # key register, unlocked

    li    x5, KEY_MANAGER_KPV_KPV_SCRAMBLER_CTRL_BASE_ADDR
    addi  x4, x0, 3             # ENABLE | LOCK, taken last because it sticks
    sw    x4, 0(x5)

    li    x5, KEY_MANAGER_KPV_KPV_SCRAMBLER_KEY_BASE_ADDR
    lw    x7, 0(x5)             # key register readback after the lock
    addi  x5, x0, 1
    sw    x5, MBOX_WRITE_SEP(x1)
    sw    x7, MBOX_WRITE_DATA(x1)

    slli  x4, x11, 2
    add   x4, x2, x4
    lw    x7, 0(x4)
    addi  x5, x0, 1
    sw    x5, MBOX_WRITE_SEP(x1)
    sw    x7, MBOX_WRITE_DATA(x1)           # post-lock round-trip word

    # The lock's DOCUMENTED contract is that the key and the enable can no
    # longer be modified. Try both. A third key is derived from key B by
    # inversion so it needs no extra config word, and it is distinct from key B
    # because no 32-bit value equals its own complement.
    li    x5, KEY_MANAGER_KPV_KPV_SCRAMBLER_KEY_BASE_ADDR
    xori  x4, x12, -1
    sw    x4, 0(x5)             # refused: key is write-locked
    li    x5, KEY_MANAGER_KPV_KPV_SCRAMBLER_CTRL_BASE_ADDR
    sw    x0, 0(x5)             # refused: enable is write-locked

    slli  x4, x11, 2
    add   x4, x2, x4
    lw    x7, 0(x4)
    addi  x5, x0, 1
    sw    x5, MBOX_WRITE_SEP(x1)
    sw    x7, MBOX_WRITE_DATA(x1)           # round-trip after both refused writes

    li    x5, KEY_MANAGER_KPV_KPV_SCRAMBLER_CTRL_BASE_ADDR
    lw    x7, 0(x5)
    addi  x5, x0, 1
    sw    x5, MBOX_WRITE_SEP(x1)
    sw    x7, MBOX_WRITE_DATA(x1)           # KPV_SCRAMBLER_CTRL after the refused write

halt:
    j     halt
