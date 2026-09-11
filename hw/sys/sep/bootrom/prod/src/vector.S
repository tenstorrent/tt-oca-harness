/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* OCAH SEP Boot ROM
 *
 * Code executes from Boot ROM (0x10040000) via the IFU AXI demux.
 * Data (.rodata/.data/.bss/stack) resides in DCCM (0xC0040000).
 * The ROM reports entirely through cold_scratch: verdict in [0], status in [1],
 * console in [2]. It stores nothing outside SEP and opens no egress window.
 *
 * Build assumes RV32IM (no compressed — .option norvc).
 */

    .option norvc
    .section .text.init, "ax", @progbits
    .globl _start
    .type  _start, @function

#include "sep_addr.h"

/* Reset entry and the halts report through cold_scratch and nothing else: it is
 * a SEP register, always present and writable from the first instruction. These
 * paths must survive anything, and a store into the external SMU aperture can
 * take a bus error on a part where nothing is mapped there, which raises NMI and
 * turns a clean stop into a loop. */
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

/* Warm-handler slot: SEP COLD scratch 7.
 *
 * The COLD bank, because the value has to survive the warm/watchdog reset it is
 * dispatching from: cold scratch reads 0 on a cold reset and retains across a
 * warm one. The WARM bank does not retain -- its arst_n is
 * sep_reset_n & wdt_rst_ni -- so a watchdog reset would clear the very register
 * the handler address was parked in.
 */
.equ SEP_COLD_SCRATCH_7, OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(7)
.equ SEP_COLD_SCRATCH_0, OCH_SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(0)

/* ICCM address range for warm handler jump validation.
 *
 * ICCM, not SRAM: the boot flow requires a valid ICCM address, so the range
 * check has to be the ICCM window. */
.equ WARM_HANDLER_RANGE_BASE,  OCH_SEP_TOP_SEP_ICCM_BASE_ADDR
.equ WARM_HANDLER_RANGE_END,   OCH_SEP_TOP_SEP_ICCM_BASE_ADDR + OCH_SEP_TOP_SEP_ICCM_SIZE

/* MEM_REPAIR boot gate. Mirrors include/sep_smc_interface.h -- the C side owns
 * these numbers, so they must be changed in both places together. Kept as .equ
 * rather than pulled from a header because that header is C, not assembly. */
.equ SEP_SMC_GLOBAL_BASE,      0x40000000
/* Offsets must match sep_smc_interface.h, which takes them from this design's
 * generated SMC map. */
.equ SMC_DFX_CTRL_STATUS_SMU,  SEP_SMC_GLOBAL_BASE + 0xB800
/* SMC scratch registers are 64-bit; index 10 is the agreed MBIST/MEM_REPAIR
 * failure slot, read back by the debugger and by DV. */
.equ SMC_SCRATCH_MBIST_FAIL,   SEP_SMC_GLOBAL_BASE + 0x39080 + (10 * 8)

/* DFX_CTRL_STATUS_SMU fields (dfx_ctrl_status.rdl). All six are sticky-1,
 * software-read-only, and written by the external DFT controller. */
.equ DFT_MEM_REPAIR_SUCCESS,   (1 << 1)
.equ DFT_MBIST_DONE,           (1 << 4)
.equ DFT_MBIST_PASS,           (1 << 8)
.equ DFT_MBIST_ABORT,          (1 << 12)

/* Straps live in the SMC external supplementary window. These offsets match
 * sep_smc_interface.h and the captured-GPIO straps map. */
.equ SMC_STRAPS_LO,            SEP_SMC_GLOBAL_BASE + 0x405800
.equ SMC_STRAPS_HI,            SEP_SMC_GLOBAL_BASE + 0x405804
/* BYPASS_SRAM_REPAIR -> STRAPS_LO[13]. It drives skip_mem_repair_o, so repair
 * NEVER RAN.
 *
 * The status bits then do not report on any repair that happened -- but do NOT
 * assume they read back 0. The specification says that when skip_mem_repair_o is
 * asserted the external repair logic "should skip operations and immediately
 * assert completion status", without saying which of done/success it asserts. A
 * bypassed part may therefore present done=1,success=0 (completion asserted,
 * nothing repaired) just as plausibly as done=1,success=1. In the first case,
 * reading success here would brick a legitimately strapped part on a fuse
 * (SKIP_MEM_CHECK) that nobody has any reason to have blown. Skipping the arm is
 * the correct response under either reading, which is why this arm skips
 * outright rather than treating some particular value as a failure to excuse. */
