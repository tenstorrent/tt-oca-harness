# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2020 Western Digital Corporation or its affiliates
# SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
#
# VeeR EL2 Bare-Metal Startup Code for DV Environment
#
# This minimal crt0.s handles ONLY the essential CPU initialization:
#   1. Set VeeR PMA CSR for memory attributes
#   2. Set mtvec trap handler
#   3. Set meivt for fast interrupt redirect
#   4. Pre-fill vector table to prevent 'X' state fetches
#   5. Initialize gp and tp, zero BSS, initialize sp
#   6. Call main() and handle exit
#
# Test-specific configuration (PIC priorities, interrupt enables, etc.)
# should be done in C code (see interrupt.c).

#include "tb.h"

#==============================================================================
# VeeR EL2 Custom CSR Definitions
#==============================================================================
.equ CSR_MPMC,      0x7c0       # PMA Configuration (VeeR custom)
.equ CSR_MEIVT,     0xBC8       # External interrupt vector table base
.equ CSR_MEIPT,     0xBC9       # External interrupt priority threshold
.equ CSR_MEICURPL,  0xBCC       # Current priority level for nesting
.equ CSR_MEIHAP,    0xFC8       # Handler address pointer (read-only)

#==============================================================================
# Entry Point
#==============================================================================
.section .text.init
.align 4
.global _start
_start:
    #--------------------------------------------------------------------------
    # Step 1: Set VeeR PMA CSR
    #
    # Configure all 256 MB PMA regions as side-effect (uncacheable) EXCEPT
    # region 12 (ICCM/DCCM area). This prevents speculative accesses to
    # peripherals from causing issues.
    # See documentation: https://chipsalliance.github.io/Cores-VeeR-EL2/html/main/docs_rendered/html/memory-map.html#region-access-control-register-mrac
    #
    # MRAC holds two bits per region, region r in bits [2r+1:2r]: bit 2r is
    # cacheable, bit 2r+1 is side-effect.
    # Bit pattern: 0xA8AAAAAA
    #   - Regions 0-11, 13-15:                     0b10 = Side-effect (peripherals)
    #   - Region 12 (0xC000_0000, bits [25:24]):   0b00 = Normal (ICCM/DCCM)
    #--------------------------------------------------------------------------
    li      t0, 0xA8AAAAAA
    csrw    CSR_MPMC, t0

    #--------------------------------------------------------------------------
    # Step 2: Set trap handler (mtvec)
    #
    # All synchronous exceptions (illegal instruction, misaligned access, etc.)
    # will vector here. This default handler fails the test.
    #--------------------------------------------------------------------------
    la      t0, _trap
    csrw    mtvec, t0

    #--------------------------------------------------------------------------
    # Step 3: Set fast interrupt vector table base (meivt)
    #
    # VeeR EL2 with fast_interrupt_redirect=1 uses a table of function POINTERS
    # (not instructions) in DCCM. On external interrupt, hardware:
    #   1. Captures claim ID
    #   2. Loads handler address from meivt + (claimid << 2)
    #   3. Jumps to handler
    #
    # INTVEC_BASE must be 1024-byte aligned (defined in linker script).
    #--------------------------------------------------------------------------
    la      t0, INTVEC_BASE
    csrw    CSR_MEIVT, t0

    #--------------------------------------------------------------------------
    # Step 4: Pre-fill vector table with default handler
    #
    # CRITICAL for RTL simulation: Uninitialized DCCM contains 'X' states.
    # If an unexpected interrupt fires, the CPU would fetch 'X' as the handler
    # address, crashing the simulation.
    #
    # Solution: Fill ALL 256 entries (1KB) with _dummy_int_handler address.
    # Tests can override specific entries as needed.
    #--------------------------------------------------------------------------
    la      t0, INTVEC_BASE         # t0 = base address of vector table
    la      t1, _dummy_int_handler  # t1 = default handler address
    li      t2, 256                 # t2 = loop counter (256 entries)

