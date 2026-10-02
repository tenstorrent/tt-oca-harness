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
#     and require AXI_SLVERR with AXI_DECERR clear (key_manager.rdl: an
#     unmapped offset inside a window answers SLVERR)
#   lock the seed SRAM region, store, require the write dropped plus
#     SRAM_WRITE_LOCK_VIOLATION and IRQ_STATUS.SRAM_WRITE_LOCK_ERR, then W1C
#   seal a slot (one write; hardware raises lock_write with it), erase it, and
#     require it comes back RETIRED: lock_write held and lock_use gained
#   mark an unsealed slot with lock_write, erase it, and require it comes
#     back FREE with CTRL all clear -- the mark is what makes a no-op erase
#     fail rather than pass on the reset value
#
# Register addresses, array strides and word offsets come from the generated
# map, included below. Field masks come from km_fields.inc (lifted from
# km_csr.h / km_kpv.h / km_mailbox_km.h).
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

#include "key_manager_addr.h"
#include "km_fields.inc"

#define IRQ_AXI_SLVERR     KM_CSR__IRQ_STATUS_REG__AXI_SLVERR_bm
#define IRQ_AXI_DECERR     KM_CSR__IRQ_STATUS_REG__AXI_DECERR_bm
#define IRQ_AXI_ERR        (IRQ_AXI_SLVERR | IRQ_AXI_DECERR)
#define IRQ_SRAM_LOCK_ERR  KM_CSR__IRQ_STATUS_REG__SRAM_WRITE_LOCK_ERR_bm
#define IRQ_DRBG_ERR       KM_CSR__IRQ_STATUS_REG__DRBG_ERR_bm
#define IRQ_PARITY_TRIO    (KM_CSR__IRQ_STATUS_REG__ROM_PARITY_ERR_bm | \
                            KM_CSR__IRQ_STATUS_REG__SRAM_PARITY_ERR_bm | \
                            KM_CSR__IRQ_STATUS_REG__ROM_WRITE_ERR_bm)