.equ STRAP_BYPASS_SRAM_REPAIR,  (1 << 13)
/* MBIST_BYPASS -> STRAPS_HI[22]: "Ignore results of Power-On MBIST for boot".
 * Do not merge the two bypass arms: MBIST still RUNS under this strap, so
 * mbist_done sets normally and only the verdict is discarded, whereas
 * BYPASS_SRAM_REPAIR stops repair happening at all. */
.equ STRAP_MBIST_BYPASS_HI,     (1 << 22)

/* SKIP_MEM_CHECK fuse: STATUS_RPT bit 2. Applies to a check that RAN and FAILED
 * -- distinct from either bypass strap above, which mean the check did not run
 * or its result is not to be believed. 0 = hang, 1 = warn and continue.
 *
 * Fail-closed: the bit is 0 on an unblown part. Permitting a boot after a check
 * that RAN AND FAILED therefore requires deliberately blowing a fuse; that
 * particular escape cannot be arranged at run time by holding a pin.
 *
 * That covers THIS FUSE ONLY, not the gate as a whole. Both bypass straps skip
 * their arm outright, so anyone able to hold a strap can stop the corresponding
 * check from being evaluated without touching any fuse. That is the straps'
 * documented purpose and a different threat surface.
 *
 * LIMITATION: bit 2 falls inside `reserved[31:2]` in this design's
 * sep_efuse_map RDL, so this is an undeclared use of a reserved bit. The
 * specification declares STATUS_RPT as 32 bits with 2 used, both for status
 * reporting, and allocates nothing for a MEM_REPAIR bypass. The register's
 * `sw = r` / `hw = rw` access is nevertheless correct for this use: software
 * cannot assert the bit, only the fuse can.
 */
.equ SEP_EFUSE_STATUS_RPT,     OCH_SEP_TOP_SEP_EFUSE_MAP_STATUS_RPT_BASE_ADDR
.equ STATUS_RPT_SKIP_MEM_CHECK, (1 << 2)

/* Bound on the wait for mbist_done. LIMITATION: not derived from a measured
 * MBIST duration.
 *
 * COUNT AXI TRANSACTIONS, NOT INSTRUCTIONS. Each iteration performs one read of
 * a register on the far side of the SMC fabric, so the cost per iteration is a
 * bus round trip -- tens of cycles -- not the handful of instructions the loop
 * body looks like. 10000 bounds the worst case to roughly 300K cycles, about
 * 3 ms at 100 MHz and a fraction of a boot in simulation; a value in the
 * millions would be several HOURS of simulation for a single timeout. It runs on
 * REFCLK, the PLL not being up yet, so it has no fixed wall-clock meaning.
 *
 * A timeout is treated as a failure, so too small a value could stop a healthy
 * part -- but the hardware releases the SEP CPU only after repair, and MBIST is
 * expected to be complete or nearly so by then, which is why a large margin is
 * not needed.
 */
.equ MBIST_DONE_WAIT_ITERS,    10000

