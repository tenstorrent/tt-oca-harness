# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM ROM for sep_km_key_policy_vault_test. Not rom_main: slot extent, the
# SRAM write-lock and the KPV seal all live on the KM CPU bus, so this image
# is the vehicle. The mailbox command set cannot reach the seal: no command
# seals a slot, so an erase driven over the mailbox always frees.
#
# PicoRV32 is RV32E (x0-x15 only). Do not use x16+.
#
# Host writes one mailbox word before/while this image waits:
#   [5:0]   legal KPV slot (0..63)
#   [12:8]  SRAM lock region (1..30, never 0 or 15)
#   [21:16] slot to seal then erase, distinct from the others
#   [29:24] slot to erase unsealed, distinct from the others
#
# Then:
#   write LOCK_WRITE on slot 0, the seed slot, and slot 63; read back bit 0
#   store to 0x13108 (KPV base 0x12000 + KM_KPV_SIZE 0x1108, so the first
#     byte past the register map and still inside the 8 KB KPV decode window)
#     and require AXI_SLVERR (or DECERR)
#   lock the seed SRAM region, store, require the write dropped plus
#     SRAM_WRITE_LOCK_VIOLATION and IRQ_STATUS.SRAM_WRITE_LOCK_ERR, then W1C
#   seal a slot (one write; hardware raises lock_write with it), erase it, and
#     require it comes back RETIRED: lock_write held and lock_use gained
#   mark an unsealed slot with lock_write, erase it, and require it comes
#     back FREE with CTRL all clear -- the mark is what makes a no-op erase
#     fail rather than pass on the reset value
#
# CTRL[slot] bits: lock_write[0], lock_use[1], erase[2], seal[3]. Erase is
# never gated by a lock or by the seal; the slot's seal state when the erase
# completes is what decides retired versus reusable.
#
# Result at KM SRAM word0 (0x8000), which the host probes:
#   0xA11A0000 | slot[15:10] | slot_ok | extent | dropped | viol | irq | w1c
#              | seal | retire | free
#
# Build (output committed as ../km_rom_vault.parhex):
#   make -C hw/sys/sep/dv/cocotb/tests/km_fw ../km_rom_vault.parhex

    .section .text
    .globl _start
_start:
    # x1  mbox
    # x2  cfg / scratch
    # x3  slot
    # x4  region
    # x5  result flags
    # x8  CTRL[0] / scratch
    # x9  IRQ_STATUS
    # x10 SRAM base
    # x6,x7,x11-x15 scratch
    lui   x1, 0x10              # mbox 0x00010000
    addi  x5, x0, 0             # flags

    # Wait for the host config word.
1:  lw    x2, 0xC(x1)
    andi  x6, x2, 0x1           # inbound_empty
    bnez  x6, 1b
    lw    x2, 0x8(x1)           # cfg
    andi  x3, x2, 0x3F          # slot
    srli  x4, x2, 8
    andi  x4, x4, 0x1F          # region

    # --- legal slots: 0, seed, 63 ---
    lui   x8, 0x13              # CTRL[0] = 0x00013000
    addi  x6, x0, 1
    sw    x6, 0(x8)
    lw    x7, 0(x8)
    andi  x7, x7, 1
    beqz  x7, slot_done

    slli  x11, x3, 2
    add   x11, x8, x11          # CTRL[slot]
    sw    x6, 0(x11)
    lw    x7, 0(x11)
    andi  x7, x7, 1
    beqz  x7, slot_done

    addi  x11, x8, 0xFC         # CTRL[63] = 0x000130FC
    sw    x6, 0(x11)
    lw    x7, 0(x11)
    andi  x7, x7, 1
    beqz  x7, slot_done
    ori   x5, x5, 0x1           # CHK-SLOT
slot_done:

    # --- past last KPV register, still in the 8 KB window ---
    # PeakRDL --err-if-bad-addr answers SLVERR; IRQ_STATUS is sticky on the
    # B-handshake pulse, so poll a bounded number of times.
    #
    # Clear the two error bits and require them to read back 0 FIRST. They are
    # sticky, so without this the check would also be satisfied by an earlier
    # fault anywhere on the KM CPU bus, and would not be about this store.
    lui   x9, 0x14
    addi  x9, x9, 0xC           # IRQ_STATUS 0x0001400C
    addi  x11, x0, 0x30         # AXI_SLVERR | AXI_DECERR
    sw    x11, 0(x9)
    lw    x7, 0(x9)
    andi  x7, x7, 0x30
    bnez  x7, extent_done       # not clean to begin with: prove nothing
    lui   x6, 0x13
    addi  x6, x6, 0x108         # 0x00013108
    sw    x0, 0(x6)
    addi  x12, x0, 32
3:  lw    x7, 0(x9)
    andi  x11, x7, 0x30         # AXI_SLVERR | AXI_DECERR
    bnez  x11, extent_ok
    addi  x12, x12, -1
    bnez  x12, 3b
    j     extent_done
extent_ok:
    ori   x5, x5, 0x2           # CHK-EXTENT
    addi  x11, x0, 0x30
    sw    x11, 0(x9)            # W1C those bits so later IRQ checks are clean
