/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* OCH SEP Boot ROM
 *
 * Code executes from Boot ROM (0x10040000) via the IFU AXI demux.
 * Data (.rodata/.data/.bss/stack) resides in DCCM (0xC0040000).
 * PASS/FAIL signalled via STDOUT mailbox (0x80000000).
 *
 * Build assumes RV32IM (no compressed — .option norvc).
 */

    .option norvc
    .section .text.init, "ax", @progbits
    .globl _start
    .type  _start, @function

#include "sep_addr.h"

/* SEP firmware status mailbox observed by the DV harness. */
.equ SEP_STDOUT_MBX, 0x80000000
.equ SEP_FW_MAGIC0,  0xA5A55A5A
.equ SEP_FW_PASS,    0xCAFEBABE
.equ SEP_FW_FAIL,    0xDEADBEEF
.equ SEP_STAT_TAG,   0x53544154      /* 'STAT' (legacy, kept for reference) */
.equ SEP_COLD_SCRATCH_1, OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(1)

/* DCCM base from EL2 snapshot: sadr=0xC0040000, size=128KiB → top=0xC0060000.
 * (Actual stack pointer uses __stack_top from the linker script.) */
.equ DCCM_BASE,      0xC0040000
.equ DCCM_STACK_TOP, 0xC0060000

#ifndef DCCM_SCRUB_BYTES
#define DCCM_SCRUB_BYTES 0x20000   /* 128KiB = full DCCM (snapshot dccm_size) */
#endif

#ifndef PMP_ENABLE
#define PMP_ENABLE 1
#endif

#ifndef PMP_LOCK
#define PMP_LOCK 0
#endif

/* SEP scratch registers (warm reset retention).
 * warm_scratch[0] survives warm reset (wdt_rst_ni only resets CPU).
 * cold_scratch[0] is cleared on any reset.
 */
.equ SEP_WARM_SCRATCH_0, OCH_SEP_TOP_SEP_SCRATCH_WARM_SCRATCH_BASE_ADDR(0)
.equ SEP_COLD_SCRATCH_0, OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(0)

/* SRAM address range for warm handler jump validation.
 * BL1 executes from SRAM after handoff, so warm reset handler lives there. */
.equ WARM_HANDLER_RANGE_BASE,  OCH_SEP_TOP_SEP_SRAM_BASE_ADDR
.equ WARM_HANDLER_RANGE_END,   OCH_SEP_TOP_SEP_BOOT_ROM_BASE_ADDR

/* MEM_REPAIR boot gate. Mirrors include/sep_smc_interface.h -- the C side owns
 * these numbers, so they must be changed in both places together. Kept as .equ
 * rather than pulled from a header because that header is C, not assembly. */
.equ SEP_SMC_GLOBAL_BASE,      0x40000000
.equ SMC_DFX_CTRL_STATUS_SMU,  SEP_SMC_GLOBAL_BASE + 0xF800
/* SMC scratch registers are 64-bit; index 10 is the agreed MBIST/MEM_REPAIR
 * failure slot, read back by the debugger and by DV. */
.equ SMC_SCRATCH_MBIST_FAIL,   SEP_SMC_GLOBAL_BASE + 0x10100 + (10 * 8)
.equ DFT_MEM_REPAIR_SUCCESS,   (1 << 1)

/* MEM_REPAIR bypass fuse: STATUS_RPT bit 2.
 *
 * Fail-closed: the bit is 0 on an unblown part, and 0 means hang. Permitting a
 * boot after a repair failure therefore requires deliberately blowing a fuse; it
 * cannot be arranged at run time. That is the whole point of reading a fuse here
 * instead of the SMC strap the C version used -- a strap is a pin, so anyone able
 * to hold it could switch this gate off on a production part.
 *
 * NOTE (A32): bit 2 currently falls inside `reserved[31:2]` in
 * regs/blocks/sep_efuse_map/sep_efuse_map.rdl:806, so this is an undeclared use
 * of a reserved bit. The reference does exactly the same thing -- its own RDL
 * also leaves the bit reserved while its vector.S reads it -- and the OCH eFuse
 * spec does not allocate it either. A32 is to split that field into
 * `mem_repair_ignore[2:2]` so the allocation is documented rather than merely
 * relied upon. The register's existing `sw = r` / `hw = rw` access is already
 * correct for a bypass: software cannot assert it, only the fuse can.
 */
