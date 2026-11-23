// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP CPU IFU/LSU local alias remap test. A CPU access inside the local alias
// window is remapped to (addr - (window base - SRAM base)); an access outside
// the window passes through unchanged. The window base is programmable and its
// span is fixed (hw/sys/sep/doc/memory_map.adoc); the inbound region size does
// not size this window, so the test does not program it. The separate
// alias-table remapper used by other masters is out of scope.
//
// The test must run on the real CPU: the no_cpu AXI splice sits after the
// remap, so a no_cpu driver would bypass it.
//
// Checks (main() returns the error count; startup/crt0.s emits the PASS/FAIL
// magic):
//   CHK-CSR       The window base CSR takes a non-reset value, then is restored.
//   CHK-LSU-WR    An LSU write through the alias lands at the SRAM target.
//   CHK-LSU-RD    An LSU read through the alias returns the SRAM target.
//   CHK-BASE-LIVE With a non-reset base programmed, a write through that window
//                 lands at the SRAM target, so the remapper uses the CSR.
//   CHK-IFU       A function written to SRAM and called through the alias
//                 returns its expected value, so IFU fetches are remapped too.
//
// U-mode leg: the firmware enters user mode (MPP = 0, mret) at a stub alone in
// one 4 KiB ICCM page. The stub loads UMODE_PHYS, stores a marker to it and
// exits with ecall. PMP entry 0 grants R|X on the stub page and entry 1 grants
// R|W on the SRAM page that holds UMODE_PHYS; no other entry is written.
// Machine mode stores the preset marker to UMODE_PHYS before the leg and reads
// it back after; no other code touches that word. The leg prints one record,
// which the host grades:
//   UMODE-LEG mcause= mpp= mepc= ustub= ntrap= uaddr= pre= load= st= rb=
// The image fails unless mcause is 8 (ecall from U-mode), the trapped MPP is
// 0, one trap was taken, load equals pre and rb equals st.

#include <stdint.h>

#include "sep.h"
#include "sep_outbound_filter.h"
#include "sep_mailbox.h"

#define SEP_LOCAL_BASE_ADDR_REG SEP_TOP_SEP_CPU_CTRL_SEP_LOCAL_BASE_ADDR_BASE_ADDR
#define WINDOW_BASE SEP_CPU_CTRL__SEP_LOCAL_BASE_ADDR_reset
// Distinct probe value, used only to prove the base CSR is writable at all.
#define ALT_WINDOW_BASE 0xE0000000u
#define TARGET_BASE SEP_TOP_SEP_SRAM_BASE_ADDR
#define ADJUST (WINDOW_BASE - TARGET_BASE)
#define ADJUST_ALT (ALT_WINDOW_BASE - TARGET_BASE)

#define SRAM_PHYS TARGET_BASE
#define ALIAS_FOR(phys) ((phys) + ADJUST) // physical target addr -> its alias addr
#define ALIAS_ALT(phys) ((phys) + ADJUST_ALT)

// SRAM layout for this test (within the SRAM responder, no overlap).
#define IFU_FN_PHYS (SRAM_PHYS + 0x000u) // 2 instr words live here
#define LSU_WR_PHYS (SRAM_PHYS + 0x308u)
#define LSU_RD_PHYS (SRAM_PHYS + 0x310u)
#define LSU_BASE_PHYS (SRAM_PHYS + 0x318u)

#define UMODE_PHYS (SRAM_PHYS + 0x320u)

#define MARK_LSU_WR 0xA11A1036u
#define MARK_LSU_RD 0xA11A0317u
#define MARK_BASE_LIVE 0xB15E0001u
#define MARK_UMODE_PRE 0x05E40001u
#define MARK_UMODE_ST 0x05E40002u
#define IFU_RET_VAL 42

// Encodings of "li a0, 42; ret": a leaf function that returns IFU_RET_VAL.
#define INSN_LI_A0_42 0x02A00513u
#define INSN_RET 0x00008067u

static inline void wr32(uint32_t addr, uint32_t v) {
    *(volatile uint32_t *)addr = v;
}
static inline uint32_t rd32(uint32_t addr) {
    return *(volatile uint32_t *)addr;
}

typedef int (*fn_t)(void);

#define MCAUSE_ECALL_U 8u
#define MSTATUS_MPP 0x1800u
#define PMP_R 0x01u
#define PMP_W 0x02u
#define PMP_X 0x04u
#define PMP_NAPOT 0x18u

