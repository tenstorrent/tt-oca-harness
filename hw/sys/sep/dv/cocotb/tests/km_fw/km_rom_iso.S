# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM ROM for sep_km_isolate_termination_test. Not rom_main: the contract is
# what a KEY MANAGER master transaction receives when its own AXI-Lite path to
# a destination engine is isolated, and only code running on the KM CPU can
# issue that transaction. Every other isolation test in this package drives the
# SEP host port, which reaches the host_* paths and never the km_* ones.
#
# PicoRV32 is RV32E (x0-x15 only). Do not use x16+.
#
# The path under test is km_hmac: the KM master port to the HMAC wrapper key
# aperture. Three legs on the SAME address, each preceded by a W1C of the two
# AXI error bits and a readback requiring them clear, so the bit a leg reports
# belongs to that leg's access and not to an earlier fault anywhere on the KM
# CPU bus:
#
#   A  path live       store completes with neither error bit set
#   B  path isolated   the same store raises AXI_SLVERR or AXI_DECERR
#   C  path reopened   the same store is clean again
#
# Legs A and C cannot fail on their own -- no error is also what a dead poll
# loop reports. They are here as the controls that make leg B mean something:
# the same instruction at the same address, discriminated only by whether the
# host is holding HMAC in reset. B without A and C would be satisfied by an
# address that always errors.
#
# Host handshake. The host must park HMAC between A and B and release it
# between B and C, so this image publishes a phase marker in KM SRAM word0
# (the km_sram_word0_o probe) and then blocks on an inbound mailbox word:
#
#   word0 = 0xB1 << 24 | flags << 4 | phase
#   phase 1  leg A done, waiting for the host to park HMAC
#   phase 2  leg B done, waiting for the host to release HMAC
#   phase 3  final result
#
# Result flags in word0[7:4]:
#   bit 4  CHK-KM-PATH-LIVE     leg A clean
#   bit 5  CHK-KM-ISO-TERM      leg B raised an AXI error
#   bit 6  CHK-KM-ISO-REOPEN    leg C clean again
#   bit 7  CHK-KM-ISO-PRECOND   every leg started with both error bits clear
#
# Build (output committed as ../km_rom_iso.parhex):
#   make -C hw/sys/sep/dv/cocotb/tests/km_fw ../km_rom_iso.parhex

#include "key_manager_addr.h"
#include "km_fields.inc"

    .equ MBOX_READ_DATA,   (KEY_MANAGER_MAILBOX_KM_KM_READ_DATA_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ MBOX_STATUS,      (KEY_MANAGER_MAILBOX_KM_KM_STATUS_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)

    # KM SRAM base from the generated map. km_csr.rdl SRAM lock region 0
    # starts at this base.
    .equ KM_SRAM_BASE, KEY_MANAGER_SRAM_BASE_ADDR

    # IRQ_STATUS AXI_SLVERR | AXI_DECERR -- the mask that carries
    # CHK-KM-ISO-TERM, so it comes from the generated field masks, not from a
    # typed number. km_csr.h itself is a C header the assembler cannot pull in;
    # km_fields.inc is the assembler-safe extract the km_fw Makefile lifts
    # out of it, so a field that moves at the next RDL regeneration moves here.
    .equ AXI_ERR_BITS, (KM_CSR__IRQ_STATUS_REG__AXI_SLVERR_bm | \
                        KM_CSR__IRQ_STATUS_REG__AXI_DECERR_bm)
    .equ POLL_LIMIT,   32

    .section .text
    .globl _start
_start:
    # x1  mailbox base
    # x2  HMAC key aperture (the km_hmac path under test)
    # x5  result flags
    # x9  IRQ_STATUS
    # x10 KM SRAM base
    # x6,x7,x11-x14 scratch
    li    x1, KEY_MANAGER_MAILBOX_KM_BASE_ADDR
    li    x2, KEY_MANAGER_HMAC_WRAPPER_KEY_BASE_ADDR
    li    x9, KEY_MANAGER_KMCSR_IRQ_STATUS_BASE_ADDR
    li    x10, KM_SRAM_BASE
    addi  x5, x0, 0
    addi  x15, x0, 0x80            # precondition flag, cleared on any failure

    jal   x13, wait_mbox           # host: HMAC released, go

    # ---- leg A: the path is live -------------------------------------
    jal   x13, clear_errs
    beqz  x14, legA_dirty
    sw    x0, 0(x2)
    jal   x13, poll_err
    bnez  x14, legA_done           # an error here means the path was NOT live
    ori   x5, x5, 0x10             # CHK-KM-PATH-LIVE
    j     legA_done
legA_dirty:
    andi  x15, x15, 0              # precondition broken
legA_done:
    addi  x11, x0, 1
    jal   x13, publish

    jal   x13, wait_mbox           # host: HMAC parked and km_hmac isolated

    # ---- leg B: the path is isolated ---------------------------------
    jal   x13, clear_errs
    beqz  x14, legB_dirty
    sw    x0, 0(x2)
    jal   x13, poll_err
    beqz  x14, legB_done
    ori   x5, x5, 0x20             # CHK-KM-ISO-TERM
    j     legB_done
legB_dirty:
    andi  x15, x15, 0
legB_done:
    addi  x11, x0, AXI_ERR_BITS
    sw    x11, 0(x9)               # W1C so leg C starts clean
    addi  x11, x0, 2
    jal   x13, publish

    jal   x13, wait_mbox           # host: HMAC released again

    # ---- leg C: the path reopened ------------------------------------
    jal   x13, clear_errs
    beqz  x14, legC_dirty
    sw    x0, 0(x2)
    jal   x13, poll_err
    bnez  x14, legC_done
    ori   x5, x5, 0x40             # CHK-KM-ISO-REOPEN
    j     legC_done
legC_dirty:
    andi  x15, x15, 0
legC_done:
    or    x5, x5, x15              # CHK-KM-ISO-PRECOND
    addi  x11, x0, 3
    jal   x13, publish
1:  j     1b

# --- helpers; x13 holds the return address, x14 the result ------------

    # Block until the inbound mailbox holds a word, then consume it.
wait_mbox:
    lw    x6, MBOX_STATUS(x1)
    andi  x6, x6, KM_MAILBOX_KM__STATUS_REG__INBOUND_EMPTY_bm
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

    # Poll IRQ_STATUS a bounded number of times. x14 = 1 if an AXI error bit
    # set within the window. The bits are sticky on the B-handshake pulse, so
    # a set bit cannot be missed once it appears.
poll_err:
    addi  x12, x0, POLL_LIMIT
poll_err_loop:
    lw    x6, 0(x9)
    andi  x6, x6, AXI_ERR_BITS
    bnez  x6, poll_err_set
    addi  x12, x12, -1
    bnez  x12, poll_err_loop
    addi  x14, x0, 0
    jr    x13
poll_err_set:
    addi  x14, x0, 1
    jr    x13

    # Publish flags plus the phase in x11 to KM SRAM word0.
publish:
    lui   x6, 0xB1000              # magic 0xB1 in [31:24]
    or    x6, x6, x5
    or    x6, x6, x11
    sw    x6, 0(x10)
    jr    x13
