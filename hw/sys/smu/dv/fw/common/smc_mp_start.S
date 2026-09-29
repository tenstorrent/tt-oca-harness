// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// SMC ROM entry for images that run on every hart: each hart takes its own
// 2 KiB stack below _stack_top and calls main(mhartid).

.section .text.start
.global _start
.type _start, @function

_start:
    .option push
    .option norelax
    la gp, __global_pointer$
    .option pop

    csrr a0, mhartid
    la sp, _stack_top
    slli t0, a0, 11
    sub sp, sp, t0
    andi sp, sp, -16
    call main

.Lpark:
    wfi
    j .Lpark
