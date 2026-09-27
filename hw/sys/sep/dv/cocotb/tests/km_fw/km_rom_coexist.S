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
#   KM-local memory map (km_intf_pkg.sv):
#     MBOX base = 0x0001_0000
#       WRITE_DATA      +0x0   KM -> EL2 payload
#       WRITE_SEPARATOR +0x4   write 1 to frame a message
#       READ_DATA       +0x8   EL2 -> KM payload
#       STATUS          +0xC   bit0 inbound_empty, bit2 outbound_empty,
#                              bit3 outbound_full
#     OTP/eFuse base = 0x0001_1000 (HW remaps addr[31:12] -> 0x1093_0xxx)
#       MMR0 (RMA_SIP_TOKEN_I[0]) KM-local 0x0001_1500 -> SEP 0x1093_0500
#       MMR1 (RMA_SIP_TOKEN_I[1]) KM-local 0x0001_1504 -> SEP 0x1093_0504
#
# Build (output committed as ../km_rom_coexist.parhex):
#   riscv64-unknown-elf-gcc -nostdlib -march=rv32i -mabi=ilp32 -Ttext=0 \
#       -o km_rom_coexist.elf km_rom_coexist.S
#   riscv64-unknown-elf-objcopy -O binary km_rom_coexist.elf km_rom_coexist.bin
#   python3 gen_parhex.py km_rom_coexist.bin > ../km_rom_coexist.parhex

    .section .text
    .globl _start
_start:
    li    a0, 0x00010000      # KM mailbox base

    # --- send READY to the EL2 (wait outbound space, frame, write) ---
    li    a1, 0xA11FE5EE      # KM_READY_TOKEN
1:  lw    t0, 0xC(a0)         # STATUS
    andi  t1, t0, 0x8         # outbound_full (bit3)
    bnez  t1, 1b              # spin while the KM->EL2 FIFO is full
    li    t2, 1
    sw    t2, 0x4(a0)         # WRITE_SEPARATOR = 1
    sw    a1, 0x0(a0)         # WRITE_DATA = READY

    # --- wait for the EL2 GO word (any inbound word) ---
2:  lw    t0, 0xC(a0)         # STATUS
    andi  t1, t0, 0x1         # inbound_empty (bit0)
    bnez  t1, 2b              # spin while the EL2->KM FIFO is empty
    lw    t0, 0x8(a0)         # READ_DATA = GO (value not inspected)

    # --- free-run eFuse MMR writes ---
    li    a2, 0x00011500      # KEY_MANAGER_OTP_EFUSE_MMR_BASE_ADDR (MMR1 = +0x4)
    li    a3, 0xA5000000      # MMR0 owner tag
    li    a4, 0x5A000000      # MMR1 owner tag
    li    a5, 0x00FFFFFF      # 24-bit payload mask
    li    a6, 1               # counter (start at 1 so the EL2 sees progress)
3:
    and   t0, a6, a5          # payload = counter & 0x00FFFFFF
    or    t1, t0, a4          # MMR1 value = 0x5A000000 | payload
    sw    t1, 0x4(a2)         # write MMR1 (lead)  -> 0x1093_0504
    or    t2, t0, a3          # MMR0 value = 0xA5000000 | payload
    sw    t2, 0x0(a2)         # write MMR0 (trail) -> 0x1093_0500
    addi  a6, a6, 1           # counter++
    j     3b