.equ SEP_EFUSE_STATUS_RPT,     OCH_SEP_TOP_SEP_EFUSE_MAP_STATUS_RPT_BASE_ADDR
.equ STATUS_RPT_MEM_REPAIR_IGNORE, (1 << 2)

_start:
    /* Multi-hart safety: only hart0 proceeds (others park). */
    csrr    t0, mhartid
    bnez    t0, secondary_hart

    /* Set trap vector early (before any MMIO access, for safety). */
    la      t0, trap_vector
    csrw    mtvec, t0

    /* Configure VeeR EL2 MRAC before warm reset check so that the
     * warm_scratch read at 0x1080xxxx (region 1) gets correct
     * memory attributes (side-effect, non-cacheable). */
    li      t0, 0xAAAAAAA8
    csrw    0x7C0, t0

    /* ── V2: Warm reset detection ──────────────────────────────────
     *
     * On warm reset (WDT bark → wdt_rst_ni low):
     *   - CPU is reset (sep_cpu_reset_n = sep_reset_n & wdt_rst_ni)
     *   - ICCM/DCCM content preserved (not reset)
     *   - sep_scratch_warm_scratch[] preserved (not reset)
     *   - All CPU CSRs reset to defaults
     *
     * BL1 writes its re-entry address to warm_scratch[0] before enabling
     * the WDT.  On warm reset, ROM reads this and jumps back to BL1.
     *
     * Protocol:
     *   1. Read warm_scratch[0]
     *   2. If zero → cold boot
     *   3. If non-zero: range check against
     *      [WARM_HANDLER_RANGE_BASE, WARM_HANDLER_RANGE_END) = SEP SRAM
     *   4. If valid: poison scratch (write 0), jump to handler
     *   5. If invalid: hang
     *   The cold path poisons with -1, deliberately out of range, so an
     *   unarmed warm reset lands on step 5 rather than step 2.
     *
     * This check happens BEFORE touching DCCM (sp/gp/scrub/.data/.bss)
     * to preserve BL1's runtime state across warm reset.
     */
    li      t0, SEP_WARM_SCRATCH_0
    lw      t1, 0(t0)              /* t1 = warm handler address */
    beqz    t1, cold_boot          /* zero → cold boot */

    /* Range check: WARM_HANDLER_RANGE_BASE <= handler < WARM_HANDLER_RANGE_END */
    li      t2, WARM_HANDLER_RANGE_BASE
    bltu    t1, t2, warm_reset_hang /* handler < range base → invalid → hang */
    li      t2, WARM_HANDLER_RANGE_END
    bgeu    t1, t2, warm_reset_hang /* handler >= range end → invalid → hang */

    /* Valid warm handler found.  Announce the decision BEFORE transferring
     * control: once we jr, the ROM never runs again, so this store is the only
     * record that the ROM took the warm path rather than falling into cold_boot.
     * STATUS_ENCODE(STATUS_TYPE_INFO, SEP_MSG_WARM_RESET_JUMP)
     * = (0x01 << 24) | (0x01 << 16) | 0x68 = 0x01010068
     * Written with t3/t4 so t0 (warm scratch base) and t1 (handler address)
     * stay live for the poison and the jump below. */
    li      t3, SEP_COLD_SCRATCH_1
    li      t4, 0x01010068
    sw      t4, 0(t3)

    /* Poison scratch to prevent re-entry. */
    sw      zero, 0(t0)

    /* Jump to warm reset handler.  BL1 is already in SRAM and will
     * set up its own sp/mtvec/PMP as needed. */
    jr      t1

    /* Invalid warm handler address — hang.
     * Do not fall through to cold boot; an invalid handler pointer
     * may indicate corruption or attack.
     * STATUS_ENCODE(STATUS_TYPE_ERROR, SEP_MSG_WARM_RESET_HANG)
     * = (0x0f << 24) | (0x01 << 16) | 0x69 = 0x0f010069
     * Stored once, outside the spin loop: a hang with no status left the
     * two arms indistinguishable from the outside (both are just a stopped
     * core), so this is what makes the reject observable. */
