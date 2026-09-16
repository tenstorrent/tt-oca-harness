// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP CPU IFU/LSU local-alias-remap firmware test (OSS port of the reference suite
// sep_cpu_ifu_lsu_alias_remap_matrix_test). Proves the CPU-side local alias remap
// (hw/sys/sep/rtl/sep_cpu.sv u_lsu/u_ifu/u_dbg axi_window_remap): a CPU fabric
// access in [SEP_LOCAL_BASE, SEP_LOCAL_BASE+SEP_LOCAL_ALIAS_REGION_SIZE) is remapped
// to (addr - (SEP_LOCAL_BASE - SEP_LOCAL_ALIAS_REGION_BASE)), and an access outside
// the window passes through unchanged.
//
// The alias window is a FIXED 768 MiB (hw/sys/sep/doc/memory_map.adoc):
// SEP_LOCAL_BASE_ADDR resets to 0xD000_0000, the span is 0x3000_0000
// (REGION_SIZE does not size this window), and the target is 0x1000_0000.
// So the
// alias 0xD000_0000 maps to physical 0x1000_0000 (SEP SRAM). The firmware uses
// 0xD000_xxxx (NOT the 0xC000_03xx the reference suite VIP drives on the raw pre-remap port):
// a real CPU access to 0xC000_03xx would hit ICCM (TCM, internal) and never reach
// the remapped fabric path, whereas 0xD000_xxxx routes through the IFU/LSU remap.
//
// Scope delta vs the reference suite: SEP_REGION_SIZE (0x10A3_00D0) sizes the inbound/SMU window
// only, NOT this CPU alias window, so it is not programmed here; the
// CPU window size is the fixed 768 MiB alias span in memory_map.adoc.
//
// This must be a CPU-firmware (real IFU/LSU) test: the OSS no_cpu AXI splice is
// POST-remap, so a no_cpu driver would bypass the remap entirely.
//
// Scope delta vs the reference suite: the reference suite scenario also pokes ALIAS_ENTRY0_*
// (0x10A1_00xx); those program a SEPARATE alias-table remapper (for other masters), NOT the CPU
// u_ifu/u_lsu_local_alias_remap instances this test targets, so they
// are out of scope here.
//
// Checks (firmware-self-checking; start.S emits PASS/FAIL magic from main's rc):
//   CHK-CSR    SEP_LOCAL_BASE probe/restore (REGION_SIZE is not programmed).
//   CHK-LSU-WR LSU write via the alias lands at the physical SRAM target
//              (write alias 0xD000_0308 -> read direct 0x1000_0308 == marker).
//   CHK-LSU-RD LSU read via the alias returns the physical SRAM target
//              (write direct 0x1000_0310 -> read alias 0xD000_0310 == marker).
//   CHK-BASE-LIVE LSU write through a non-reset base (0xE000_0318) lands at
//              phys 0x1000_0318. A remapper stuck at the operating base fails.
//   CHK-IFU    IFU fetch+execute through the alias: write a tiny function
//              ("li a0,42; ret") to SRAM 0x1000_0000, then CALL it via the alias
//              0xD000_0000 -> IFU fetch remaps to 0x1000_0000 -> returns 42.
//              (Stronger than the reference suite, which drives a synthetic write on the IFU port
//              rather than a real instruction fetch through the remap.)

#include <stdint.h>

#include "sep.h"
#include "sep_outbound_filter.h"
#include "sep_mailbox.h"

#define SEP_LOCAL_BASE_ADDR_REG OCH_SEP_TOP_SEP_CPU_CTRL_SEP_LOCAL_BASE_ADDR_BASE_ADDR
#define WINDOW_BASE SEP_CPU_CTRL__SEP_LOCAL_BASE_ADDR_reset
// Distinct probe value, used only to prove the base CSR is writable at all.
#define ALT_WINDOW_BASE 0xE0000000u
#define TARGET_BASE OCH_SEP_TOP_SEP_SRAM_BASE_ADDR
#define ADJUST (WINDOW_BASE - TARGET_BASE) // 0xC000_0000 = base - target
#define ADJUST_ALT (ALT_WINDOW_BASE - TARGET_BASE)

#define SRAM_PHYS TARGET_BASE             // SEP SRAM base
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

// "li a0,42 ; ret" (verified encodings) -- a leaf function returning 42.
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

    // CHK-CSR: program the alias window base and read it back. The base
    // resets to 0xD000_0000 and the window size is the fixed
    // 768 MiB alias span in memory_map.adoc (0x3000_0000), so only the base
    // CSR is programmable; REGION_SIZE (0x10A3_00D0) does not size this window and
    // is not touched here.
    // Write a value that is NOT the reset value first. Writing only WINDOW_BASE
    // and reading it back proves nothing about programmability: 0xD000_0000 is
    // this field's own reset value, so the register could be read-only, or the
    // CSR could be disconnected from the remapper entirely, and the readback
    // would still match. Probing with a distinct value makes the write half of
    // this check falsifiable; the alias accesses below then run at the restored
    // operating base.
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
    // window must land at physical SRAM. A remapper hardwired at the operating
    // base (0xD000_0000) would map 0xE000_0318 to 0x2000_0318, not 0x1000_0318.
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
    fn_t fn = (fn_t)ALIAS_FOR(IFU_FN_PHYS);            // 0xD0000000
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
