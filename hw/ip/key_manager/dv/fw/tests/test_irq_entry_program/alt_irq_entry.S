/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/* Alternate PicoRV32 IRQ entry at VROM 0x10000100 — sets irq_entry_alt_hit then jumps to crt0 irq_handler. */

.section .text.alt_irq, "ax", @progbits
.align 4
.global alt_irq_vec_entry

alt_irq_vec_entry:
    la t0, irq_entry_alt_hit
    li t1, 1
    sw t1, 0(t0)
    lui t0, %hi(irq_handler)
    jalr zero, %lo(irq_handler)(t0)
