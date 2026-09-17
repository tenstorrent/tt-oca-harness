// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP testbench mailbox (STDOUT) driver.
//
// The mailbox at 0x8000_0000 is the firmware's console + test-completion port:
//   * a BYTE store is decoded by the testbench as a console character;
//   * a WORD store of the magic sequence (0xA5A5_5A5A then 0xCAFE_BABE /
//     0xDEAD_BEEF) is decoded as PASS / FAIL (emitted by crt0.s on exit).
// Reaching the mailbox requires the outbound filter to be opened first
// (see sep_outbound_filter.h).

#ifndef SEP_MAILBOX_H
#define SEP_MAILBOX_H

#include <stdint.h>

#define SEP_STDOUT_ADDR 0x80000000u

static inline void sep_mbx_putc(char c) {
    *((volatile uint8_t *)SEP_STDOUT_ADDR) = (uint8_t)c;
    __asm__ volatile("fence" ::: "memory");
}

static inline void sep_mbx_puts(const char *s) {
    while (*s) {
        sep_mbx_putc(*s++);
    }
}

// Emit a 32-bit value as "0x" + 8 hex digits on the console. Lets a firmware
// test surface a captured value (claim id, status word, counter) in the kept
// simulator log as positive evidence, with no libc/printf.
static inline void sep_mbx_puthex(uint32_t v) {
    static const char hex[] = "0123456789abcdef";
    sep_mbx_putc('0');
    sep_mbx_putc('x');
    for (int nib = 7; nib >= 0; nib--) {
        sep_mbx_putc(hex[(v >> (nib * 4)) & 0xF]);
    }
}

#endif // SEP_MAILBOX_H
