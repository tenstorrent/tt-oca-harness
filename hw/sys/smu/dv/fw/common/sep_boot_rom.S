// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// SEP boot-ROM trampoline from reset ROM to ICCM.

.section .text.start
.global _start
.type _start, @function

_start:
    li t0, 0xC0000000
    jr t0