warm_reset_hang:
    li      t0, SEP_COLD_SCRATCH_1
    li      t1, 0x0f010069
    sw      t1, 0(t0)
3:  wfi
    j       3b
    /* ── end warm reset ─────────────────────────────────────────── */

cold_boot:
    /* Poison warm_scratch[0] with an out-of-range value rather than 0.
     * A later warm reset arriving with no handler armed then fails the range
     * check and hangs with SEP_MSG_WARM_RESET_HANG, instead of taking the
     * beqz early-out and silently cold booting -- for a repeating watchdog
     * that would be a boot loop with no diagnosable stop. This matches the
     * philosophy already stated on the invalid-handler path below: an
     * unexpected handler value may indicate corruption or attack.
     *
     * The warm path keeps its own zero poison; that one exists to prevent
     * handler re-entry and must stay. Neither value alone is the stronger
     * choice on both paths. */
    li      t0, SEP_WARM_SCRATCH_0
    li      t1, -1
    sw      t1, 0(t0)

    /* Set stack near top of DCCM (from linker script). */
    la      sp, __stack_top

    /* Set global pointer for small-data accesses (gp-relative). */
    la      gp, __global_pointer$

    /* Configure outbound filter to allow mailbox writes at 0x8000_0000.
     *
     * The SEP outbound filter blocks ALL AXI egress transactions by default.
     * Without this, mailbox writes (PASS/FAIL signal, status, printf) are
     * silently dropped and the UVM testbench never sees fw_done.
     *
     * Filter 0 registers (OUTBOUND_FILTER_CTRL_0 from sep_addr.h):
     *   START_ADDR (64-bit) = 0x0000_0000_8000_0000
     *   END_ADDR   (64-bit) = 0x0000_0000_8000_0003
     *   CONFIG     (64-bit) = 0x0000_0001_0100_0013
     *          (read_en | write_en | addr_mode | allow_burst)
     * CONFIG must be written LAST so address range is set before enable.
     */
    li      t0, OCH_SEP_TOP_OUTBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR(0)
    li      t1, 0x80000000
    sw      t1, 0(t0)           /* start_addr[31:0] */
    sw      zero, 4(t0)         /* start_addr[63:32] = 0 */

    li      t0, OCH_SEP_TOP_OUTBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR(0)
    li      t1, 0x80000003
    sw      t1, 0(t0)           /* end_addr[31:0] */
    sw      zero, 4(t0)         /* end_addr[63:32] = 0 */

    fence   w, w                /* ensure START/END committed before CONFIG */

    li      t0, OCH_SEP_TOP_OUTBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(0)
    li      t1, 0x01000013
    sw      t1, 0(t0)           /* config[31:0] */
    li      t1, 0x00000001
    sw      t1, 4(t0)           /* config[63:32] */

    /* Status: entered _start (hart0) → scratch[1]
     * STATUS_ENCODE(STATUS_TYPE_DEBUG, SEP_MSG_BOOTROM_START)
     * = (0x80 << 24) | (0x01 << 16) | 0x44 = 0x80010044 */
    li      t0, SEP_COLD_SCRATCH_1
    li      t1, 0x80010044
    sw      t1, 0(t0)

    /* Disable interrupts during early init (defensive). */
    csrw    mie, zero
    csrci   mstatus, 0x8        /* clear MIE */

    /* PMP init (Phase 1 / M3):
     * Program a simple region-based policy (NAPOT).
     *
     * Optional knobs:
     * - PMP_ENABLE=0: skip PMP programming
     * - PMP_LOCK=1: set L bit on programmed entries (locked until reset)
     *
     * Regions:
     * - entry0: Boot ROM  0x1004_0000 .. 0x1004_FFFF (64KiB)  : R-X
     * - entry1: DCCM      0xC004_0000 .. 0xC005_FFFF (128KiB) : RW-
     * - entry2: MBX       0x8000_0000 .. 0x8000_0FFF (4KiB)   : RW-
     * - entry3: SRAM      0x1000_0000 .. 0x1003_FFFF (256KiB) : RWX (BL1 code+data)
     * - entry4: Periph    0x1090_0000 .. 0x10BF_FFFF (3MiB)   : RW-
     * - entry5: ICCM      0xC000_0000 .. 0xC003_FFFF (256KiB) : RWX (BL1)
     * - entry6: SMC MMIO  0xC000_0000 .. 0xCFFF_FFFF (256MiB) : RW-
     */