#define CSR_READ(n) \
    ({ \
        uint32_t v_; \
        __asm__ volatile("csrr %0, " #n : "=r"(v_)::"memory"); \
        v_; \
    })
#define CSR_WRITE(n, v) __asm__ volatile("csrw " #n ", %0" ::"r"(v) : "memory")

// Trap entry for the U-mode leg: save the caller-saved registers, call
// trap_c, mret.
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

// User-mode stub, alone in one 4 KiB ICCM page. run_user(addr, marker) enters
// user mode at umode_stub with s2 = addr and s3 = marker. The stub loads the
// word at addr into t3, stores the marker to addr and exits with ecall. The
// trap handler returns to umode_return in machine mode.
__asm__(".section .text.umode,\"ax\",@progbits\n"
        ".balign 4096\n"
        ".global umode_stub\n"
        "umode_stub:\n"
        "lw t3, 0(s2)\n"
        "sw s3, 0(s2)\n"
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
void run_user(uint32_t addr, uint32_t marker);
extern char umode_stub[];
extern char umode_return[];

volatile uint32_t g_user_sp;
static volatile uint32_t g_ntrap;
static volatile uint32_t g_mcause, g_mepc, g_mpp, g_t3;

// Every trap taken while mtvec points at trap_entry ends the leg: the handler
// records it and returns to umode_return in machine mode.
void trap_c(uint32_t *frame) {
    g_mcause = CSR_READ(mcause);
    g_mepc = CSR_READ(mepc);
    g_mpp = CSR_READ(mstatus) & MSTATUS_MPP;
    g_t3 = frame[4];
    g_ntrap = g_ntrap + 1u;
    CSR_WRITE(mepc, (uint32_t)(uintptr_t)umode_return);
    __asm__ volatile("csrs mstatus, %0" ::"r"(MSTATUS_MPP) : "memory");
}

// NAPOT pmpaddr of a naturally aligned 4 KiB region.
static uint32_t napot4k(uint32_t base) {
    return ((base & ~0xFFFu) >> 2) | 0x1FFu;
}

static void put_field(const char *key, uint32_t v) {
    sep_mbx_putc(' ');
    sep_mbx_puts(key);
    sep_mbx_putc('=');
    sep_mbx_puthex(v);
}

// One load and one store to UMODE_PHYS from user mode. Returns the error count.
static int umode_leg(void) {
    uint32_t ustub = (uint32_t)(uintptr_t)umode_stub;
    uint32_t mtvec_saved = CSR_READ(mtvec);
    wr32(UMODE_PHYS, MARK_UMODE_PRE);
    __asm__ volatile("fence" ::: "memory");
    CSR_WRITE(pmpcfg0, 0u);
    CSR_WRITE(pmpaddr0, napot4k(ustub));
    CSR_WRITE(pmpaddr1, napot4k(UMODE_PHYS));
    CSR_WRITE(pmpcfg0, ((PMP_NAPOT | PMP_R | PMP_W) << 8) | (PMP_NAPOT | PMP_R | PMP_X));
    CSR_WRITE(mtvec, (uint32_t)(uintptr_t)&trap_entry);
    g_ntrap = 0u;
    g_mcause = 0u;
    g_mpp = MSTATUS_MPP;
    g_t3 = 0u;
    run_user(UMODE_PHYS, MARK_UMODE_ST);
    CSR_WRITE(mtvec, mtvec_saved);
    CSR_WRITE(pmpcfg0, 0u);
    __asm__ volatile("fence" ::: "memory");
    uint32_t rb = rd32(UMODE_PHYS);

    sep_mbx_puts("UMODE-LEG");
    put_field("mcause", g_mcause);
    put_field("mpp", g_mpp);
    put_field("mepc", g_mepc);
    put_field("ustub", ustub);
    put_field("ntrap", g_ntrap);
    put_field("uaddr", UMODE_PHYS);
    put_field("pre", MARK_UMODE_PRE);
    put_field("load", g_t3);
    put_field("st", MARK_UMODE_ST);
    put_field("rb", rb);
    sep_mbx_putc('\n');

    if (g_ntrap != 1u || g_mcause != MCAUSE_ECALL_U || g_mpp != 0u || g_t3 != MARK_UMODE_PRE ||
        rb != MARK_UMODE_ST) {
        sep_mbx_puts("FAIL: U-mode leg did not load the preset, store the marker and ecall\n");
        return 1;
    }
    return 0;
}

int main(void) {
    int errors = 0;

    sep_outbound_filter_init();
    sep_mbx_puts("SEP CPU IFU/LSU alias-remap test\n");

    // CHK-CSR: probe the window base CSR with a non-reset value, then restore
    // the operating base for the alias accesses below. The operating base is
    // the reset value, so writing only that would read back the same from a
    // read-only or disconnected CSR.
    wr32(SEP_LOCAL_BASE_ADDR_REG, ALT_WINDOW_BASE);
    uint32_t alt_rb = rd32(SEP_LOCAL_BASE_ADDR_REG);
    wr32(SEP_LOCAL_BASE_ADDR_REG, WINDOW_BASE);
    uint32_t base_rb = rd32(SEP_LOCAL_BASE_ADDR_REG);
    if (alt_rb != ALT_WINDOW_BASE) {
        sep_mbx_puts("FAIL: alias CSR is not writable, alt readback=");
        sep_mbx_puthex(alt_rb);
        sep_mbx_putc('\n');
        errors++;
    } else if (base_rb != WINDOW_BASE) {
        sep_mbx_puts("FAIL: alias CSR readback base=");
        sep_mbx_puthex(base_rb);
        sep_mbx_putc('\n');
        errors++;
    } else {
        sep_mbx_puts("CHK-CSR PASS: SEP_LOCAL_BASE writable (probed 0xe0000000), restored to "
                     "0xd0000000 (fixed 768MiB window -> 0x10000000)\n");
    }

    // CHK-LSU-WR: write THROUGH the alias, read back at the physical target.
    wr32(ALIAS_FOR(LSU_WR_PHYS), MARK_LSU_WR);
    uint32_t wr_seen = rd32(LSU_WR_PHYS);
    if (wr_seen != MARK_LSU_WR) {
        sep_mbx_puts("FAIL: LSU alias write not at phys target, got ");
        sep_mbx_puthex(wr_seen);
        sep_mbx_putc('\n');
        errors++;
    } else {
        sep_mbx_puts("CHK-LSU-WR PASS: write@0xd0000308 -> phys 0x10000308 == marker\n");
    }

    // CHK-LSU-RD: write at the physical target, read THROUGH the alias.
    wr32(LSU_RD_PHYS, MARK_LSU_RD);
    uint32_t rd_seen = rd32(ALIAS_FOR(LSU_RD_PHYS));
    if (rd_seen != MARK_LSU_RD) {
        sep_mbx_puts("FAIL: LSU alias read != phys target, got ");
        sep_mbx_puthex(rd_seen);
        sep_mbx_putc('\n');
        errors++;
    } else {
        sep_mbx_puts("CHK-LSU-RD PASS: read@0xd0000310 -> phys 0x10000310 == marker\n");
    }

    // CHK-BASE-LIVE: with the alternate base programmed, a write through that
    // window must land in SRAM. A remapper hardwired at the operating base would
    // send it elsewhere.
    wr32(SEP_LOCAL_BASE_ADDR_REG, ALT_WINDOW_BASE);
    wr32(ALIAS_ALT(LSU_BASE_PHYS), MARK_BASE_LIVE);
    uint32_t base_seen = rd32(LSU_BASE_PHYS);
    wr32(SEP_LOCAL_BASE_ADDR_REG, WINDOW_BASE);
    if (base_seen != MARK_BASE_LIVE) {
        sep_mbx_puts("FAIL: alias remapper ignored programmed base, phys got ");
        sep_mbx_puthex(base_seen);
        sep_mbx_putc('\n');
        errors++;
    } else {
        sep_mbx_puts("CHK-BASE-LIVE PASS: write@0xe0000318 with base 0xe0000000 -> "
                     "phys 0x10000318 == marker (remapper consumes SEP_LOCAL_BASE)\n");
    }

    // CHK-IFU: place a leaf function in SRAM, then CALL it through the alias so the
    // IFU fetch is remapped. fence.i flushes any stale prefetch before the fetch.
    wr32(IFU_FN_PHYS + 0, INSN_LI_A0_42);
    wr32(IFU_FN_PHYS + 4, INSN_RET);
    __asm__ volatile("fence rw, rw" ::: "memory");
    __asm__ volatile(".word 0x0000100f" ::: "memory"); // fence.i (sync IFU)
    fn_t fn = (fn_t)ALIAS_FOR(IFU_FN_PHYS);
    int ifu_ret = fn();
    if (ifu_ret != IFU_RET_VAL) {
        sep_mbx_puts("FAIL: IFU alias fetch returned ");
        sep_mbx_puthex((uint32_t)ifu_ret);
        sep_mbx_putc('\n');
        errors++;
    } else {
        sep_mbx_puts("CHK-IFU PASS: call@0xd0000000 -> IFU fetch remapped to "
                     "phys 0x10000000 -> returned 42\n");
    }

    errors += umode_leg();

    if (errors == 0) {
        sep_mbx_puts("PASS: CPU IFU+LSU local-alias-remap verified\n");
    }
    return errors;
}
