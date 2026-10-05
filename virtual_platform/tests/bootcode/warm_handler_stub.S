/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Warm-reset handler for the retained-scratch warm-jump testcases.
 *
 * The test deposits this code in ICCM and writes its entry address to retained
 * cold scratch 7. The ROM validates that pointer and jumps here before setting
 * up sp or gp, so the stub uses only temporaries and never touches the stack.
 *
 * Console packets are written to cold scratch 2. The VP emits payload bytes
 * from bits [15:8], [23:16], then [31:24], skipping zero bytes.
 */

    .option norvc
    .section .text
    .globl _warm_stub
_warm_stub:
    li      t0, 0x10802010

    li      t1, 0x52415700          /* "WAR" */
    sw      t1, 0(t0)
    li      t1, 0x4A5F4D00          /* "M_J" */
    sw      t1, 0(t0)
    li      t1, 0x504D5500          /* "UMP" */
    sw      t1, 0(t0)
    li      t1, 0x4B4F5F00          /* "_OK" */
    sw      t1, 0(t0)
    li      t1, 0x00000A00          /* "\n" */
    sw      t1, 0(t0)

1:  j       1b
