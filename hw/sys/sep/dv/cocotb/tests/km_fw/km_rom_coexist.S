# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# KM (PicoRV32) ROM firmware for the SEP OSS dual-CPU eFuse AXI-lite mux
# coexistence test (reference sep_efuse_km_axil_cpu_mux_coexist_test).
#
# The Key Manager contends with the EL2 host at the shared eFuse AXI-lite mux:
# after a mailbox handshake with the EL2 it free-runs eFuse MMR writes so the EL2
# can observe KM progress, owner-tag attribution, and ordering through the mux.
#
# Protocol (MUST match km_efuse_coexist.c + the cocotb observer):
#   - send  KM_READY_TOKEN (0xA11FE5EE) to the EL2 over the KM<->SEP mailbox;
#   - wait for the EL2's GO word (any inbound word; the EL2 only sends GO);
#   - free-run: payload = counter & 0x00FFFFFF; write MMR1 (lead) = 0x5A000000 |
#     payload, then MMR0 (trail) = 0xA5000000 | payload; counter++. Writing the
#     lead before the trail guarantees MMR1 >= MMR0 for a correct mux, so the EL2
#     can flag a torn/cross-attributed response.
#
#   KM-local addresses and STATUS field masks come from the generated map
#   (key_manager_addr.h) and km_fields.inc (lifted from km_mailbox_km.h):
#     mailbox WRITE_DATA / WRITE_SEPARATOR / READ_DATA / STATUS, and
#     MMR0 = OTP_EFUSE_MMR RMA_SIP_TOKEN_I[0], MMR1 = RMA_SIP_TOKEN_I[1].
#   The EL2 reads the same two registers at their SEP-side addresses.
#
# Build (output committed as ../km_rom_coexist.parhex):
#   make -C hw/sys/sep/dv/cocotb/tests/km_fw ../km_rom_coexist.parhex

#include "key_manager_addr.h"
#include "km_fields.inc"

#define MBOX_INBOUND_EMPTY  KM_MAILBOX_KM__STATUS_REG__INBOUND_EMPTY_bm
#define MBOX_OUTBOUND_FULL  KM_MAILBOX_KM__STATUS_REG__OUTBOUND_FULL_bm

    // Offsets from the mailbox block base, derived from the generated map.
    .equ MBOX_WRITE_DATA,  (KEY_MANAGER_MAILBOX_KM_KM_WRITE_DATA_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ MBOX_WRITE_SEP,   (KEY_MANAGER_MAILBOX_KM_KM_WRITE_SEPARATOR_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ MBOX_READ_DATA,   (KEY_MANAGER_MAILBOX_KM_KM_READ_DATA_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    .equ MBOX_STATUS,      (KEY_MANAGER_MAILBOX_KM_KM_STATUS_BASE_ADDR - KEY_MANAGER_MAILBOX_KM_BASE_ADDR)
    // MMR1 is addressed as its offset from MMR0.
    .equ EFUSE_MMR1_OFF,   (KEY_MANAGER_OTP_EFUSE_MMR_RMA_SIP_TOKEN_I_BASE_ADDR(1) - KEY_MANAGER_OTP_EFUSE_MMR_RMA_SIP_TOKEN_I_BASE_ADDR(0))

    .section .text
    .globl _start
_start:
    li    a0, KEY_MANAGER_MAILBOX_KM_BASE_ADDR

    # --- send READY to the EL2 (wait outbound space, frame, write) ---
    li    a1, 0xA11FE5EE      # KM_READY_TOKEN
1:  lw    t0, MBOX_STATUS(a0)
    andi  t1, t0, MBOX_OUTBOUND_FULL
    bnez  t1, 1b              # spin while the KM->EL2 FIFO is full
    li    t2, 1
    sw    t2, MBOX_WRITE_SEP(a0)   # WRITE_SEPARATOR = 1
    sw    a1, MBOX_WRITE_DATA(a0)  # WRITE_DATA = READY

    # --- wait for the EL2 GO word (any inbound word) ---
2:  lw    t0, MBOX_STATUS(a0)
    andi  t1, t0, MBOX_INBOUND_EMPTY
    bnez  t1, 2b              # spin while the EL2->KM FIFO is empty
    lw    t0, MBOX_READ_DATA(a0)  # GO (value not inspected)

    # --- free-run eFuse MMR writes ---
    li    a2, KEY_MANAGER_OTP_EFUSE_MMR_RMA_SIP_TOKEN_I_BASE_ADDR(0)  # MMR0
    li    a3, 0xA5000000      # MMR0 owner tag
    li    a4, 0x5A000000      # MMR1 owner tag
    li    a5, 0x00FFFFFF      # 24-bit payload mask
    li    a6, 1               # counter (start at 1 so the EL2 sees progress)
3:
    and   t0, a6, a5          # payload = counter & 0x00FFFFFF
    or    t1, t0, a4          # MMR1 value = 0x5A000000 | payload
    sw    t1, EFUSE_MMR1_OFF(a2)  # write MMR1 (lead)
    or    t2, t0, a3          # MMR0 value = 0xA5000000 | payload
    sw    t2, 0(a2)           # write MMR0 (trail)
    addi  a6, a6, 1           # counter++
    j     3b
