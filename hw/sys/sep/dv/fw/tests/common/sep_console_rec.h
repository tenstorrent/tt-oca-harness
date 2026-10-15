// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Console record lines of a firmware leaf, in the shapes that the host
// follower hw/sys/sep/dv/cocotb/env/sep_fw_console.py parses. One line each:
//
//   M G <leg>                 a graded leg starts (the host opens the window)
//   M C <leg>                 a control, set-up or clean-up leg starts
//   CHK-<NAME> PASS k=v ...   a check record (FAIL on a failed check)
//   CTL-<NAME> LOG k=v ...    a control record
//   OBS-<NAME> LOG k=v ...    a logged value of a blocked check
//   REQ <what> k=v ...        a request to the host
//
// A value prints as 0x<8 hex digits> (rec_hex) or in decimal (rec_dec). The
// console goes through the outbound responder (sep_mailbox.h), so the leaf
// opens the outbound filter before the first record. Header-only, no libc.

#ifndef SEP_CONSOLE_REC_H
#define SEP_CONSOLE_REC_H

#include <stdint.h>

#include "sep_mailbox.h"

// Loop iterations of CPU spin after a marker line, so the host gate write and its tap
// marks land before the first bus access of the leg.
#ifndef SEP_REC_MARK_SPIN
#define SEP_REC_MARK_SPIN 64u
#endif

static inline void rec_dec(uint32_t v) {
    char buf[10];
    int n = 0;
    do {
        buf[n++] = (char)('0' + (v % 10u));
        v /= 10u;
    } while (v != 0u && n < 10);
    while (n > 0) {
        sep_mbx_putc(buf[--n]);
    }
}

// " key=0x<v>"
static inline void rec_hex(const char *key, uint32_t v) {
    sep_mbx_putc(' ');
    sep_mbx_puts(key);
    sep_mbx_putc('=');
    sep_mbx_puthex(v);
}

// " key=<decimal v>"
static inline void rec_num(const char *key, uint32_t v) {
    sep_mbx_putc(' ');
    sep_mbx_puts(key);
    sep_mbx_putc('=');
    rec_dec(v);
}

// " key=<text>" (text holds no blank)
static inline void rec_str(const char *key, const char *text) {
    sep_mbx_putc(' ');
    sep_mbx_puts(key);
    sep_mbx_putc('=');
    sep_mbx_puts(text);
}

// "CHK-<name> PASS" or "CHK-<name> FAIL"; the caller adds fields and rec_end().
static inline void rec_chk(const char *name, int pass) {
    sep_mbx_puts("CHK-");
    sep_mbx_puts(name);
    sep_mbx_puts(pass ? " PASS" : " FAIL");
}

// "CTL-<name> LOG" or "OBS-<name> LOG"; the caller adds fields and rec_end().
static inline void rec_ctl(const char *name) {
    sep_mbx_puts("CTL-");
    sep_mbx_puts(name);
    sep_mbx_puts(" LOG");
}

static inline void rec_obs(const char *name) {
    sep_mbx_puts("OBS-");
    sep_mbx_puts(name);
    sep_mbx_puts(" LOG");
}

// "REQ <what>"; the caller adds fields and rec_end().
static inline void rec_req(const char *what) {
    sep_mbx_puts("REQ ");
    sep_mbx_puts(what);
}

static inline void rec_end(void) {
    sep_mbx_putc('\n');
}

static inline void rec_spin(uint32_t n) {
    for (volatile uint32_t i = 0; i < n; i++) {
    }
}

// "M G <leg>" then a spin; kind_graded 0 prints "M C <leg>".
static inline void rec_mark(int kind_graded, const char *leg) {
    sep_mbx_puts(kind_graded ? "M G " : "M C ");
    sep_mbx_puts(leg);
    sep_mbx_putc('\n');
    rec_spin(SEP_REC_MARK_SPIN);
}

#endif // SEP_CONSOLE_REC_H