_start:
    /* Multi-hart safety: only hart0 proceeds (others park). */
    csrr    t0, mhartid
    bnez    t0, secondary_hart

    /* Set a trap vector before the first MMIO access. It has to be the
     * stack-free one: sp is not established until cold_boot, and trap_vector
     * pushes ra, so a trap taken here would store through a garbage sp --
     * likely outside DCCM, which is a bus error, which is an NMI, which is a
     * double fault. cold_boot re-points mtvec once sp exists. */
    la      t0, trap_vector_early
    csrw    mtvec, t0

    /* Configure VeeR EL2 MRAC before warm reset check so that the
     * cold_scratch read at 0x1080xxxx (region 1) gets correct
     * memory attributes (side-effect, non-cacheable). Cold, not warm: the
     * handler slot moved to COLD scratch 7, see the block above SEP_COLD_SCRATCH_7.
     * Both banks sit in region 1, so the MRAC value itself is unchanged. */
    li      t0, 0xAAAAAAA8
    csrw    0x7C0, t0

    /* ── Warm reset detection ─────────────────────────────────────
     *
     * On warm reset (WDT bark → wdt_rst_ni low):
     *   - CPU is reset (sep_cpu_reset_n = sep_reset_n & wdt_rst_ni)
     *   - ICCM/DCCM content preserved (not reset)
     *   - sep_scratch_cold_scratch[] preserved (not reset) -- this is the bank
     *     the handler slot lives in
     *   - sep_scratch_warm_scratch[] is NOT preserved: its
     *     arst_n = sep_reset_n & wdt_rst_ni, so a watchdog reset clears it.
     *     The handler slot therefore lives in the COLD bank; see the block
     *     above SEP_COLD_SCRATCH_7.
     *   - All CPU CSRs reset to defaults
     *
     * BL1 writes its re-entry address to cold_scratch[7] before enabling
     * the WDT.  On warm reset, ROM reads this and jumps back to BL1.
     *
     * Protocol:
     *   1. Read cold_scratch[7]
     *   2. If zero → cold boot
     *   3. If non-zero: range check against
     *      [WARM_HANDLER_RANGE_BASE, WARM_HANDLER_RANGE_END) = SEP ICCM
     *   4. If valid: jump to handler, leaving the slot INTACT
     *   5. If invalid: hang
     *   The cold path poisons with -1, deliberately out of range, so an
     *   unarmed warm reset lands on step 5 rather than step 2.
     *
     * This check happens BEFORE touching DCCM (sp/gp/scrub/.data/.bss)
     * to preserve BL1's runtime state across warm reset.
     */
    li      t0, SEP_COLD_SCRATCH_7
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
     * Written with t3/t4 so t1 (handler address) stays live for the jump. */
    li      t3, SEP_COLD_SCRATCH_1
    li      t4, 0x01010068
    sw      t4, 0(t3)

    /* NO POISON HERE, DELIBERATELY. The handler address is left in place; only
     * the cold path writes the slot, and it writes -1.
     *
     * Persistence is what a watchdog handler needs: BL1 arms the watchdog after
     * parking its re-entry address here, so the SECOND watchdog reset must reach
     * the handler too. Poisoning on dispatch would let only the first one
     * through and silently disarm watchdog recovery. */

    /* Jump to warm reset handler. BL1 sets up its own sp/mtvec/PMP as needed. */
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
    /* Poison cold_scratch[7] with an out-of-range value rather than 0.
     * A later warm reset arriving with no handler armed then fails the range
     * check and hangs with SEP_MSG_WARM_RESET_HANG, instead of taking the
     * beqz early-out and silently cold booting -- for a repeating watchdog
     * that would be a boot loop with no diagnosable stop. This matches the
     * philosophy already stated on the invalid-handler path below: an
     * unexpected handler value may indicate corruption or attack.
     *
     * The warm path writes NOTHING -- see the accept arm above, where
     * persistence is what a watchdog handler slot is for.
     *
     * -1 is what the specification asks for on the cold path. Writing 0 instead
     * would take the beqz early-out and cold boot silently. */
    li      t0, SEP_COLD_SCRATCH_7
    li      t1, -1
    sw      t1, 0(t0)

    /* Set stack near top of DCCM (from linker script). */
    la      sp, __stack_top

    /* Set global pointer for small-data accesses (gp-relative). */
    la      gp, __global_pointer$

    /* sp exists now, so upgrade from the stack-free early vector to the one
     * that can call into C and print a decoded trap. */
    la      t0, trap_vector
    csrw    mtvec, t0

    /* The SEP outbound filter blocks all AXI egress by default and the ROM opens
     * nothing: its verdict, status and console are cold_scratch, a SEP register.
     * A stage that needs egress opens its own window -- the DV BL1 image does
     * exactly that in bl1_outbound_filter_init(). */

    /* Status: entered _start (hart0) → scratch[1]
     * STATUS_ENCODE(STATUS_TYPE_DEBUG, SEP_MSG_BOOTROM_START)
     * = (0x80 << 24) | (0x01 << 16) | 0x44 = 0x80010044 */
    li      t0, SEP_COLD_SCRATCH_1
    li      t1, 0x80010044
    sw      t1, 0(t0)

    /* Disable interrupts during early init (defensive). */
    csrw    mie, zero
    csrci   mstatus, 0x8        /* clear MIE */

    /* PMP init: a region-based policy (NAPOT).
     *
     * Optional knobs:
     * - PMP_ENABLE=0: skip PMP programming
     * - PMP_LOCK=1: set L bit on programmed entries (locked until reset)
     *
     * Regions:
     * - entry0: Boot ROM  0x1004_0000 .. 0x1004_FFFF (64KiB)  : R-X
     * - entry1: DCCM      0xC004_0000 .. 0xC005_FFFF (128KiB) : RW-
     * - entry2: unused (A=OFF, left free for a later stage)
     * - entry3: SRAM      0x1000_0000 .. 0x1003_FFFF (256KiB) : RWX (BL1 code+data)
     * - entry4: Periph    0x1080_0000 .. 0x10BF_FFFF (4MiB)   : RW-
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
     * - entry2 unused:   0x00 (A=OFF; a later stage may claim it)
     * - entry3 SRAM RWX: 0x18|0x07 = 0x1F
     */