extent_done:

    # --- SRAM write-lock ---
    lui   x10, 0x8              # SRAM 0x00008000
    slli  x6, x4, 10            # region * 0x400
    add   x6, x10, x6
    addi  x6, x6, 0x100         # test address
    lui   x7, 0x11111
    addi  x7, x7, 0x111         # 0x11111111
    sw    x7, 0(x6)
    lw    x11, 0(x6)
    bne   x11, x7, lock_done    # preload must land (region unlocked)

    lui   x12, 0x14
    addi  x12, x12, 0x1C        # SRAM_LOCK 0x0001401C
    addi  x11, x0, 1
    sll   x11, x11, x4
    sw    x11, 0(x12)

    lui   x13, 0x22222
    addi  x13, x13, 0x222       # 0x22222222
    sw    x13, 0(x6)
    lw    x13, 0(x6)
    bne   x13, x7, lock_done    # write must be dropped
    ori   x5, x5, 0x4           # CHK-DROP

    lui   x14, 0x14
    addi  x14, x14, 0x24        # SRAM_WRITE_LOCK_VIOLATION 0x00014024
    lw    x13, 0(x14)
    addi  x15, x0, 1
    sll   x15, x15, x4
    and   x13, x13, x15
    beqz  x13, lock_done
    ori   x5, x5, 0x8           # CHK-VIOL

    lw    x13, 0(x9)            # IRQ_STATUS
    andi  x13, x13, 0x8         # SRAM_WRITE_LOCK_ERR
    beqz  x13, lock_done
    ori   x5, x5, 0x10          # CHK-IRQ

    addi  x13, x0, -1
    sw    x13, 0(x14)           # W1C all violation bits
    addi  x13, x0, 0x8
    sw    x13, 0(x9)            # W1C SRAM_WRITE_LOCK_ERR
    lw    x13, 0(x14)
    bnez  x13, lock_done
    lw    x13, 0(x9)
    andi  x13, x13, 0x8
    bnez  x13, lock_done
    ori   x5, x5, 0x20          # CHK-W1C
lock_done:

    # --- seal, then erase: the slot must retire, not free ---
    # x2 still holds the host config word.
    lui   x8, 0x13              # CTRL[0] = 0x00013000
    srli  x6, x2, 16
    andi  x6, x6, 0x3F          # seal slot
    slli  x6, x6, 2
    add   x6, x8, x6            # CTRL[seal_slot]

    addi  x7, x0, 0x8           # SEAL
    sw    x7, 0(x6)
    lw    x7, 0(x6)
    andi  x11, x7, 0x9          # seal | lock_write
    addi  x12, x0, 0x9
    bne   x11, x12, seal_done   # one write must seal AND write-lock
    ori   x5, x5, 0x40          # CHK-SEAL

    addi  x7, x0, 0x4           # ERASE
    sw    x7, 0(x6)
    addi  x12, x0, 256          # bounded: a stuck erase must not hang the image
4:  lw    x7, 0(x6)
    andi  x11, x7, 0x4
    beqz  x11, seal_erased
    addi  x12, x12, -1
    bnez  x12, 4b
    j     seal_done
seal_erased:
    lw    x7, 0(x6)
    andi  x11, x7, 0x3          # lock_write | lock_use
    addi  x12, x0, 0x3
    bne   x11, x12, seal_done   # retired: write stays locked, use becomes locked
    ori   x5, x5, 0x80          # CHK-RETIRE
seal_done:

    # --- erase an unsealed slot: it must come back reusable ---
    srli  x6, x2, 24
    andi  x6, x6, 0x3F          # free slot
    slli  x6, x6, 2
    add   x6, x8, x6            # CTRL[free_slot]

    # Mark the slot first. Its reset value is already 0, so erasing an
    # untouched slot and finding CTRL clear would be satisfied by an erase that
    # did nothing at all. Setting lock_write gives the erase something it has
    # to clear.
    addi  x7, x0, 0x1           # LOCK_WRITE
    sw    x7, 0(x6)
    lw    x7, 0(x6)
    andi  x7, x7, 0x1
    beqz  x7, free_done         # the mark did not take: prove nothing

    addi  x7, x0, 0x4           # ERASE
    sw    x7, 0(x6)
    addi  x12, x0, 256
5:  lw    x7, 0(x6)
    andi  x11, x7, 0x4
    beqz  x11, free_erased
    addi  x12, x12, -1
    bnez  x12, 5b
    j     free_done
free_erased:
    lw    x7, 0(x6)
    andi  x11, x7, 0xF
    bnez  x11, free_done        # unsealed erase clears CTRL entirely
    ori   x5, x5, 0x100         # CHK-FREE
free_done:

    # Echo the slot the host asked for into bits [15:10]. Without it the result
    # word is the same constant for every seed, so a config word that never
    # arrived could not be told from one that did.
    slli  x7, x3, 10
    or    x5, x5, x7
    lui   x6, 0xA11A0           # 0xA11A0000
    or    x5, x5, x6
    sw    x5, 0(x10)            # SRAM word0
2:  j     2b