.L_fill_vector_table:
    sw      t1, 0(t0)               # Store handler address
    addi    t0, t0, 4               # Advance to next entry
    addi    t2, t2, -1              # Decrement counter
    bnez    t2, .L_fill_vector_table

    #--------------------------------------------------------------------------
    # Step 5: Initialize Global Pointer (gp) and Thread Pointer (tp)
    #
    # The global pointer enables efficient access to small data sections
    # via gp-relative addressing (linker relaxation).
    #
    # tp must point at the TLS block before any libc call: a picolibc built
    # with thread-local storage enabled reaches state such as the rand() seed
    # through tp, and would fault on a store to address 0 otherwise. The block
    # is empty when the toolchain emits no TLS.
    #--------------------------------------------------------------------------
    .option push
    .option norelax
    la      gp, __global_pointer$
    .option pop

    la      tp, __tls_base

    #--------------------------------------------------------------------------
    # Step 6: Zero BSS section
    #
    # The .bss section contains uninitialized global/static variables.
    # C runtime expects these to be zero. In RTL sim, they would be 'X'.
    #--------------------------------------------------------------------------
    la      t0, BSS_START           # t0 = start of BSS
    la      t1, BSS_END             # t1 = end of BSS

.L_zero_bss:
    bgeu    t0, t1, .L_bss_done     # Exit if start >= end
    sw      zero, 0(t0)             # Zero one word
    addi    t0, t0, 4               # Advance pointer
    j       .L_zero_bss

.L_bss_done:

    #--------------------------------------------------------------------------
    # Step 7: Initialize Stack Pointer (sp)
    #
    # STACK is defined in linker script, positioned below INTVEC_BASE.
    # Stack grows DOWNWARD toward BSS_END.
    #--------------------------------------------------------------------------
    la      sp, STACK

    #--------------------------------------------------------------------------
    # Step 8: Call main()
    #
    # At this point:
    #   - Memory attributes configured (PMA)
    #   - Trap handler set (mtvec)
    #   - Interrupt vector table initialized (meivt + entries)
    #   - BSS zeroed
    #   - gp, tp and sp initialized
    #   - Interrupts DISABLED (mstatus.mie = 0, mie = 0)
    #
    # Test code in main() is responsible for:
    #   - Configuring PIC priorities and enables
    #   - Enabling specific interrupt sources
    #   - Enabling global interrupts when ready
    #--------------------------------------------------------------------------
    call    main

    #--------------------------------------------------------------------------
    # Step 9: Handle main() return / test completion
    #
    # Exit code convention (magic word protocol):
    #   - main() returns 0: TEST PASS
    #   - main() returns non-zero: TEST FAIL
    #
    # TB expects 2-word sequence to STDOUT (0x80000000):
    #   1. TEST_MAGIC0:     0xA5A55A5A
    #   2. Pass/Fail:       TEST_MAGIC_PASS (0xCAFEBABE) or TEST_MAGIC_FAIL (0xDEADBEEF)
    #--------------------------------------------------------------------------
    snez    a0, a0                  # a0 = (a0 != 0) ? 1 : 0 (1=fail, 0=pass)

.global _finish
_finish:
    li      t0, STDOUT

    # Write magic0 word first
    li      t1, TEST_MAGIC0
    sw      t1, 0(t0)
    fence

    # Write pass/fail magic word based on a0
    # a0 == 0 -> PASS, a0 != 0 -> FAIL
    bnez    a0, .L_finish_fail
    li      t1, TEST_MAGIC_PASS
    j       .L_finish_write
.L_finish_fail:
    li      t1, TEST_MAGIC_FAIL
.L_finish_write:
    sw      t1, 0(t0)
    fence

    # Spin with NOPs to allow TB to detect completion
    .rept 10
    nop
    .endr
    j       _finish                 # Infinite loop (TB should terminate)