#if PMP_LOCK
    li      t0, 0x9f009b9d      /* L on entries 0,1,3; entry2 off */
#else
    li      t0, 0x1f001b1d
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
     * WHY IT SITS HERE, IN ASSEMBLY. It must run before the DCCM scrub below, so
     * before anything writes DCCM and before the C runtime exists. In C it would
     * run after straps, PLL, lifecycle and chip-ID, which would let a repair
     * failure have the ROM compute and store the lifecycle -- the input that
     * decides whether secure boot is enforced -- in memory whose integrity is not
     * established. LC_STATE_TEST_DEV is 0x0, so a corrupted lc_state biases
     * toward the permissive answer.
     *
     * The SMC base is a compile-time constant here, so the check costs three
     * instructions of setup.
     */
    li      t0, SMC_DFX_CTRL_STATUS_SMU
    lw      t1, 0(t0)                       /* t1 = raw DFT status, kept live */

    /* ---- Arm 1: memory repair --------------------------------------------
     * Skipped entirely when BYPASS_SRAM_REPAIR is strapped: repair never ran, so
     * the status bits are not a report on it and must not be read as one. See
     * STRAP_BYPASS_SRAM_REPAIR above for why the bits cannot simply be assumed
     * to be 0 either. */
    li      t0, SMC_STRAPS_LO
    lw      t5, 0(t0)
    li      t4, STRAP_BYPASS_SRAM_REPAIR    /* (1<<13) exceeds andi's 12-bit imm */
    and     t2, t5, t4
    bnez    t2, 1f                          /* repair bypassed -> do not check */

    andi    t2, t1, DFT_MEM_REPAIR_SUCCESS
    beqz    t2, dft_gate_failed             /* ran and failed */

