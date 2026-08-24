// SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
/* SPDX-License-Identifier: Apache-2.0 */

/* SMC ROM Boot Entry Point
 * This code executes at the very beginning of boot before _start.
 * It performs critical early initialization before entering the C runtime. */
.section .text.metal.init.enter
.global _enter
_enter:
    .cfi_startproc

    .cfi_undefined ra

    /* Initialize all general purpose registers to zero. */
    li x1, 0
    li x2, 0
    li x3, 0
    li x4, 0
    li x5, 0
    li x6, 0
    li x7, 0
    li x8, 0
    li x9, 0
    li x10, 0
    li x11, 0
    li x12, 0
    li x13, 0
    li x14, 0
    li x15, 0
    li x16, 0
    li x17, 0
    li x18, 0
    li x19, 0
    li x20, 0
    li x21, 0
    li x22, 0
    li x23, 0
    li x24, 0
    li x25, 0
    li x26, 0
    li x27, 0
    li x28, 0
    li x29, 0
    li x30, 0
    li x31, 0

    /* SRAM initialization must occur before any stack operations. */
    jal ra, __metal_sram_init_early

    /* MBIST validation after SRAM initialization, before memory repair status handling. */
    jal ra, __metal_mbist_early_check

    /* Memory repair validation after SRAM initialization. */
    jal ra, __metal_memory_repair_check

    /* Configure global pointer after early memory checks complete. */
.option push
.option norelax
#ifdef __riscv_cmodel_compact
1:
    auipc a0, %pcrel_hi(__global_pointer__)
    addi a0, a0, %pcrel_lo(1b)
    ld   gp, 0(a0)
    add  gp, gp, a0
#else
    la gp, __global_pointer$
#endif
.option pop

    /* Configure early boot trap vector. */
    la t0, early_trap_vector
    csrw mtvec, t0

#ifdef ROM_PADDING_SELFTEST
    /*
     * DV-only ROM padding protection self-test. This is never compiled into a
     * production image. Run it immediately after mtvec is installed so the
     * result is independent of later boot operations.
     *
     * Mode 1 jumps to an aligned EBREAK in the linker-defined padding range.
     * Mode 2 executes EBREAK here to exercise the generic breakpoint path.
     */
#if ROM_PADDING_SELFTEST == 2
    ebreak
#else
    la   t0, __rom_used_end
    la   t1, __rom_end
    add  t2, t0, t1
    srli t2, t2, 1
    andi t2, t2, -4
    jr   t2
#endif
#endif

    /* Clear SMC/SEP coordination scratch registers for clean state. */
    jal ra, __metal_clear_coordination_scratch_regs

    /* Set up C runtime environment with proper stack pointer. */
    .weak __metal_stack_pointer
    la sp, __metal_stack_pointer

    bne sp, zero, 1f
#ifdef __riscv_cmodel_compact
    lla.gprel sp, _sp
#else
    la sp, _sp
#endif
1:
    /* Adjust stack pointer per hart ID. */
    csrr a0, mhartid
    li t0, 0
    la t1, __stack_size
1:
    beq t0, a0, 1f
    add sp, sp, t1
    addi t0, t0, 1
    j 1b
1:
    andi sp, sp, -16

    /* Enter C runtime with standard ABI arguments. */
    csrr a0, mhartid
    li a1, 0
    li a2, 0
    call _start

    /* Handle unexpected return from main. */
    .weak __metal_after_main
    la ra, __metal_after_main
    beqz ra, 1f
    jalr ra
1:

    /* Final fallback: infinite loop with trap. */
     la t0, 1f
     csrw mtvec, t0
1:
     lw t1, 0(x0)
     j 1b

    .cfi_endproc

/* Weak frame info stub to prevent linker issues. */
.weak __register_frame_info
.section .text.metal.init.__register_frame_info
__register_frame_info:
    .cfi_startproc
    ret
    .cfi_endproc