#==============================================================================
# Default Trap Handler
#
# Handles synchronous exceptions (ecall, illegal instruction, faults, etc.)
# Default behavior: FAIL the test. Tests can override mtvec if needed.
#==============================================================================
.align 4
_trap:
    # Print mcause/mepc/mtval as hex, one character per sb: the STDOUT monitor
    # decodes byte stores as characters.
    li      t0, STDOUT

    # Print "TRAP mc="
    li      t1, 'T'
    sb      t1, 0(t0)
    li      t1, 'R'
    sb      t1, 0(t0)
    li      t1, 'A'
    sb      t1, 0(t0)
    li      t1, 'P'
    sb      t1, 0(t0)
    li      t1, ' '
    sb      t1, 0(t0)
    li      t1, 'm'
    sb      t1, 0(t0)
    li      t1, 'c'
    sb      t1, 0(t0)
    li      t1, '='
    sb      t1, 0(t0)

    # Print mcause as 8-digit hex
    csrr    a1, mcause
    jal     ra, _print_hex32

    # Print " pc="
    li      t1, ' '
    sb      t1, 0(t0)
    li      t1, 'p'
    sb      t1, 0(t0)
    li      t1, 'c'
    sb      t1, 0(t0)
    li      t1, '='
    sb      t1, 0(t0)

    # Print mepc as 8-digit hex
    csrr    a1, mepc
    jal     ra, _print_hex32

    # Print " mt="
    li      t1, ' '
    sb      t1, 0(t0)
    li      t1, 'm'
    sb      t1, 0(t0)
    li      t1, 't'
    sb      t1, 0(t0)
    li      t1, '='
    sb      t1, 0(t0)

    # Print mtval as 8-digit hex
    csrr    a1, mtval
    jal     ra, _print_hex32

    # Newline
    li      t1, '\n'
    sb      t1, 0(t0)

    li      a0, 1                   # Exit code = FAIL
    j       _finish

# Helper: print 32-bit value in a1 as 8 hex digits to STDOUT (t0)
# Clobbers: t1, t2, t3, a1
_print_hex32:
    li      t2, 8                   # 8 nibbles
.L_hex_loop:
    srli    t1, a1, 28              # top nibble
    andi    t1, t1, 0xf
    li      t3, 10
    blt     t1, t3, .L_hex_digit
    addi    t1, t1, ('a' - 10)
    j       .L_hex_write
.L_hex_digit:
    addi    t1, t1, '0'
.L_hex_write:
    sb      t1, 0(t0)
    slli    a1, a1, 4              # shift left for next nibble
    addi    t2, t2, -1
    bnez    t2, .L_hex_loop
    ret

#==============================================================================
# Default Interrupt Handler
#
# This is the fallback handler for ALL external interrupt sources.
# It's pre-loaded into every vector table entry to prevent 'X' state crashes.
#
# For VeeR EL2 with fast_interrupt_redirect=1:
#   - Hardware automatically captures claim ID in meihap
#   - Handler executes and returns with mret
#   - meicpct CSR does NOT exist (auto-capture)
#
# This default handler disables the interrupt source to prevent infinite loops
# from level-triggered interrupts that aren't cleared at the source.
#
# Tests should register their own handlers for expected interrupts:
#   la t0, INTVEC_BASE
#   la t1, my_handler
#   sw t1, (SOURCE_ID * 4)(t0)
#   fence
#==============================================================================
.align 4
.global _dummy_int_handler
_dummy_int_handler:
    # Save caller-saved registers we'll use
    addi    sp, sp, -16
    sw      t0, 0(sp)
    sw      t1, 4(sp)
    sw      t2, 8(sp)
    sw      ra, 12(sp)

    # Get claim ID from meihap
    # meihap format: {base[31:10], claimid[9:2], 2'b00}
    csrr    t0, CSR_MEIHAP
    srli    t0, t0, 2
    andi    t0, t0, 0xFF            # t0 = claimid (0-255)

    # Witness for firmware quiet-window checks: an unregistered source that
    # reaches this handler must fail the test that looks at the count.
    la      t1, sep_dummy_int_count
    lw      t2, 0(t1)
    addi    t2, t2, 1
    sw      t2, 0(t1)

    # Disable this interrupt source at PIC to prevent infinite re-entry.
    # Source 0 is the tied no-interrupt source, so its MEIE word is reserved.
    beqz    t0, .L_dummy_int_done
    # The MEIE word stride comes from the generated register map.
    li      t1, (SEP_TOP_PIC_MEIE_BASE_ADDR(1) - SEP_TOP_PIC_MEIE_BASE_ADDR(0))
    mul     t2, t0, t1              # t2 = claimid * MEIE stride
    li      t1, SEP_TOP_PIC_MEIE_BASE_ADDR(0)
    add     t1, t1, t2              # t1 = MEIE for this claim
    sw      zero, 0(t1)             # Disable interrupt source