#if PMP_ENABLE
    /* Boot ROM 64KiB @ 0x1004_0000: pmpaddr0 = (0x10040000>>2) | ((64KiB/2)-1) = 0x0401_7FFF */
    li      t0, 0x04017fff
    csrw    pmpaddr0, t0
    /* DCCM 128KiB @ 0xC004_0000: pmpaddr1 = (0xC0040000>>2) | ((128KiB>>3)-1) = 0x3001_3FFF */
    li      t0, 0x30013fff
    csrw    pmpaddr1, t0
    /* MBX 4KiB @ 0x8000_0000: pmpaddr2 = (0x80000000>>2) | ((4KiB/2)-1) = 0x2000_07FF */
    li      t0, 0x200007ff
    csrw    pmpaddr2, t0
    /* SRAM 256KiB @ 0x1000_0000: pmpaddr3 = (0x10000000>>2) | ((256KiB/2)-1) = 0x0401_FFFF */
    li      t0, 0x0401ffff
    csrw    pmpaddr3, t0
    /* Periph 4MiB @ 0x1080_0000: pmpaddr4 = (0x10800000>>2) | ((4MiB/2)-1) = 0x0421_FFFF */
    li      t0, 0x0421ffff
    csrw    pmpaddr4, t0
    /* ICCM 256KiB @ 0xC000_0000: pmpaddr5 = (0xC0000000>>2) | ((256KiB>>3)-1) = 0x3000_7FFF */
    li      t0, 0x30007fff
    csrw    pmpaddr5, t0
    /* SMC MMIO 256MiB @ 0xC000_0000: pmpaddr6 = (0xC0000000>>2) | ((256MiB>>3)-1) = 0x31FF_FFFF */
    li      t0, 0x31ffffff
    csrw    pmpaddr6, t0

    /* pmpcfg0 bytes: [entry3][entry2][entry1][entry0]
     * - NAPOT=0x18; R=0x1; W=0x2; X=0x4; L=0x80
     * - entry0 ROM  R-X: 0x18|0x05 = 0x1D
     * - entry1 DCCM RW-: 0x18|0x03 = 0x1B
     * - entry2 MBX  RW-: 0x18|0x03 = 0x1B
     * - entry3 SRAM RWX: 0x18|0x07 = 0x1F
     */
#if PMP_LOCK
    li      t0, 0x9f9b9b9d      /* set L bit on entries 0..3 */
#else
    li      t0, 0x1f1b1b1d
#endif
    csrw    pmpcfg0, t0

    /* pmpcfg1 bytes: [entry7][entry6][entry5][entry4]
     * - entry4 Periph RW-: 0x18|0x03 = 0x1B
     * - entry5 ICCM   RWX: 0x18|0x07 = 0x1F
     * - entry6 SMC    RW-: 0x18|0x03 = 0x1B
     * - entry7: unused (0x00)
     */
