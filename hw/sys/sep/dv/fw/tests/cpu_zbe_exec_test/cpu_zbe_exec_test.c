// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Zbe instruction results: Zbe bext (bit extract), Zbe bdep (bit deposit),
// pack and packh.
//
// The host (cocotb/tests/cpu/sep_cpu_zbe_exec_test.py) draws the operand rows
// and patches them into g_prm before reset release. The firmware grades
// nothing: it prints the result of each row, and the host compares it with the
// value of its instruction model.
//
// This file is built for RV32I (fw.mk), so the only Zbe encodings it retires
// are the explicit instruction words of exec_op(). Each word holds the encoding
// of the draft "RISC-V Bitmanip Extension" specification v0.93, section 2.12,
// and is written as data (.word), so the assembler cannot replace it. A word
// that the core does not execute traps to the crt0 handler, which fails the
// run.
//
// Console lines:
//   M G <leg> / M C <leg>     leg markers (sep_console_rec.h)
//   SEED seed=                the seed of the patched block
//   ROW i= op= r=             result of table row i

#include <stdint.h>

#include "sep.h"
#include "sep_console_rec.h"
#include "sep_mailbox.h"
#include "sep_outbound_filter.h"

#define PRM_MAGIC 0x2BE0E7ECu
#define NROW_MAX 160u

enum {
    P_MAGIC = 0,
    P_SEED,
    P_NROW,
    P_ROWS, // NROW_MAX rows of {op, a, b}
    P_WORDS = P_ROWS + 3u * NROW_MAX,
};

volatile uint32_t g_prm[P_WORDS] = {
    [P_MAGIC] = PRM_MAGIC,
};

// ---- the instruction rows: rd = rs1 = a0, rs2 = a1 ----
#define ROW_RR(enc) \
    do { \
        register uint32_t ra_ __asm__("a0") = a; \
        register uint32_t rb_ __asm__("a1") = b; \
        __asm__ volatile(".word " #enc : "+r"(ra_) : "r"(rb_) : "memory"); \
        r = ra_; \
    } while (0)

static uint32_t __attribute__((noinline)) exec_op(uint32_t op, uint32_t a, uint32_t b) {
    uint32_t r = 0xDEADC0DEu;
    switch (op) {
    case 0:
        ROW_RR(0x08b56533);
        break; // Zbe bext a0, a0, a1: funct7 0000100, funct3 110
    case 1:
        ROW_RR(0x48b56533);
        break; // Zbe bdep a0, a0, a1: funct7 0100100, funct3 110
    case 2:
        ROW_RR(0x08b54533);
        break; // pack a0, a0, a1: funct7 0000100, funct3 100, rs2 = a1, never x0
    case 3:
        ROW_RR(0x08b57533);
        break; // packh a0, a0, a1: funct7 0000100, funct3 111
    default:
        break;
    }
    return r;
}

static uint32_t row(uint32_t i, uint32_t k) {
    return g_prm[P_ROWS + 3u * i + k];
}

int main(void) {
    sep_outbound_filter_init();
    sep_mbx_puts("SEP CPU Zbe exec test\n");
    uint32_t nrow = g_prm[P_NROW];
    if (g_prm[P_MAGIC] != PRM_MAGIC || nrow == 0u || nrow > NROW_MAX) {
        sep_mbx_puts("FAIL: parameter block not patched\n");
        return 1;
    }
    sep_mbx_puts("SEED");
    rec_hex("seed", g_prm[P_SEED]);
    rec_end();
    rec_mark(0, "setup");

    rec_mark(1, "zbe");
    for (uint32_t i = 0; i < nrow; i++) {
        uint32_t r = exec_op(row(i, 0), row(i, 1), row(i, 2));
        sep_mbx_puts("ROW");
        rec_hex("i", i);
        rec_hex("op", row(i, 0));
        rec_hex("r", r);
        rec_end();
    }

    rec_mark(0, "end");
    sep_mbx_puts("PASS: CPU Zbe exec\n");
    return 0;
}
