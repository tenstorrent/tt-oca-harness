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

#define MARK_LSU_WR 0xA11A1036u
#define MARK_LSU_RD 0xA11A0317u
#define MARK_BASE_LIVE 0xB15E0001u
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

    if (errors == 0) {
        sep_mbx_puts("PASS: CPU IFU+LSU local-alias-remap verified\n");
    }
    return errors;
}