#if PMP_LOCK
    li      t0, 0x009b9f9b      /* set L bit on entries 4..6 */
#else
    li      t0, 0x001b1f1b
#endif
    csrw    pmpcfg1, t0

    /* Status: PMP configured → scratch[1]
     * STATUS_ENCODE(STATUS_TYPE_DEBUG, SEP_MSG_BOOTROM_PRESTART_DONE)
     * = (0x80 << 24) | (0x01 << 16) | 0x56 = 0x80010056 */
    li      t0, SEP_COLD_SCRATCH_1
    li      t1, 0x80010056
    sw      t1, 0(t0)
#endif /* PMP_ENABLE */

    /* ── MEM_REPAIR boot gate ─────────────────────────────────────────────
     *
     * On-chip SRAMs carry redundancy; MBIST finds faulty cells at reset and the
     * repair logic swaps in spares. DFX_CTRL_STATUS_SMU.mem_repair_success says
     * whether that worked. If it did not, the memories may return wrong data,
     * and the ROM's entire job is comparing digests and deciding what to trust:
     * a single flipped cell can make const_time_eq() agree, or corrupt a derived
     * key, with nothing reporting an error. So a repair failure is fatal unless a
     * fuse says otherwise.
     *
     * WHY IT SITS HERE, IN ASSEMBLY. This runs before the DCCM scrub below, so
     * before anything writes DCCM and before the C runtime exists. The check used
     * to live in C (rom_main.c, after straps, PLL, lifecycle and chip-ID), which
     * meant a repair failure let the ROM compute and store the lifecycle -- the
     * input that decides whether secure boot is enforced -- in memory whose
     * integrity had not been established. Worse, LC_STATE_TEST_DEV is 0x0, so a
     * corrupted lc_state biases toward the permissive answer.
     *
     * Three instructions of setup are all it takes: the SMC base is a
     * compile-time constant here, so unlike the reference (which loads its SMC
     * base from a register first) no preparation is needed.
     */
    li      t0, SMC_DFX_CTRL_STATUS_SMU
    lw      t1, 0(t0)                       /* t1 = raw DFT status, kept live */
    andi    t2, t1, DFT_MEM_REPAIR_SUCCESS
    bnez    t2, 4f                          /* repaired -> continue */

    /* Repair failed. Record the raw status before doing anything else: if this
     * read ever returns 0 because the SMC window is not reachable this early,
     * scratch 10 shows 0 and distinguishes "cannot read" from "really failed". */
    li      t0, SMC_SCRATCH_MBIST_FAIL
    sw      t1, 0(t0)

    /* STATUS_ENCODE(STATUS_TYPE_WARN, SEP_MSG_MBIST_FAIL)
     * = (0x08 << 24) | (0x01 << 16) | 0x219 = 0x08010219
     * WARN, not ERROR: the bypass fuse below may still permit the boot. */
    li      t0, SEP_COLD_SCRATCH_1
    li      t2, 0x08010219
    sw      t2, 0(t0)

    /* Bypass fuse. Blown -> continue despite the failure; unblown -> hang. */
    li      t0, SEP_EFUSE_STATUS_RPT
    lw      t3, 0(t0)
    andi    t4, t3, STATUS_RPT_MEM_REPAIR_IGNORE
    bnez    t4, 4f

    /* No bypass: stop. Do not fall through to the scrub -- writing 128KiB of
     * memory that just failed repair is exactly what must not happen.
     *
     * This reproduces what rom_err_fail(ROM_ERR_DFT_GATE_BLOCKED) used to emit,
     * deliberately, so the observable contract does not change when the gate
     * moves out of C: cold_scratch[1] gets STATUS_ENCODE(ERROR, 0xD001) =
     * 0x0f01d001, then the mailbox gets the MAGIC/FAIL/code triple that tells the
     * testbench the ROM stopped rather than hung silently. The one part that
     * cannot come along is the simputs() console text -- there is no C runtime
     * here -- and the bl0_state error_code, which is not initialised this early.
     *
     * The mailbox writes work because the outbound filter was opened above;
     * warm_reset_hang cannot do this because it runs before that setup, which is
     * why it only leaves a scratch word. */
