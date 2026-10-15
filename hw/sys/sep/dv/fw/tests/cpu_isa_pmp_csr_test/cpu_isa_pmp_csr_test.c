// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// RV32 M, C, Zba, Zbb and Zbc instruction results, the Zbs illegal-instruction
// trap, the pmpaddr registers, mrac against a PMP-denied user-mode load, and
// the minstret delta of a straight-line block.
//
// The host (cocotb/tests/cpu/sep_cpu_isa_pmp_csr_test.py) draws the operands,
// the 16 pmpaddr values, the four mrac values and the seeded SRAM words, and
// patches them with the expected results of its instruction model into g_prm
// before reset release. The firmware grades nothing: it prints each result, CSR
// readback and trap record, and the host compares them with its table.
//
// This file is built for RV32I (fw.mk), so the only M, C, Zba, Zbb, Zbc or Zbs
// encodings it retires are the explicit instruction words of exec_op() and of
// the bset step. Each row word is written as data (.word / .half), so the
// assembler cannot replace it.
//
// Console lines:
//   M G <leg> / M C <leg>                  leg markers (sep_console_rec.h)
//   ROW i= op= r= / CROW i= op= r=         result of table row i (control rows after bset)
//   ZBS traps= mcause= mepc= pc=           the bset step
//   PMP0 r0..r15= / PMPC i= r0..r15=       pmpaddr readbacks after the drawn and the complement
//   writes MSECCFG v= traps= MRAC j= v= rb= traps= mcause= mepc= rok= rden= INSTRET r1= r2= pc1=
//   pc2=

#include <stdint.h>

#include "sep.h"
#include "sep_console_rec.h"
#include "sep_mailbox.h"
#include "sep_outbound_filter.h"

#define PRM_MAGIC 0x3529A15Au
#define NROW_MAX 306u
#define NCTRL 5u
#define NPMP 16u
#define NMRAC 4u

enum {
    P_MAGIC = 0,
    P_SEED,
    P_NROW,
    P_CTRL,                 // NCTRL row indices re-run after the bset trap
    P_PMP = P_CTRL + NCTRL, // 16 drawn pmpaddr values
    P_MRAC = P_PMP + NPMP,  // 4 drawn mrac values
    P_AW = P_MRAC + NMRAC,  // 4 seeded words of the allowed region
    P_DW = P_AW + NMRAC,    // 4 seeded words of the denied region
    P_AREG = P_DW + NMRAC,  // allowed SRAM region base (4 KiB aligned)
    P_DREG,                 // denied SRAM region base (4 KiB aligned)
    P_ROWS,                 // NROW_MAX rows of {op, a, b, expected}
    P_WORDS = P_ROWS + 4u * NROW_MAX,
};

volatile uint32_t g_prm[P_WORDS] = {
    [P_MAGIC] = PRM_MAGIC,
};

#define MRAC_BOOT 0xA8AAAAAAu // the crt0 value: regions side-effect except 0xC
#define MSTATUS_MPP 0x1800u
#define PMP_R 0x01u
#define PMP_X 0x04u
#define PMP_NAPOT 0x18u

