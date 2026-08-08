/* Copyright 2026 Tenstorrent Inc. */
/* Key Manager Startup Code for PicoRV32 with q-register IRQ support */

/*
 * Memory Layout:
 *   0x0000_0000 - Reset vector (_start)
 *   0x0000_0010 - IRQ vector (irq_vec)
 *   0x0000_4000 - SRAM base
 *   _stack      - Stack top (linker-defined, top of SRAM)
 *
 * PicoRV32 IRQ Configuration (ENABLE_IRQ_QREGS=1):
 *   - q0 = return address (saved PC + compressed-width bit)
 *   - q1 = IRQ bitmask
 *   - q2/q3 = temporary q-register scratch used by entry wrapper
 *
 * Internal IRQ Sources:
 *   IRQ 0 - Timer (disabled in this build)
 *   IRQ 1 - EBREAK/Illegal Instruction
 *   IRQ 2 - Bus Error (Misaligned Access)
 */

/* PicoRV32 custom instructions (custom0 opcode) */

/* maskirq rd, rs - Set IRQ mask, return old mask in rd */
.macro picorv32_maskirq rd, rs
    .word ((0b0000011 << 25) | (\rs << 15) | (0b110 << 12) | (\rd << 7) | 0b0001011)
.endm

/* getq rd_num, qid - Read q-register qid (0..3) into rd_num (x-register id) */
.macro picorv32_getq rd_num, qid
    .word ((0b0000000 << 25) | (\qid << 15) | (0b100 << 12) | (\rd_num << 7) | 0b0001011)
.endm

/* setq qid, rs_num - Write q-register qid (0..3) from rs_num (x-register id) */
.macro picorv32_setq qid, rs_num
    .word ((0b0000001 << 25) | (\rs_num << 15) | (0b010 << 12) | (\qid << 7) | 0b0001011)
.endm

/* retirq - Return from interrupt */
.macro picorv32_retirq
    .word ((0b0000010 << 25) | 0b0001011)
.endm

/* waitirq rd - Sleep until interrupt, return pending IRQ mask in rd */
.macro picorv32_waitirq rd
    .word ((0b0000100 << 25) | (0b100 << 12) | (\rd << 7) | 0b0001011)
.endm

/*===========================================================================
 * Reset Vector - Entry Point at Address 0x0000_0000
 *===========================================================================*/

.section .text._start, "ax", @progbits
.global _start
_start:
    /* Long jump to _start_init.
     * JAL has ±1MB range; use LUI+JALR for full 32-bit address. */
    lui t0, %hi(_start_init)
    jalr zero, %lo(_start_init)(t0)

/*===========================================================================
 * IRQ Vector - Must be at Address 0x0000_0010 (16 bytes from reset)
 *===========================================================================*/

.section .text.irq_vec, "ax", @progbits
.align 4
.global irq_vec
irq_vec:
    j irq_handler

/*===========================================================================
 * IRQ Handler (q-register mode)
 *
 * On entry with ENABLE_IRQ_QREGS=1:
 *   q0 = return address
 *   q1 = IRQ mask
 *===========================================================================*/

.section .text.irq_handler, "ax", @progbits
.align 4
.global irq_handler
irq_handler:
    /* Preserve ra/sp immediately in q2/q3 before clobbering GPRs. */
    picorv32_setq 2, 1
    picorv32_setq 3, 2

    la x1, irq_frame

    /* Save q-register IRQ state. */
    picorv32_getq 2, 0
    sw x2, 0*4(x1)    /* ret_addr (q0) */
    picorv32_getq 2, 1
    sw x2, 1*4(x1)    /* irq_mask (q1) */
    picorv32_getq 2, 2
    sw x2, 2*4(x1)    /* x1 (ra) */
    picorv32_getq 2, 3
    sw x2, 3*4(x1)    /* x2 (sp) */

    /* Save RV32E GPR state x3..x15. */
    sw x3,  4*4(x1)
    sw x4,  5*4(x1)
    sw x5,  6*4(x1)
    sw x6,  7*4(x1)
    sw x7,  8*4(x1)
    sw x8,  9*4(x1)
    sw x9,  10*4(x1)
    sw x10, 11*4(x1)
    sw x11, 12*4(x1)
    sw x12, 13*4(x1)
    sw x13, 14*4(x1)
    sw x14, 15*4(x1)
    sw x15, 16*4(x1)

    /* Switch to dedicated IRQ stack and call C handler. */
    la sp, irq_stack_top
    mv a0, x1

    la t0, rom_irq
    beqz t0, irq_restore
    jalr ra, t0

