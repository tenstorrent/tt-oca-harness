/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * Warm-path target that announces execution and then takes an illegal
 * instruction fault. PST is intentionally unreachable and acts as the
 * post-fault negative witness.
 */

    .option norvc
    .section .text
    .globl _warm_fault_stub
_warm_fault_stub:
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

    .word   0x00000000              /* illegal instruction */

    li      t1, 0x54535000          /* "PST" */
    sw      t1, 0(t0)
    li      t1, 0x00000A00          /* "\n" */
    sw      t1, 0(t0)

1:  j       1b