#define CSR_READ(n) \
    ({ \
        uint32_t v_; \
        __asm__ volatile("csrr %0, " #n : "=r"(v_)::"memory"); \
        v_; \
    })
#define CSR_WRITE(n, v) __asm__ volatile("csrw " #n ", %0" ::"r"(v) : "memory")

// ---- trap entry: save the caller-saved registers, call trap_c, mret ----
__asm__(".section .text.trap_entry,\"ax\",@progbits\n"
        ".balign 4\n"
        ".global trap_entry\n"
        "trap_entry:\n"
        "addi sp, sp, -64\n"
        "sw ra, 0(sp)\n sw t0, 4(sp)\n sw t1, 8(sp)\n sw t2, 12(sp)\n"
        "sw t3, 16(sp)\n sw t4, 20(sp)\n sw t5, 24(sp)\n sw t6, 28(sp)\n"
        "sw a0, 32(sp)\n sw a1, 36(sp)\n sw a2, 40(sp)\n sw a3, 44(sp)\n"
        "sw a4, 48(sp)\n sw a5, 52(sp)\n sw a6, 56(sp)\n sw a7, 60(sp)\n"
        "mv a0, sp\n"
        "call trap_c\n"
        "lw ra, 0(sp)\n lw t0, 4(sp)\n lw t1, 8(sp)\n lw t2, 12(sp)\n"
        "lw t3, 16(sp)\n lw t4, 20(sp)\n lw t5, 24(sp)\n lw t6, 28(sp)\n"
        "lw a0, 32(sp)\n lw a1, 36(sp)\n lw a2, 40(sp)\n lw a3, 44(sp)\n"
        "lw a4, 48(sp)\n lw a5, 52(sp)\n lw a6, 56(sp)\n lw a7, 60(sp)\n"
        "addi sp, sp, 64\n"
        "mret\n"
        ".previous\n");
void trap_entry(void);

// ---- user-mode stub, alone in one 4 KiB ICCM page ----
// run_user(allowed, denied) enters user mode at umode_stub with s2 = allowed
// and s3 = denied. The stub loads the allowed word into t3, the denied word
// into t4, and exits with ecall. The trap handler returns to umode_return in
// machine mode.
__asm__(".section .text.umode,\"ax\",@progbits\n"
        ".balign 4096\n"
        ".global umode_stub\n"
        "umode_stub:\n"
        "lw t3, 0(s2)\n"
        "lw t4, 0(s3)\n"
        "ecall\n"
        ".balign 4096\n"
        ".section .text.run_user,\"ax\",@progbits\n"
        ".balign 4\n"
        ".global run_user\n"
        "run_user:\n"
        "addi sp, sp, -16\n"
        "sw ra, 0(sp)\n sw s2, 4(sp)\n sw s3, 8(sp)\n"
        "la t0, g_user_sp\n"
        "sw sp, 0(t0)\n"
        "mv s2, a0\n"
        "mv s3, a1\n"
        "li t3, 0\n"
        "li t4, 0\n"
        "la t0, umode_stub\n"
        "csrw mepc, t0\n"
        "li t0, 0x1800\n"
        "csrc mstatus, t0\n"
        "mret\n"
        ".global umode_return\n"
        "umode_return:\n"
        "la t0, g_user_sp\n"
        "lw sp, 0(t0)\n"
        "lw ra, 0(sp)\n lw s2, 4(sp)\n lw s3, 8(sp)\n"
        "addi sp, sp, 16\n"
        "ret\n"
        ".previous\n");
void run_user(uint32_t allowed, uint32_t denied);
extern char umode_stub[];
extern char umode_return[];

volatile uint32_t g_user_sp;
static volatile uint32_t g_ntrap;
static volatile uint32_t g_mcause, g_mepc, g_t3, g_t4;

void trap_c(uint32_t *frame) {
    uint32_t mc = CSR_READ(mcause);
    uint32_t epc = CSR_READ(mepc);
    uint32_t mst = CSR_READ(mstatus);
    g_mcause = mc;
    g_mepc = epc;
    g_t3 = frame[4];
    g_t4 = frame[5];
    g_ntrap = g_ntrap + 1u;
    if ((mst & MSTATUS_MPP) == 0u) {
        // A trap from user mode returns to umode_return in machine mode.
        CSR_WRITE(mepc, (uint32_t)(uintptr_t)umode_return);
        __asm__ volatile("csrs mstatus, %0" ::"r"(MSTATUS_MPP) : "memory");
    } else {
        // A machine-mode exception resumes after its 32-bit instruction word.
        CSR_WRITE(mepc, epc + 4u);
    }
}

// ---- the instruction rows: rd = rs1 = a0, rs2 = a1 ----
#define ROW_RR(enc) \
    do { \
        register uint32_t ra_ __asm__("a0") = a; \
        register uint32_t rb_ __asm__("a1") = b; \
        __asm__ volatile(".word " #enc : "+r"(ra_) : "r"(rb_) : "memory"); \
        r = ra_; \
    } while (0)
#define ROW_C(enc) \
    do { \
        register uint32_t ra_ __asm__("a0") = a; \
        register uint32_t rb_ __asm__("a1") = b; \
        __asm__ volatile(".half " #enc : "+r"(ra_) : "r"(rb_) : "memory"); \
        r = ra_; \
    } while (0)

static uint32_t __attribute__((noinline)) exec_op(uint32_t op, uint32_t a, uint32_t b) {
    uint32_t r = 0xDEADC0DEu;
    switch (op) {
    case 0:
        ROW_RR(0x02b50533);
        break; // mul a0, a0, a1
    case 1:
        ROW_RR(0x02b51533);
        break; // mulh
    case 2:
        ROW_RR(0x02b52533);
        break; // mulhsu
    case 3:
        ROW_RR(0x02b53533);
        break; // mulhu
    case 4:
        ROW_RR(0x02b54533);
        break; // div
    case 5:
        ROW_RR(0x02b55533);
        break; // divu
    case 6:
        ROW_RR(0x02b56533);
        break; // rem
    case 7:
        ROW_RR(0x02b57533);
        break; // remu
    case 8:
        ROW_C(0x952e);
        break; // c.add a0, a1
    case 9:
        ROW_C(0x1565);
        break; // c.addi a0, -7
    case 10:
        ROW_C(0x8d0d);
        break; // c.sub a0, a1
    case 11:
        ROW_C(0x0536);
        break; // c.slli a0, 13
    case 12:
        ROW_RR(0x20b52533);
        break; // sh1add
    case 13:
        ROW_RR(0x20b54533);
        break; // sh2add
    case 14:
        ROW_RR(0x20b56533);
        break; // sh3add
    case 15:
        ROW_RR(0x40b57533);
        break; // andn
    case 16:
        ROW_RR(0x40b56533);
        break; // orn
    case 17:
        ROW_RR(0x40b54533);
        break; // xnor
    case 18:
        ROW_RR(0x60051513);
        break; // clz a0, a0
    case 19:
        ROW_RR(0x60151513);
        break; // ctz
    case 20:
        ROW_RR(0x60251513);
        break; // cpop
    case 21:
        ROW_RR(0x0ab54533);
        break; // min
    case 22:
        ROW_RR(0x0ab55533);
        break; // minu
    case 23:
        ROW_RR(0x0ab56533);
        break; // max
    case 24:
        ROW_RR(0x0ab57533);
        break; // maxu
    case 25:
        ROW_RR(0x60b51533);
        break; // rol
    case 26:
        ROW_RR(0x60b55533);
        break; // ror
    case 27:
        ROW_RR(0x69855513);
        break; // rev8
    case 28:
        ROW_RR(0x28755513);
        break; // orc.b
    case 29:
        ROW_RR(0x60451513);
        break; // sext.b
    case 30:
        ROW_RR(0x60551513);
        break; // sext.h
    case 31:
        ROW_RR(0x0ab51533);
        break; // clmul
    case 32:
        ROW_RR(0x0ab53533);
        break; // clmulh
    case 33:
        ROW_RR(0x0ab52533);
        break; // clmulr
    default:
        break;
    }
    return r;
}

// bset a0, a0, a1 (Zbs), as a data word at the global label isa_bset.
static void __attribute__((noinline)) exec_bset(void) {
    register uint32_t ra_ __asm__("a0") = 0x11u;
    register uint32_t rb_ __asm__("a1") = 3u;
    __asm__ volatile(".global isa_bset\nisa_bset:\n.word 0x28b51533"
                     : "+r"(ra_)
                     : "r"(rb_)
                     : "memory");
}
extern char isa_bset[];

static uint32_t row(uint32_t i, uint32_t k) {
    return g_prm[P_ROWS + 4u * i + k];
}

static void put_row(const char *kind, uint32_t i) {
    uint32_t r = exec_op(row(i, 0), row(i, 1), row(i, 2));
    sep_mbx_puts(kind);
    rec_hex("i", i);
    rec_hex("op", row(i, 0));
    rec_hex("r", r);
    rec_end();
}

// ---- PMP ----
static void pmp_read_all(uint32_t *r) {
    r[0] = CSR_READ(pmpaddr0);
    r[1] = CSR_READ(pmpaddr1);
    r[2] = CSR_READ(pmpaddr2);
    r[3] = CSR_READ(pmpaddr3);
    r[4] = CSR_READ(pmpaddr4);
    r[5] = CSR_READ(pmpaddr5);
    r[6] = CSR_READ(pmpaddr6);
    r[7] = CSR_READ(pmpaddr7);
    r[8] = CSR_READ(pmpaddr8);
    r[9] = CSR_READ(pmpaddr9);
    r[10] = CSR_READ(pmpaddr10);
    r[11] = CSR_READ(pmpaddr11);
    r[12] = CSR_READ(pmpaddr12);
    r[13] = CSR_READ(pmpaddr13);
    r[14] = CSR_READ(pmpaddr14);
    r[15] = CSR_READ(pmpaddr15);
}

static void pmp_write(uint32_t i, uint32_t v) {
    switch (i) {
    case 0:
        CSR_WRITE(pmpaddr0, v);
        break;
    case 1:
        CSR_WRITE(pmpaddr1, v);
        break;
    case 2:
        CSR_WRITE(pmpaddr2, v);
        break;
    case 3:
        CSR_WRITE(pmpaddr3, v);
        break;
    case 4:
        CSR_WRITE(pmpaddr4, v);
        break;
    case 5:
        CSR_WRITE(pmpaddr5, v);
        break;
    case 6:
        CSR_WRITE(pmpaddr6, v);
        break;
    case 7:
        CSR_WRITE(pmpaddr7, v);
        break;
    case 8:
        CSR_WRITE(pmpaddr8, v);
        break;
    case 9:
        CSR_WRITE(pmpaddr9, v);
        break;
    case 10:
        CSR_WRITE(pmpaddr10, v);
        break;
    case 11:
        CSR_WRITE(pmpaddr11, v);
        break;
    case 12:
        CSR_WRITE(pmpaddr12, v);
        break;
    case 13:
        CSR_WRITE(pmpaddr13, v);
        break;
    case 14:
        CSR_WRITE(pmpaddr14, v);
        break;
    case 15:
        CSR_WRITE(pmpaddr15, v);
        break;
    default:
        break;
    }
}

static void pmp_cfg_zero(void) {
    CSR_WRITE(pmpcfg0, 0u);
    CSR_WRITE(pmpcfg1, 0u);
    CSR_WRITE(pmpcfg2, 0u);
    CSR_WRITE(pmpcfg3, 0u);
}

static void put_list(const uint32_t *r) {
    static const char *const key[NPMP] = {"r0", "r1", "r2",  "r3",  "r4",  "r5",  "r6",  "r7",
                                          "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15"};
    for (uint32_t i = 0; i < NPMP; i++) {
        rec_hex(key[i], r[i]);
    }
    rec_end();
}

// NAPOT pmpaddr of a naturally aligned 4 KiB region.
static uint32_t napot4k(uint32_t base) {
    return (base >> 2) | 0x1FFu;
}

static uint32_t g_ir[4];

static void __attribute__((noinline)) instret_block(uint32_t *out) {
    // 64 instructions between the two minstret reads, no branch: a dependent
    // chain of 31 instructions, a load-use pair, and 31 independent
    // instructions.
    __asm__ volatile("mv t5, %0\n"
                     ".global isa_r1\n"
                     "isa_r1:\n"
                     "csrr t3, minstret\n"
                     "addi t1, zero, 3\n"
                     ".rept 30\n addi t1, t1, 5\n .endr\n"
                     "lw t2, 0(t5)\n"
                     "addi t2, t2, 1\n"
                     ".rept 31\n xor t6, t1, t2\n .endr\n"
                     ".global isa_r2\n"
                     "isa_r2:\n"
                     "csrr t4, minstret\n"
                     "sw t3, 0(t5)\n"
                     "sw t4, 4(t5)\n"
                     :
                     : "r"(out)
                     : "t1", "t2", "t3", "t4", "t5", "t6", "memory");
}
extern char isa_r1[], isa_r2[];

int main(void) {
    sep_outbound_filter_init();
    sep_mbx_puts("SEP CPU ISA PMP CSR test\n");
    uint32_t nrow = g_prm[P_NROW];
    if (g_prm[P_MAGIC] != PRM_MAGIC || nrow == 0u || nrow > NROW_MAX) {
        sep_mbx_puts("FAIL: parameter block not patched\n");
        return 1;
    }
    sep_mbx_puts("SEED");
    rec_hex("seed", g_prm[P_SEED]);
    rec_end();
    sep_mbx_puts("PARAMS");
    rec_hex("rows", nrow);
    rec_hex("areg", g_prm[P_AREG]);
    rec_hex("dreg", g_prm[P_DREG]);
    rec_hex("ustub", (uint32_t)(uintptr_t)umode_stub);
    rec_end();
    rec_mark(0, "setup");
    CSR_WRITE(mtvec, (uint32_t)(uintptr_t)&trap_entry);

    rec_mark(1, "isa");
    for (uint32_t i = 0; i < nrow; i++) {
        put_row("ROW", i);
    }

    rec_mark(1, "zbs");
    uint32_t n0 = g_ntrap;
    exec_bset();
    sep_mbx_puts("ZBS");
    rec_hex("traps", g_ntrap - n0);
    rec_hex("mcause", g_mcause);
    rec_hex("mepc", g_mepc);
    rec_hex("pc", (uint32_t)(uintptr_t)isa_bset);
    rec_end();
    for (uint32_t c = 0; c < NCTRL; c++) {
        put_row("CROW", g_prm[P_CTRL + c]);
    }

    rec_mark(1, "pmp");
    uint32_t rb[NPMP];
    pmp_cfg_zero();
    for (uint32_t i = 0; i < NPMP; i++) {
        pmp_write(i, g_prm[P_PMP + i]);
    }
    pmp_read_all(rb);
    sep_mbx_puts("PMP0");
    put_list(rb);
    for (uint32_t i = 0; i < NPMP; i++) {
        pmp_write(i, ~g_prm[P_PMP + i]);
        pmp_read_all(rb);
        sep_mbx_puts("PMPC");
        rec_hex("i", i);
        put_list(rb);
    }
    n0 = g_ntrap;
    uint32_t msec = CSR_READ(0x747);
    sep_mbx_puts("MSECCFG");
    rec_hex("v", msec);
    rec_hex("traps", g_ntrap - n0);
    rec_end();

    rec_mark(1, "mrac");
    uint32_t areg = g_prm[P_AREG];
    uint32_t dreg = g_prm[P_DREG];
    uint32_t upage = (uint32_t)(uintptr_t)umode_stub;
    for (uint32_t j = 0; j < NMRAC; j++) {
        uint32_t aw = g_prm[P_AW + j];
        uint32_t dw = g_prm[P_DW + j];
        CSR_WRITE(0x7C0, g_prm[P_MRAC + j]);
        uint32_t mrb = CSR_READ(0x7C0);
        *(volatile uint32_t *)areg = aw;
        *(volatile uint32_t *)dreg = dw;
        __asm__ volatile("fence" ::: "memory");
        pmp_cfg_zero();
        CSR_WRITE(pmpaddr0, napot4k(upage));
        CSR_WRITE(pmpaddr1, napot4k(areg));
        CSR_WRITE(pmpaddr2, napot4k(dreg));
        CSR_WRITE(pmpcfg0,
                  (PMP_NAPOT << 16) | ((PMP_NAPOT | PMP_R) << 8) | (PMP_NAPOT | PMP_R | PMP_X));
        n0 = g_ntrap;
        g_mcause = 0u;
        g_t3 = 0u;
        g_t4 = 0u;
        run_user(areg, dreg);
        uint32_t nt = g_ntrap - n0;
        pmp_cfg_zero();
        CSR_WRITE(0x7C0, MRAC_BOOT);
        sep_mbx_puts("MRAC");
        rec_hex("j", j);
        rec_hex("v", g_prm[P_MRAC + j]);
        rec_hex("rb", mrb);
        rec_hex("traps", nt);
        rec_hex("mcause", g_mcause);
        rec_hex("mepc", g_mepc);
        rec_hex("rok", g_t3);
        rec_hex("rden", g_t4);
        rec_end();
    }

    rec_mark(1, "trace");
    instret_block(g_ir);
    sep_mbx_puts("INSTRET");
    rec_hex("r1", g_ir[0]);
    rec_hex("r2", g_ir[1]);
    rec_hex("pc1", (uint32_t)(uintptr_t)isa_r1);
    rec_hex("pc2", (uint32_t)(uintptr_t)isa_r2);
    rec_end();

    rec_mark(0, "end");
    sep_mbx_puts("PASS: CPU ISA PMP CSR\n");
    return 0;
}