mem_repair_fail_hang:
    li      t0, SEP_COLD_SCRATCH_1
    li      t2, 0x0f01d001
    sw      t2, 0(t0)

    li      t0, SEP_STDOUT_MBX
    li      t2, SEP_FW_MAGIC0
    sw      t2, 0(t0)
    li      t2, SEP_FW_FAIL
    sw      t2, 0(t0)
    li      t2, 0x0000d001              /* ROM_ERR_DFT_GATE_BLOCKED */
    sw      t2, 0(t0)

5:  wfi
    j       5b
4:
    /* Memory scrub (DCCM):
     * Clear DCCM before initializing runtime sections.
     *
     * Default (Phase 1): full scrub (128KiB). This matches TT-S behavior and
     * provides deterministic init/ECC state for early bring-up.
     *
     * If RTL sim runtime becomes an issue, override at build time with a
     * smaller scrub length:
     *   make -C fw/sep/bootcode clean all DCCM_SCRUB_BYTES=0x2000
     * Set DCCM_SCRUB_BYTES=0 to disable scrub entirely (required for
     * BACKDOOR_TCM preload where UVM already applies ECC).
     *
     * Note: `.data copy` will populate initialized data afterwards.
     */
    li      t0, DCCM_BASE           /* start at DCCM base (0xC0040000) */
    li      t1, DCCM_SCRUB_BYTES
    beqz    t1, 1f                  /* skip scrub if DCCM_SCRUB_BYTES=0 */
    add     t1, t0, t1              /* scrub end = base + count */
    /* clamp scrub end to __stack_top */
    la      t2, __stack_top
    bltu    t1, t2, 0f
    mv      t1, t2
0:
    sw      zero, 0(t0)
    addi    t0, t0, 4
    bltu    t0, t1, 0b
1:

    /* Minimal C runtime init: copy .data and clear .bss (in DCCM). */
    la      t0, __data_load_start
    la      t1, __data_start
    la      t2, __data_end
    beq     t1, t2, 1f
0:
    lw      t3, 0(t0)
    sw      t3, 0(t1)
    addi    t0, t0, 4
    addi    t1, t1, 4
    bltu    t1, t2, 0b
1:

    la      t0, __bss_start
    la      t1, __bss_end
    beq     t0, t1, 3f
2:
    sw      zero, 0(t0)
    addi    t0, t0, 4
    bltu    t0, t1, 2b
3:

    /* Status: runtime init done (scrub + .data/.bss) → scratch[1]
     * STATUS_ENCODE(STATUS_TYPE_DEBUG, SEP_MSG_RUNTIME_INIT_OK)
     * = (0x80 << 24) | (0x01 << 16) | 0x211 = 0x80010211 */
    li      t0, SEP_COLD_SCRATCH_1
    li      t1, 0x80010211
    sw      t1, 0(t0)

    /* Jump into ROM main. */
    call    rom_main

1:  wfi
    j       1b

    .align  4
trap_vector:
    /* On any trap, read key CSRs and call C handler for debug output.
     * Requires sp to be valid (set up during cold_boot). */
    addi    sp, sp, -4
    sw      ra, 0(sp)
    csrr    a0, mcause
    csrr    a1, mepc
    csrr    a2, mtval
    csrr    a3, mstatus
    call    trap_handler_c
    /* trap_handler_c does not return, but just in case: */
    lw      ra, 0(sp)
    addi    sp, sp, 4
2:  wfi
    j       2b

secondary_hart:
    /* Secondary harts: set mtvec then park. */
    la      t0, trap_vector
    csrw    mtvec, t0
4:  wfi
    j       4b

    .size _start, .-_start
