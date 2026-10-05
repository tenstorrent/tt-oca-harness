// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// (c) 2026 Tenstorrent USA Inc
//
// _exit stub for ROM-mode DV tests.
//
// crt0 calls exit() which calls _exit().  ROM tests never actually return, but
// picolibc needs _exit to resolve the symbol at link time.  Provide the stub
// here so any test linked in "rom" mode links cleanly.  Sram-mode tests never
// call _exit (no startup code) so this symbol is stripped by --gc-sections.

#include <stdint.h>

__attribute__((noreturn)) void _exit(int code) {
    (void)code;
    while (1) {
        __asm__ volatile("wfi");
    }
}
