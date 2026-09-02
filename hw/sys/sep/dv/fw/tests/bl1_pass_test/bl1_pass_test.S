/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

// Minimal BL1 test payload for OROM boot flow verification.
//
// After the Boot ROM loads this image into ICCM and jumps to _start,
// it prints debug messages via virtual console (SCRATCH_2), configures
// OBF, then signals PASS via STDOUT mailbox.
//
// Virtual console output (appears as text in cocotb sim log):
//   "BL1\n"     — BL1 entry (proves jump to ICCM succeeded)
//   "OBF\n"     — Outbound filter configured
//   "GO!\n"     — About to write PASS to STDOUT mailbox
//
// No C runtime, no stack, no memory loads — pure register-immediate ops.
// CSR addresses come from generated sep_addr.h.

#include "../../../../regs/gen/c/sep_addr.h"

    .section .text
    .globl _start

// Protocol: [31:24] c3 | [23:16] c2 | [15:8] c1 | [7:4] 0 | [3:1] op=0(ASCII) | [0] toggle

_start:
    // ---------------------------------------------------------------
    // Step 0: Print "BL1\n" — proves we jumped to ICCM successfully
    // ---------------------------------------------------------------
    li    t0, OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(2)
    li    t1, 0x314C4200        // 'B'=0x42 'L'=0x4C '1'=0x31, op=ASCII
    sw    t1, 0(t0)             // SCRATCH_2: "BL1"
    li    t1, 0x00000A00        // '\n'=0x0A, op=ASCII
    sw    t1, 0(t0)             // SCRATCH_2: "\n"

    // ---------------------------------------------------------------
    // Step 1: Configure outbound filter to allow mailbox writes.
    // Matches sep_outbound_filter_init() from sep_outbound_filter.h.
    // Without this, writes to 0x80000000 are silently dropped.
    // ---------------------------------------------------------------

    li    t0, OCH_SEP_TOP_OUTBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR(0)
    lui   t1, 0x80000           // t1 = 0x80000000
    sw    t1, 0(t0)             // START_ADDR[31:0] = 0x80000000
    sw    zero, 4(t0)           // START_ADDR[63:32] = 0x00000000

    li    t0, OCH_SEP_TOP_OUTBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR(0)
    lui   t1, 0x80000           // t1 = 0x80000000
    addi  t1, t1, 0xFF         // t1 = 0x800000FF
    sw    t1, 0(t0)             // END_ADDR[31:0] = 0x800000FF
    sw    zero, 4(t0)           // END_ADDR[63:32] = 0x00000000

    fence w, w                  // ensure START/END committed before CONFIG

    li    t0, OCH_SEP_TOP_OUTBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(0)
    lui   t1, 0x01000           // t1 = 0x01000000
    addi  t1, t1, 0x013        // t1 = 0x01000013
    sw    t1, 0(t0)             // CONFIG[31:0] = 0x01000013
    li    t1, 1
    sw    t1, 4(t0)             // CONFIG[63:32] = 0x00000001

    fence w, w                  // ensure OBF config committed

    // ---------------------------------------------------------------
    // Step 2: Print "OBF\n" — outbound filter configured
    // ---------------------------------------------------------------
    li    t0, OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(2)
    li    t1, 0x46424F00        // 'O'=0x4F 'B'=0x42 'F'=0x46, op=ASCII
    sw    t1, 0(t0)             // SCRATCH_2: "OBF"
    li    t1, 0x00000A01        // '\n'=0x0A, op=ASCII, toggle=1 (avoid dup)
    sw    t1, 0(t0)             // SCRATCH_2: "\n"

    // ---------------------------------------------------------------
    // Step 3: Print "GO!\n" then write PASS to STDOUT mailbox
    // ---------------------------------------------------------------
    li    t1, 0x214F4700        // 'G'=0x47 'O'=0x4F '!'=0x21, op=ASCII
    sw    t1, 0(t0)             // SCRATCH_2: "GO!"
    li    t1, 0x00000A00        // '\n'=0x0A, op=ASCII, toggle=0
    sw    t1, 0(t0)             // SCRATCH_2: "\n"

    // Write ROM_FW_MAGIC0 (0xA5A55A5A) to STDOUT mailbox
    lui   t0, 0x80000           // t0 = 0x80000000 (ROM_MBX_ADDR)
    li    t1, 0xA5A55A5A        // t1 = ROM_FW_MAGIC0
    sw    t1, 0(t0)

    // Write ROM_FW_PASS (0xCAFEBABE) to STDOUT mailbox
    li    t1, 0xCAFEBABE        // t1 = ROM_FW_PASS
    sw    t1, 0(t0)

    // Park: spin in WFI loop
1:  wfi
    j     1b