.L_dummy_int_done:

    # Restore registers
    lw      t0, 0(sp)
    lw      t1, 4(sp)
    lw      t2, 8(sp)
    lw      ra, 12(sp)
    addi    sp, sp, 16

    mret

#==============================================================================
# Exit Symbol
#==============================================================================
.global _exit
_exit:
    j       _finish

#==============================================================================
# NMI Handler Trampoline (256-byte aligned)
#
# VeeR EL2 NMI mechanism:
#   - nmi_vec[31:1] input provides the handler address (lower bit always 0)
#   - nmi_int signal triggers the NMI (must be high for 2+ cycles)
#   - CPU jumps to address in nmi_vec when NMI fires
#   - NMI uses standard RISC-V trap: mepc = interrupted PC, mret restores it
#
# This trampoline:
#   1. Saves all caller-saved registers (ra, t0-t6, a0-a7) on the stack
#   2. Calls the C handler via jalr, which sets ra to the return point
#   3. Restores registers after handler returns
#   4. Executes mret to return to the exact interrupted instruction
#
# This ensures the C NMI handler:
#   - Can be a leaf or non-leaf function
#   - Does not corrupt interrupted code's registers
#   - Returns to the interrupted instruction via mepc
#
# Default behavior: jump to _default_nmi_handler which fails the test.
#==============================================================================
.section .nmi_handler, "ax"
.balign 256
.global _nmi_handler
_nmi_handler:
    # Save all caller-saved registers so interrupted code is not corrupted.
    # Allocate 17 words: ra + t0-t6 (7) + a0-a7 (8) = 17 registers.
    addi    sp, sp, -68
    sw      ra,  0(sp)
    sw      t0,  4(sp)
    sw      t1,  8(sp)
    sw      t2, 12(sp)
    sw      t3, 16(sp)
    sw      t4, 20(sp)
    sw      t5, 24(sp)
    sw      t6, 28(sp)
    sw      a0, 32(sp)
    sw      a1, 36(sp)
    sw      a2, 40(sp)
    sw      a3, 44(sp)
    sw      a4, 48(sp)
    sw      a5, 52(sp)
    sw      a6, 56(sp)
    sw      a7, 60(sp)

    # Load handler pointer and CALL it (jalr sets ra = return address here)
    la      t0, _nmi_handler_ptr
    lw      t0, 0(t0)
    jalr    ra, 0(t0)           # ra = the restore sequence below

    # Restore all saved registers
    lw      ra,  0(sp)
    lw      t0,  4(sp)
    lw      t1,  8(sp)
    lw      t2, 12(sp)
    lw      t3, 16(sp)
    lw      t4, 20(sp)
    lw      t5, 24(sp)
    lw      t6, 28(sp)
    lw      a0, 32(sp)
    lw      a1, 36(sp)
    lw      a2, 40(sp)
    lw      a3, 44(sp)
    lw      a4, 48(sp)
    lw      a5, 52(sp)
    lw      a6, 56(sp)
    lw      a7, 60(sp)
    addi    sp, sp, 68

    # Return to exact interrupted instruction via mret
    mret

#==============================================================================
# Default NMI Handler
#
# Called when NMI fires but no custom handler has been registered.
# Treats unexpected NMI as a test failure.
#==============================================================================
.section .text
.global _default_nmi_handler
_default_nmi_handler:
    li      a0, 1           # Exit code = FAIL (unexpected NMI)
    j       _finish

#==============================================================================
# Data Section
#==============================================================================
.section .data.io
.global tohost
tohost: .word STDOUT

#==============================================================================
# NMI Handler Pointer (runtime-configurable)
#
# Tests can override this at runtime via nmi_register_handler() in nmi.h
# Default value points to _default_nmi_handler
#==============================================================================
.section .data
.global _nmi_handler_ptr
_nmi_handler_ptr:
    .word _default_nmi_handler

# Spurious-service count. _dummy_int_handler increments this on every claim.
# Zeroed with BSS. Firmware that grades a quiet window reads it; other tests
# ignore it.
.section .bss
.align 4
.global sep_dummy_int_count
sep_dummy_int_count:
    .word 0
