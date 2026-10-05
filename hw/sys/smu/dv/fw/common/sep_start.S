// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP smoke startup. Completion markers go to the DCCM mailbox (top of
// DCCM, below the stack guard) so the smoke has no external-bus dependency.

.section .text.start
.global _start
.type _start, @function

.equ MAILBOX_ADDR, 0xC005FF00

_start:
    .option push
    .option norelax
    la gp, __global_pointer$
    .option pop
    la sp, _stack_top
    andi sp, sp, -16
    call main

    li t0, MAILBOX_ADDR
    li t1, 0xA5A55A5A
    sw t1, 0(t0)
    beqz a0, .Lpass
    li t1, 0xDEADBEEF
    j .Lfinish
.Lpass:
    li t1, 0xCAFEBABE
.Lfinish:
    sw t1, 4(t0)
    fence iorw, iorw
.Lpark:
    wfi
    j .Lpark