#define CTRL_LOCK_WRITE    KM_KPV__CTRL_REG__LOCK_WRITE_bm
#define CTRL_LOCK_USE      KM_KPV__CTRL_REG__LOCK_USE_bm
#define CTRL_ERASE         KM_KPV__CTRL_REG__ERASE_bm
#define CTRL_SEAL          KM_KPV__CTRL_REG__SEAL_bm
#define CTRL_SEALED        (CTRL_SEAL | CTRL_LOCK_WRITE)
#define CTRL_RETIRED       (CTRL_LOCK_WRITE | CTRL_LOCK_USE)
#define CTRL_ALL           (CTRL_LOCK_WRITE | CTRL_LOCK_USE | CTRL_ERASE | CTRL_SEAL)
#define MBOX_INBOUND_EMPTY KM_MAILBOX_KM__STATUS_REG__INBOUND_EMPTY_bm

    // Mailbox register offsets, derived from the generated map rather than
    // typed: the images hold the block base in a register and index off it.
    .equ MBOX_WRITE_DATA,  (KEY_MANAGER_MAILBOX_KM_KM_WRITE_DATA_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ MBOX_WRITE_SEP,   (KEY_MANAGER_MAILBOX_KM_KM_WRITE_SEPARATOR_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ MBOX_READ_DATA,   (KEY_MANAGER_MAILBOX_KM_KM_READ_DATA_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ MBOX_STATUS,      (KEY_MANAGER_MAILBOX_KM_KM_STATUS_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)

    // KPV array geometry from the generated map. The slot index scales by a
    // shift, so each stride must be the power of two named here; a stride
    // that moves at the next RDL regeneration fails the build.
    .equ KEY_ENTRY_SHIFT,  6
    .equ CTRL_SHIFT,       2
    .if (1 << KEY_ENTRY_SHIFT) != KEY_MANAGER_KPV_KEY_ENTRY_STRIDE
    .error "KEY_ENTRY stride is not 1 << KEY_ENTRY_SHIFT"
    .endif
    .if (1 << CTRL_SHIFT) != (KEY_MANAGER_KPV_CTRL_BASE_ADDR(1) - KEY_MANAGER_KPV_CTRL_BASE_ADDR(0))
    .error "CTRL stride is not 1 << CTRL_SHIFT"
    .endif
    .equ CTRL_LAST_OFF,    (KEY_MANAGER_KPV_CTRL_BASE_ADDR((KEY_MANAGER_KPV_CTRL_NUM - 1)) - KEY_MANAGER_KPV_CTRL_BASE_ADDR(0))
    .equ KEY_WORD_LAST_OFF, (KEY_MANAGER_KPV_KEY_ENTRY_WORD_BASE_ADDR(0, (KEY_MANAGER_KPV_KEY_ENTRY_WORD_NUM - 1)) - KEY_MANAGER_KPV_KEY_ENTRY_BASE_ADDR(0))

    // KM SRAM base from the generated map. The 1 KB lock regions start here:
    // km_csr.rdl SRAM_LOCK (region 0 = 0x8000-0x83FF) and
    // hw/ip/key_manager/doc/architecture.adoc.
    .equ KM_SRAM_BASE, KEY_MANAGER_SRAM_BASE_ADDR

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
    li    x1, KEY_MANAGER_MAILBOX_KM_BASE_ADDR
    addi  x5, x0, 0             # flags

    # Wait for the host config word.
1:  lw    x2, MBOX_STATUS(x1)
    andi  x6, x2, MBOX_INBOUND_EMPTY
    bnez  x6, 1b
    lw    x2, MBOX_READ_DATA(x1)           # cfg
    andi  x3, x2, 0x3F          # slot
    srli  x4, x2, 8
    andi  x4, x4, 0x1F          # region

    # Store a known non-zero in KEY_ENTRY[slot] before any lock. CHK-LOCKUSE
    # later reads this address; a never-written slot already returns 0, so
    # the zero-data refusal would pass whether or not the lock forced it.
    li    x12, KEY_MANAGER_KPV_KEY_ENTRY_BASE_ADDR(0)
    slli  x13, x3, KEY_ENTRY_SHIFT  # slot * KEY_ENTRY stride
    add   x12, x12, x13
    lui   x13, 0xA11CE
    sw    x13, 0(x12)
    lw    x7, 0(x12)
    bne   x7, x13, slot_done

    # --- legal slots: 0, seed, 63 ---
    li    x8, KEY_MANAGER_KPV_CTRL_BASE_ADDR(0)
    addi  x6, x0, CTRL_LOCK_WRITE
    sw    x6, 0(x8)
    lw    x7, 0(x8)
    andi  x7, x7, CTRL_LOCK_WRITE
    beqz  x7, slot_done

    slli  x11, x3, CTRL_SHIFT
    add   x11, x8, x11          # CTRL[slot]
    sw    x6, 0(x11)
    lw    x7, 0(x11)
    andi  x7, x7, CTRL_LOCK_WRITE
    beqz  x7, slot_done

    addi  x11, x8, CTRL_LAST_OFF  # CTRL[63]
    sw    x6, 0(x11)
    lw    x7, 0(x11)
    andi  x7, x7, CTRL_LOCK_WRITE
    beqz  x7, slot_done
    ori   x5, x5, 0x1           # CHK-SLOT
slot_done:

    # --- key-data write to a write-locked slot must raise SLVERR ---
    # The extent check below proves SLVERR for an out-of-map ADDRESS, which is
    # the register-decode path. This is the lock path: a legal key-entry address
    # on a slot whose lock_write is set. IRQ_STATUS bits are sticky, so clear
    # and confirm clean first or an earlier fault would satisfy it.
    li    x9, KEY_MANAGER_KMCSR_IRQ_STATUS_BASE_ADDR
    addi  x11, x0, IRQ_AXI_SLVERR
    sw    x11, 0(x9)
    lw    x7, 0(x9)
    andi  x7, x7, IRQ_AXI_SLVERR
    bnez  x7, lockwr_done

    li    x12, KEY_MANAGER_KPV_KEY_ENTRY_BASE_ADDR(0)
    slli  x13, x3, KEY_ENTRY_SHIFT  # slot * KEY_ENTRY stride
    add   x12, x12, x13         # KEY_ENTRY[slot].word0
    lui   x13, 0xC0DE1
    sw    x13, 0(x12)           # refused: slot is write-locked
    addi  x14, x0, 32
6:  lw    x7, 0(x9)
    andi  x11, x7, IRQ_AXI_SLVERR
    bnez  x11, lockwr_ok
    addi  x14, x14, -1
    bnez  x14, 6b
    j     lockwr_done
lockwr_ok:
    ori   x5, x5, 0x200         # CHK-LOCKWR
    addi  x11, x0, IRQ_AXI_SLVERR
    sw    x11, 0(x9)            # W1C for the next check
lockwr_done:

    # --- key-data read of a lock_use slot returns SLVERR and zero data ---
    addi  x7, x0, CTRL_LOCK_USE
    slli  x11, x3, CTRL_SHIFT
    add   x11, x8, x11
    sw    x7, 0(x11)
    lw    x7, 0(x11)
    andi  x7, x7, CTRL_LOCK_USE
    beqz  x7, lockuse_done      # the lock did not take: prove nothing

    lw    x7, 0(x9)
    andi  x7, x7, IRQ_AXI_SLVERR
    bnez  x7, lockuse_done      # must start clean
    lw    x13, 0(x12)           # refused read; data must be forced to zero
    addi  x14, x0, 32
7:  lw    x7, 0(x9)
    andi  x11, x7, IRQ_AXI_SLVERR
    bnez  x11, lockuse_err
    addi  x14, x14, -1
    bnez  x14, 7b
    j     lockuse_done
lockuse_err:
    bnez  x13, lockuse_done     # SLVERR alone is not enough: data must be 0
    ori   x5, x5, 0x400         # CHK-LOCKUSE
    addi  x11, x0, IRQ_AXI_SLVERR
    sw    x11, 0(x9)
lockuse_done:

    # --- past last KPV register, still in the 8 KB window ---
    # key_manager.rdl (memory-map summary): an unmapped offset inside a window
    # answers SLVERR. IRQ_STATUS is sticky on the B-handshake pulse, so poll a
    # bounded number of times.
    #
    # Clear the two error bits and require them to read back 0 FIRST. They are
    # sticky, so without this the check would also be satisfied by an earlier
    # fault anywhere on the KM CPU bus, and would not be about this store.
    li    x9, KEY_MANAGER_KMCSR_IRQ_STATUS_BASE_ADDR
    addi  x11, x0, IRQ_AXI_ERR
    sw    x11, 0(x9)
    lw    x7, 0(x9)
    andi  x7, x7, IRQ_AXI_ERR
    bnez  x7, extent_done       # not clean to begin with: prove nothing
    li    x6, KEY_MANAGER_KPV_BASE_ADDR + KEY_MANAGER_KPV_SIZE
    sw    x0, 0(x6)
    addi  x12, x0, 32
3:  lw    x7, 0(x9)
    andi  x11, x7, IRQ_AXI_ERR
    bnez  x11, extent_seen
    addi  x12, x12, -1
    bnez  x12, 3b
    j     extent_done
extent_seen:
    # SLVERR alone: a DECERR bit, with or without SLVERR, fails the check.
    addi  x12, x0, IRQ_AXI_SLVERR
    bne   x11, x12, extent_clear
    ori   x5, x5, 0x2           # CHK-EXTENT
extent_clear:
    addi  x11, x0, IRQ_AXI_ERR
    sw    x11, 0(x9)            # W1C those bits so later IRQ checks are clean
extent_done:

    # --- SRAM write-lock ---
    li    x10, KM_SRAM_BASE
    slli  x6, x4, 10            # region * 0x400
    add   x6, x10, x6
    addi  x6, x6, 0x100         # test address
    lui   x7, 0x11111
    addi  x7, x7, 0x111         # 0x11111111
    sw    x7, 0(x6)
    lw    x11, 0(x6)
    bne   x11, x7, lock_done    # preload must land (region unlocked)

    li    x12, KEY_MANAGER_KMCSR_SRAM_LOCK_BASE_ADDR
    addi  x11, x0, 1
    sll   x11, x11, x4
    sw    x11, 0(x12)

    lui   x13, 0x22222
    addi  x13, x13, 0x222       # 0x22222222
    sw    x13, 0(x6)
    lw    x13, 0(x6)
    bne   x13, x7, lock_done    # write must be dropped
    ori   x5, x5, 0x4           # CHK-DROP

    li    x14, KEY_MANAGER_KMCSR_SRAM_WRITE_LOCK_VIOLATION_BASE_ADDR
    lw    x13, 0(x14)
    addi  x15, x0, 1
    sll   x15, x15, x4
    bne   x13, x15, lock_done   # exactly this region, not merely including it
    ori   x5, x5, 0x8           # CHK-VIOL

    lw    x13, 0(x9)            # IRQ_STATUS
    andi  x15, x13, IRQ_SRAM_LOCK_ERR
    beqz  x15, lock_done
    andi  x15, x13, IRQ_PARITY_TRIO
    bnez  x15, lock_done
    ori   x5, x5, 0x10          # CHK-IRQ

    addi  x13, x0, -1
    sw    x13, 0(x14)           # W1C all violation bits
    addi  x13, x0, IRQ_SRAM_LOCK_ERR
    sw    x13, 0(x9)            # W1C SRAM_WRITE_LOCK_ERR
    lw    x13, 0(x14)
    bnez  x13, lock_done
    lw    x13, 0(x9)
    andi  x13, x13, IRQ_SRAM_LOCK_ERR
    bnez  x13, lock_done
    ori   x5, x5, 0x20          # CHK-W1C
lock_done:

    # --- seal, then erase: the slot must retire, not free ---
    # x2 still holds the host config word.
    li    x8, KEY_MANAGER_KPV_CTRL_BASE_ADDR(0)
    srli  x6, x2, 16
    andi  x6, x6, 0x3F          # seal slot
    slli  x6, x6, CTRL_SHIFT
    add   x6, x8, x6            # CTRL[seal_slot]

    addi  x7, x0, CTRL_SEAL
    sw    x7, 0(x6)
    lw    x7, 0(x6)
    andi  x11, x7, CTRL_ALL
    addi  x12, x0, CTRL_SEALED
    bne   x11, x12, seal_done   # one write seals AND write-locks, lock_use clear
    ori   x5, x5, 0x40          # CHK-SEAL

    addi  x7, x0, CTRL_ERASE
    sw    x7, 0(x6)
    addi  x12, x0, 256          # bounded: a stuck erase must not hang the image
4:  lw    x7, 0(x6)
    andi  x11, x7, CTRL_ERASE
    beqz  x11, seal_erased
    addi  x12, x12, -1
    bnez  x12, 4b
    j     seal_done
seal_erased:
    lw    x7, 0(x6)
    andi  x11, x7, CTRL_RETIRED
    addi  x12, x0, CTRL_RETIRED
    bne   x11, x12, seal_done   # retired: write stays locked, use becomes locked
    ori   x5, x5, 0x80          # CHK-RETIRE

    # Retirement is stated to hold until warm reset. Erase the retired slot
    # again: it must come back retired, not freed. Without this the retire is
    # only shown as a one-shot transition, not as a sticky property.
    addi  x7, x0, CTRL_ERASE
    sw    x7, 0(x6)
    addi  x12, x0, 256
8:  lw    x7, 0(x6)
    andi  x11, x7, CTRL_ERASE
    beqz  x11, retire_stuck
    addi  x12, x12, -1
    bnez  x12, 8b
    j     seal_done
retire_stuck:
    lw    x7, 0(x6)
    andi  x11, x7, CTRL_RETIRED
    addi  x12, x0, CTRL_RETIRED
    bne   x11, x12, seal_done   # a second erase must not release the slot
    addi  x11, x0, 1
    slli  x11, x11, 12
    or    x5, x5, x11           # CHK-RETSTICK
seal_done:

    # --- erase an unsealed slot: it must come back reusable ---
    srli  x6, x2, 24
    andi  x6, x6, 0x3F          # free slot
    slli  x6, x6, CTRL_SHIFT
    add   x6, x8, x6            # CTRL[free_slot]

    # Preload key data BEFORE marking the slot, while writes are still allowed.
    # CHK-FREE below grades CTRL bookkeeping only; this is what shows the erase
    # actually overwrites the stored words rather than just clearing flags.
    li    x13, KEY_MANAGER_KPV_KEY_ENTRY_BASE_ADDR(0)
    srli  x14, x2, 24
    andi  x14, x14, 0x3F
    slli  x14, x14, KEY_ENTRY_SHIFT
    add   x13, x13, x14         # KEY_ENTRY[free_slot]
    lui   x14, 0x5A5A5
    addi  x14, x14, 0x5A5
    sw    x14, 0(x13)           # word 0
    sw    x14, KEY_WORD_LAST_OFF(x13)  # word 15

    # Mark the slot first. Its reset value is already 0, so erasing an
    # untouched slot and finding CTRL clear would be satisfied by an erase that
    # did nothing at all. Setting lock_write gives the erase something it has
    # to clear.
    addi  x7, x0, CTRL_LOCK_WRITE
    sw    x7, 0(x6)
    lw    x7, 0(x6)
    andi  x7, x7, CTRL_LOCK_WRITE
    beqz  x7, free_done         # the mark did not take: prove nothing

    addi  x7, x0, CTRL_ERASE
    sw    x7, 0(x6)
    addi  x12, x0, 256
5:  lw    x7, 0(x6)
    andi  x11, x7, CTRL_ERASE
    beqz  x11, free_erased
    addi  x12, x12, -1
    bnez  x12, 5b
    j     free_done
free_erased:
    lw    x7, 0(x6)
    andi  x11, x7, CTRL_ALL
    bnez  x11, free_done        # unsealed erase clears CTRL entirely
    ori   x5, x5, 0x100         # CHK-FREE

    # The erase fills through an LFSR that advances per word, so both preloaded
    # words must have changed AND must now differ from each other. A stuck-at
    # fill, or a fill that never ran, fails.
    lw    x11, 0(x13)
    lw    x12, KEY_WORD_LAST_OFF(x13)
    beq   x11, x14, free_done   # word 0 unchanged
    beq   x12, x14, free_done   # word 15 unchanged
    beq   x11, x12, free_done   # both words identical: not an advancing fill
    addi  x11, x0, 1
    slli  x11, x11, 11
    or    x5, x5, x11           # CHK-ERASEDATA
free_done:

    # --- IRQ_SET drives IRQ_STATUS, and IRQ_ENABLE does not gate the status ---
    # IRQ_SET is the architected software-inject path: each field pulses the
    # matching IRQ_STATUS bit so an ISR can be exercised without the hardware
    # condition. DRBG_ERR is used here because it is the one status bit whose
    # own fault source has no frontdoor from the SEP side. This grades the
    # set/W1C plumbing and the aggregation ONLY -- it does not prove a DRBG
    # fault is detected, and must not be recorded as coverage of that source.
    addi  x11, x0, IRQ_DRBG_ERR
    sw    x11, 0(x9)            # W1C first: the bit is sticky
    lw    x7, 0(x9)
    andi  x7, x7, IRQ_DRBG_ERR
    bnez  x7, irqset_done       # must start clean

    li    x12, KEY_MANAGER_KMCSR_IRQ_SET_BASE_ADDR
    addi  x11, x0, IRQ_DRBG_ERR
    sw    x11, 0(x12)           # software-inject DRBG_ERR
    lw    x7, 0(x9)
    andi  x7, x7, IRQ_DRBG_ERR
    beqz  x7, irqset_done

    addi  x11, x0, IRQ_DRBG_ERR
    sw    x11, 0(x9)            # W1C it back down
    lw    x7, 0(x9)
    andi  x7, x7, IRQ_DRBG_ERR
    bnez  x7, irqset_done
    addi  x11, x0, 1
    slli  x11, x11, 13
    or    x5, x5, x11           # CHK-IRQSET
irqset_done:

    # Fold the whole received config word into eight bits and echo it at
    # [23:16]. Echoing only the slot would leave the region and the seal/free
    # pair unproven: a ROM that ignored them would produce an identical result
    # word. The fold covers every field the host packed.
    srli  x6, x2, 8
    xor   x6, x6, x2
    srli  x7, x2, 16
    xor   x6, x6, x7
    srli  x7, x2, 24
    xor   x6, x6, x7
    andi  x6, x6, 0xFF
    slli  x6, x6, 16
    or    x5, x5, x6
    lui   x6, 0xA1000           # magic 0xA1 in [31:24]
    or    x5, x5, x6
    sw    x5, 0(x10)            # SRAM word0
2:  j     2b