1:  /* ---- Arm 2: MBIST ----------------------------------------------------
     * Required by the boot flow ("Check SMU MBIST results?").
     *
     * The wait is not defensive, it is required. The specification releases the SEP CPU
     * "once memory repair is done or bypassed" -- repair only, MBIST is not
     * named -- while the SMC cluster waits for both. So MBIST may still be
     * running here, and reading mbist_pass without waiting would read a 0 that
     * means "not finished yet" and report it as a failure. */
    li      t0, SMC_STRAPS_HI
    lw      t5, 0(t0)
    li      t4, STRAP_MBIST_BYPASS_HI       /* (1<<22) exceeds andi's 12-bit imm */
    and     t2, t5, t4
    bnez    t2, 4f                          /* results to be ignored -> continue */

    /* Address and mask are loop invariants; hoisting them halves the work per
     * iteration. t0 and t4 must therefore survive the loop body, which only
     * writes t1, t2 and t3. */
    li      t0, SMC_DFX_CTRL_STATUS_SMU
    li      t4, DFT_MBIST_ABORT             /* (1<<12) exceeds andi's 12-bit imm */
    li      t3, MBIST_DONE_WAIT_ITERS
2:  lw      t1, 0(t0)                       /* refresh: sticky bits, so re-read */
    and     t2, t1, t4
    bnez    t2, dft_gate_failed             /* aborted -> verification incomplete */
    andi    t2, t1, DFT_MBIST_DONE
    bnez    t2, 3f                          /* done -> verdict is now valid */
    addi    t3, t3, -1
    bnez    t3, 2b
    j       dft_gate_failed                 /* timeout -> fail closed */

3:  andi    t2, t1, DFT_MBIST_PASS
    bnez    t2, 4f                          /* passed -> continue */

    /* ---- Shared failure path ---------------------------------------------
     * Reached by: repair ran and failed; MBIST aborted; MBIST timed out; MBIST
     * completed and failed. All four mean the same thing for boot safety --
     * this memory has not been shown to be trustworthy -- so they share one
     * response. The raw status word in scratch 10 is what distinguishes them
     * afterwards. */
dft_gate_failed:
    /* Record the raw status before doing anything else: if this read ever
     * returns 0 because the SMC window is not reachable this early, scratch 10
     * shows 0 and distinguishes "cannot read" from "really failed". */
    li      t0, SMC_SCRATCH_MBIST_FAIL
    sw      t1, 0(t0)

    /* STATUS_ENCODE(STATUS_TYPE_WARN, SEP_MSG_MBIST_FAIL)
     * = (0x08 << 24) | (0x01 << 16) | 0x219 = 0x08010219
     * WARN, not ERROR: the SKIP_MEM_CHECK fuse below may still permit the boot. */
    li      t0, SEP_COLD_SCRATCH_1
    li      t2, 0x08010219
    sw      t2, 0(t0)

    /* SKIP_MEM_CHECK. Blown -> continue despite the failure; unblown -> hang. */
    li      t0, SEP_EFUSE_STATUS_RPT
    lw      t3, 0(t0)
    andi    t4, t3, STATUS_RPT_SKIP_MEM_CHECK
    bnez    t4, 4f

    /* No bypass: stop. Do not fall through to the scrub -- writing 128KiB of
     * memory that just failed repair is exactly what must not happen.
     *
     * cold_scratch[1] gets STATUS_ENCODE(ERROR, 0xD001) = 0x0f01d001, the same
     * word rom_err_fail(ROM_ERR_DFT_GATE_BLOCKED) leaves, so the observable
     * contract survives the gate moving out of C. What cannot come along is the
     * simputs() console text -- there is no C runtime here -- and the bl0_state
     * error_code, which is not initialised this early.
     *
     * Scratch ONLY, deliberately: nothing outside SEP is touched here. Whether
     * anything is mapped in the external SMU aperture is an SoC integration
     * property; on a part where it is not, the store takes a bus error, the bus
     * error raises NMI, and a failure path that was supposed to stop cleanly
     * turns into an NMI loop. cold_scratch is a SEP register and is always there.
     *
     * DV therefore cannot learn of this halt from fw_done; a test covering it
     * polls cold_scratch[1] instead. */
mem_repair_fail_hang:
    li      t0, SEP_COLD_SCRATCH_1
    li      t2, 0x0f01d001
    sw      t2, 0(t0)

5:  wfi
    j       5b