irq_restore:
    la x1, irq_frame

    /* Restore q-register state from frame. */
    lw x2, 0*4(x1)
    picorv32_setq 0, 2
    lw x2, 1*4(x1)
    picorv32_setq 1, 2
    lw x2, 2*4(x1)
    picorv32_setq 2, 2
    lw x2, 3*4(x1)
    picorv32_setq 3, 2

    /* Restore RV32E GPR state x3..x15. */
    lw x3,  4*4(x1)
    lw x4,  5*4(x1)
    lw x5,  6*4(x1)
    lw x6,  7*4(x1)
    lw x7,  8*4(x1)
    lw x8,  9*4(x1)
    lw x9,  10*4(x1)
    lw x10, 11*4(x1)
    lw x11, 12*4(x1)
    lw x12, 13*4(x1)
    lw x13, 14*4(x1)
    lw x14, 15*4(x1)
    lw x15, 16*4(x1)

    /* Restore ra/sp from q2/q3. */
    picorv32_getq 1, 2
    picorv32_getq 2, 3

    picorv32_retirq

/*===========================================================================
 * Main Initialization (after IRQ handler)
 *===========================================================================*/

.section .text
.align 4
.global _start_init
_start_init:
    /* Establish a defined state for every RV32E GPR before anything else.
     * tp (x4) is never written by C code, and several other GPRs are not yet
     * written when the first IRQ fires. Because the IRQ handler context-saves
     * x1..x15 into irq_frame (in parity-protected SRAM), an X-valued GPR would
     * be stored with X parity and later read back as an X parity error, which
     * poisons the KM IRQ aggregation. Zeroing here gives a deterministic boot
     * state. */
    li x1,  0
    li x2,  0
    li x3,  0
    li x4,  0
    li x5,  0
    li x6,  0
    li x7,  0
    li x8,  0
    li x9,  0
    li x10, 0
    li x11, 0
    li x12, 0
    li x13, 0
    li x14, 0
    li x15, 0

    /* Initialize global pointer and stack pointer. */
    .option push
    .option norelax
    la gp, __global_pointer$
    .option pop
    la sp, _stack

    /* Copy initialized data from load address to SRAM VMA. */
    la t0, DATA_LOAD_START
    la t1, DATA_START
    la t2, DATA_END
    beq t1, t2, data_done
    beq t0, t1, data_done
copy_data:
    bgeu t1, t2, data_done
    lbu a0, 0(t0)
    sb a0, 0(t1)
    addi t0, t0, 1
    addi t1, t1, 1
    j copy_data
data_done:

    /* Clear BSS section. */
    la t0, BSS_START
    la t1, BSS_END
clear_bss:
    bgeu t0, t1, bss_done
    sw zero, 0(t0)
    addi t0, t0, 4
    j clear_bss
bss_done:

    call main
    j _exit

.global _exit
_exit:
    picorv32_waitirq 0
    j _exit

/*===========================================================================
 * Default weak IRQ handler (can be overridden by C code)
 *===========================================================================*/

.weak rom_irq
.global rom_irq
rom_irq:
    ret

/*===========================================================================
 * IRQ frame and stack in BSS
 *===========================================================================*/

.section .bss
.align 4
.global irq_frame
irq_frame:
    .fill 17, 4, 0

/* IRQ stack (64 words = 256 bytes) */
.align 4
irq_stack_base:
    .fill 64, 4, 0
.global irq_stack_top
irq_stack_top:
