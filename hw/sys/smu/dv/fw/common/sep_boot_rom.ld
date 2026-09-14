/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

OUTPUT_ARCH("riscv")
ENTRY(_start)

SECTIONS
{
    . = 0x10040000;
    .text : {
        KEEP(*(.text.start))
        *(.text .text.*)
    }
}