4:
    /* Memory scrub (DCCM):
     * Clear DCCM before initializing runtime sections.
     *
     * The default is a full 128KiB scrub. Because a
     * store writes its ECC, this scrub is what establishes DCCM's ECC state:
     * on silicon DCCM powers up with random contents and random ECC, and a
     * sub-word store read-modify-writes the word it lands in.
     *
     * The scrub covers ALL of DCCM, the bl0_state reserve at the top included,
     * and is deliberately not clamped to __stack_top. init_bl0_state() writes
     * that struct byte by byte, so leaving the reserve unscrubbed would put
     * those first stores on words whose ECC was never established. Nothing
     * needs bl0_state to survive the scrub either: on the cold path
     * init_bl0_state() rewrites the struct afterwards, and on the warm path the
     * ROM jumps to BL1's handler before touching DCCM at all, so this code
     * never runs. Holding the stack off bl0_state is the reserve's only job.
     *
     * If RTL sim runtime becomes an issue, override DCCM_SCRUB_BYTES at build
     * time with a smaller scrub length.
     * DCCM_SCRUB_BYTES=0 disables the scrub entirely and leaves DCCM's ECC to
     * whatever wrote it last. Firmware owns that step; do not disable it to let
     * a testbench preload stand in.
     *
     * Note: `.data copy` will populate initialized data afterwards.
     */
    li      t0, DCCM_BASE           /* start at DCCM base (0xC0040000) */
    li      t1, DCCM_SCRUB_BYTES
    beqz    t1, 1f                  /* skip scrub if DCCM_SCRUB_BYTES=0 */
    add     t1, t0, t1              /* scrub end = base + count */
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
trap_vector_early:
    /* Trap handler for the window before cold_boot establishes sp: touches no
     * memory except cold_scratch[1], and calls nothing.
     *
     * Diagnostics go to cold_scratch[1] in sequence -- status, mcause, mtval,
     * mepc, then the status again -- each store overwriting the last. The order
     * is fixed so one decoder can reconstruct the sequence, and the closing
     * status write is the point: a bus observer (the tb
     * samples this register every cycle) reconstructs the whole sequence, while
     * a post-mortem register read on silicon finds a decodable status rather
     * than a bare CSR value it cannot identify.
     *
     * cold_scratch is a SEP register, so these stores cannot leave the
     * subsystem and cannot themselves fault. Nothing here may address anything
     * outside SEP -- see the note by the constants at the top of this file. */
    li      t0, SEP_COLD_SCRATCH_1
    li      t1, 0x0f010028              /* STATUS_ENCODE(ERROR, SEP_MSG_GENERAL_EXCEPTION) */
    sw      t1, 0(t0)
    csrr    t2, mcause
    sw      t2, 0(t0)
    csrr    t2, mtval
    sw      t2, 0(t0)
    csrr    t2, mepc
    sw      t2, 0(t0)
    sw      t1, 0(t0)                   /* leave a decodable status resting here */

    /* Terminal verdict. cold_scratch[0] is a SEP register, writable this early,
     * carrying none of the addressing risk of an external-aperture store. The
     * whole ROM reports here -- the C paths via errors.h TEST_FAIL_CODE, which is
     * this same 0xDEADBEEF, so one constant covers both.
     *
     * Only the exception handler does this, not mem_repair_fail_hang: a repair
     * failure is a gated outcome with a bypass fuse, not an unexpected fault. */
    li      t0, SEP_COLD_SCRATCH_0
    li      t2, 0xDEADBEEF
    sw      t2, 0(t0)
3:  wfi
    j       3b

    .align  4
trap_vector:
    /* On any trap, read key CSRs and call C handler for debug output.
     * Requires sp to be valid; mtvec only points here after cold_boot sets it,
     * and trap_vector_early covers everything before that. */
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
    /* Secondary harts: set mtvec then park. The stack-free vector, not
     * trap_vector -- these harts never reach cold_boot, so they never get an
     * sp, and trap_vector would push ra through whatever sp holds at reset. */
    la      t0, trap_vector_early
    csrw    mtvec, t0
4:  wfi
    j       4b

    .size _start, .-_start
