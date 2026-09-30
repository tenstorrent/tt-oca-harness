/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */
/*
 * sep_mbox_irq  --  shared protocol contract (single source of truth).
 *
 * Included by BOTH firmwares (SEP producer sep_smc_mbox_irq.c + SMC consumer main.c).
 * sep_mbox_golden.py derives the same mailbox offsets and masks from PeakRDL; it
 * does not parse this header.
 *
 * Anchor scope: the eight SEP mailbox channels' source
 * interrupts PACK one-hot onto SMC cpu_interrupts[263:256] (4-core NUM_EXT_INTERRUPTS=256), and
 * each channel's source IRQ is cleared with the full W1C/readback/no-refire contract. cmd/response
 * belongs to sep_interop; the SEP->SMC alias datapath belongs to smc_sep_xbar.
 *
 * Topology -- the SEP CPU is the PRODUCER, the SMC CPU is the CONSUMER, across the eight
 * axi_lite_mailbox channels (sep.h AXIL_MAILBOX_*). For channel ch=0..7:
 *   SEP-local  OUTBOUND_MAILBOX_ch @ 0x10A00000 + 0x1000*ch  (the SEP pushes the token here)
 *   SMC-facing INBOUND_MAILBOX_ch  @ 0x10A00800 + 0x1000*ch  (the SMC pops / W1C-clears here)
 * A WRITE_DATA push at the SEP-local (outbound) port asserts that channel's outbound IRQ, which
 * hw/sys/sep/rtl/sep.sv routes out of the block as
 * smc_mailbox_interrupt_o[ch] -> sep_mailbox_interrupts[ch] -> cpu_interrupts[256+ch].
 * The paired inbound IRQ does NOT appear here: it reaches the SEP CPU's own PIC
 * (sep_internal_interrupts[7:0]), which is what sep_mailbox_plic_test grades.
 *
 * Rendezvous / progress -- the SEP reaches SMC CPU_CTRL scratch through the SEP->SMC alias
 * (SEP-view 0x4000_0000 -> SMC-local 0xC000_0000); the SMC accesses the same scratch locally.
 *   scratch2  (SMC-local 0xC0039090, alias 0x40039090) : SMC "up" marker (boot rendezvous)
 *   scratch12 (SMC-local 0xC00390E0, alias 0x400390E0) : SEP READY (SEP filters up)
 *   scratch3  (SMC-local 0xC0039098, alias 0x40039098) : SMC->SEP progress (armed + per-channel
 * done) scratch10 (SMC-local 0xC00390D0, alias 0x400390D0) : SMC final verdict (SMC_PASS /
 * SMC_FAIL) The SEP final verdict is on its own COLD scratch6 (SEP-local 0x10802030).
 */
#ifndef SEP_MBOX_IRQ_PROTOCOL_H
#define SEP_MBOX_IRQ_PROTOCOL_H

/* Number of mailbox channels exercised (sep_pkg::NUM_MAILBOXES). */
#define SEP_MBOX_IRQ_NUM_CHANNELS 8

/* Per-channel token the SEP pushes: 0x15000000 | ch (ch in bits [2:0]). */
#define SEP_MBOX_IRQ_TOKEN_BASE 0x15000000

/* Mailbox port bases + per-channel stride + per-port register offsets.
 *
 * The SEP fw includes sep.h BEFORE this header, so it sources these DIRECTLY from the
 * generated SEP_TOP_AXIL_MAILBOX_* macros (no hardcoded literals). The SMC fw CANNOT include
 * sep.h -- that generated SEP header defines EFUSE_INTERFACE_CTRL/etc. reg types that
 * COLLIDE with the SMC's own smc_top_regs.h ("conflicting types"), so the SMC toolchain uses the
 * literal mirror below. sep_mbox_golden.py
 * derives the same offsets and masks from PeakRDL, so an SMC literal that
 * drifts from RDL lands at an address the golden does not expect and the
 * test fails. outbound[ch]=OUTBOUND_0+stride*ch, inbound[ch]=INBOUND_0+stride*ch;
 * stride = OUTBOUND_1-OUTBOUND_0 (= 2*MAILBOX_SIZE = 0x1000). */
#ifdef SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR /* SEP fw: generated source of truth \
                                                          */
#define SEP_MBOX_IRQ_MBOX_OUTBOUND_BASE SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR
#define SEP_MBOX_IRQ_MBOX_INBOUND_BASE SEP_TOP_AXIL_MAILBOX_INBOUND_MAILBOX_0_BASE_ADDR
#define SEP_MBOX_IRQ_MBOX_CH_STRIDE \
    (SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_1_BASE_ADDR - \
     SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR)
#define MBOX_WRITE_DATA_OFFSET \
    (SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_WRITE_DATA_BASE_ADDR - \
     SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR)
#define MBOX_READ_DATA_OFFSET \
    (SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_READ_DATA_BASE_ADDR - \
     SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR)
#define MBOX_STATUS_OFFSET \
    (SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_STATUS_BASE_ADDR - \
     SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR)
#define MBOX_RIRQT_OFFSET \
    (SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_RIRQT_BASE_ADDR - \
     SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR)
#define MBOX_IRQS_OFFSET \
    (SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_IRQS_BASE_ADDR - \
     SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR)
#define MBOX_IRQEN_OFFSET \
    (SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_IRQEN_BASE_ADDR - \
     SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR)
#define MBOX_IRQP_OFFSET \
    (SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_IRQP_BASE_ADDR - \
     SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR)
#define SEP_MBOX_IRQ_MBOX_REG_BLOCK_SIZE SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_SIZE
#else /* SMC fw: literal mirror */
#define SEP_MBOX_IRQ_MBOX_OUTBOUND_BASE 0x10A00000
#define SEP_MBOX_IRQ_MBOX_INBOUND_BASE 0x10A00800
#define SEP_MBOX_IRQ_MBOX_CH_STRIDE 0x1000
#define MBOX_WRITE_DATA_OFFSET 0x00
#define MBOX_READ_DATA_OFFSET 0x08
#define MBOX_STATUS_OFFSET 0x10
#define MBOX_RIRQT_OFFSET 0x28
#define MBOX_IRQS_OFFSET 0x30
#define MBOX_IRQEN_OFFSET 0x38
#define MBOX_IRQP_OFFSET 0x40
#define SEP_MBOX_IRQ_MBOX_REG_BLOCK_SIZE 0x50
#endif
#ifdef AXIL_MAILBOX__STATUS__EMPTY_bm
#define MBOX_STATUS_EMPTY_MASK AXIL_MAILBOX__STATUS__EMPTY_bm
#define MBOX_IRQ_READ_MASK AXIL_MAILBOX__IRQS__RTIRQ_bm
#else
#define MBOX_STATUS_EMPTY_MASK 0x1
#define MBOX_IRQ_READ_MASK 0x2
#endif
/* W1C the read bit (bit1). Unlike sep_interop, the SMC never PUSHES on the inbound port here
 * (it only pops), so this port's TX FIFO stays empty and the sticky write-threshold status
 * (bit0) never self-sets -- clearing just the read bit (0x2) drives IRQS/IRQP fully to 0, and
 * the readback proves it. The W1C value is 0x2. */
#ifdef AXIL_MAILBOX__IRQS__RTIRQ_bm
#define SEP_MBOX_IRQ_W1C_VALUE AXIL_MAILBOX__IRQS__RTIRQ_bm
#else
#define SEP_MBOX_IRQ_W1C_VALUE 0x2
#endif

/* Progress channel (scratch3) encoding. SMC writes ARMED after arming all 8 inbound IRQs, then
 * (ARMED | (ch+1)) after fully servicing channel ch (pop/verify/W1C/readback-0/no-refire). The
 * SEP gates each push on the matching value, guaranteeing strict one-channel-at-a-time (one-hot)
 * ordering and the no-refire quiet window. */
#define SEP_MBOX_IRQ_PROGRESS_ARMED 0x015B0000 /* all 8 inbound IRQs armed; 0 channels done   */
/* per-channel-done value = SEP_MBOX_IRQ_PROGRESS_ARMED | (ch+1) : 0x015B0001 .. 0x015B0008 */

/* Verdict markers. */
#define SEP_MBOX_IRQ_SMC_PASS 0x015C0001 /* SMC scratch10 : all 8 channels consumed+cleared    */
#define SEP_MBOX_IRQ_SMC_FAIL 0x015CFFEE /* SMC scratch10 : SMC-side failure                   */
#define SEP_MBOX_IRQ_SEP_PASS 0x015A0001 /* SEP cold scratch6 : SEP saw SMC_PASS, completed    */
#define SEP_MBOX_IRQ_SEP_FAIL 0x015AFFEE /* SEP cold scratch6 : SEP-side failure               */

/* Boot rendezvous markers (mirror sep_interop / smu_smc_stall_sep). */
#define SEP_MBOX_IRQ_SMC_UP 0x5C1A11E0u /* SMC -> scratch2  : SMC past its own scratch init     */
#define SEP_MBOX_IRQ_READY 0x51EAD001   /* SEP -> scratch12 : SEP aperture/filters up          */

/* SMC-local scratch absolute addresses (CPU_CTRL scratch array, 8-byte stride). Used only by the
 * SMC fw, which has the generated SMC_CPU_CTRL_SCRATCH_0 macro (smc_top_regs.h via smc_defines.h)
 * -> source from it (no literal). The SEP fw (no smc_top_regs.h) never uses the LOCAL forms; it
 * uses the SEP-view ALIASes below. */
#ifdef SMC_CPU_CTRL_SCRATCH_0__REG_ADDR
#define SEP_MBOX_IRQ_SMC_SCRATCH2_LOCAL (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 2 * 8) /* SMC_UP */
#define SEP_MBOX_IRQ_SMC_SCRATCH3_LOCAL (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 3 * 8) /* progress */
#define SEP_MBOX_IRQ_SMC_SCRATCH10_LOCAL \
    (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 10 * 8) /* SMC verdict      */
#define SEP_MBOX_IRQ_SMC_SCRATCH12_LOCAL \
    (SMC_CPU_CTRL_SCRATCH_0__REG_ADDR + 12 * 8) /* READY rendezvous */
#else
#define SEP_MBOX_IRQ_SMC_SCRATCH2_LOCAL 0xC0039090
#define SEP_MBOX_IRQ_SMC_SCRATCH3_LOCAL 0xC0039098
#define SEP_MBOX_IRQ_SMC_SCRATCH10_LOCAL 0xC00390D0
#define SEP_MBOX_IRQ_SMC_SCRATCH12_LOCAL 0xC00390E0
#endif
/* SEP-view ALIASes (SMC-local - 0x80000000) used by the SEP fw. There is NO generated SEP-side
 * macro for the SEP-view alias of an SMC register, so these are literal by necessity. */
#define SEP_MBOX_IRQ_SMC_SCRATCH2_ALIAS 0x40039090u
#define SEP_MBOX_IRQ_SMC_SCRATCH3_ALIAS 0x40039098u
#define SEP_MBOX_IRQ_SMC_SCRATCH10_ALIAS 0x400390D0u
#define SEP_MBOX_IRQ_SMC_SCRATCH12_ALIAS 0x400390E0u

/* SEP COLD scratch6 (SEP-only; the SEP fw has the generated macro). Cold-reset domain: resets to 0,
 * so a ==SEP_MBOX_IRQ_SEP_PASS read is a positive write-landed proof. */
#ifdef SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR
#define SEP_MBOX_IRQ_SEP_COLD_SCRATCH6 SEP_TOP_SEP_SCRATCH_COLD_SCRATCH_BASE_ADDR(6)
#else
#define SEP_MBOX_IRQ_SEP_COLD_SCRATCH6 0x10802030
#endif

/* SEP SMU aperture size: 0x20000000 so [0,0x20000000) covers the mailbox (0x10A0xxxx) and the
 * SEP peripheral region without overlapping the SMC aperture at [0x40000000, ...). */
#define SEP_MBOX_IRQ_SEP_REGION_SIZE 0x20000000

/* SEP inbound filter window over the WHOLE mailbox channel region so the SMC's pops/W1C/readbacks
 * at every inbound port reach the mailbox. DERIVED from the generated mailbox macros: START =
 * outbound base; END = last inbound channel (INBOUND_0 + 7*stride) + its register-block top
 * (REG_MAP_SIZE-1) = 0x10A0784F. allow_burst=0 -> the byte-granular END stores EXACTLY, as
 * smc_sep_xbar shows. */
#define SEP_MBOX_IRQ_MBOX_FILTER_START ((unsigned long long)SEP_MBOX_IRQ_MBOX_OUTBOUND_BASE)
#define SEP_MBOX_IRQ_MBOX_FILTER_END \
    ((unsigned long long)(SEP_MBOX_IRQ_MBOX_INBOUND_BASE + 7 * SEP_MBOX_IRQ_MBOX_CH_STRIDE + \
                          SEP_MBOX_IRQ_MBOX_REG_BLOCK_SIZE - 1))
#define SEP_MBOX_IRQ_MBOX_FILTER_CFG 0x0000000100030013ULL /* read/write/enable/src_id=3 */
#define SEP_MBOX_IRQ_MBOX_FILTER_CFG_NS 0x0000000100030113ULL /* + allow_ns (non-secure) */
#define SEP_MBOX_IRQ_MBOX_FILTER_CFG_WORD 0x00030013 /* field-based cfg (passive golden) */
#define SEP_MBOX_IRQ_MBOX_FILTER_CFG_WORD_NS 0x00030113 /* + allow_ns (passive golden) */

/* Firmware poll bound (loop iterations) shared by both sides -- bounded so a missing peer times
 * out to a fail marker instead of hanging the simulation (mirrors sep_interop /
 * smu_smc_stall_sep). */
#define SEP_MBOX_IRQ_POLL_LIMIT 4000000

/* Post-clear no-refire hold: the SMC waits this many iterations after the W1C/readback-0 of a
 * channel before publishing that channel's done-marker, guaranteeing the source IRQ stays low
 * well beyond the 64 clk_smc_i no-refire window the cocotb checker measures. */
#define SEP_MBOX_IRQ_NOREFIRE_HOLD_ITERS 4000

/*
 * SEP-driven SMC bring-up (mirrors sep_interop / smu_smc_stall_sep) -- the TB backdoor-preloads
 * the SMC image
 * into SRAM, then the SEP re-vectors the four SMC cores to the SMC entry symbol and pulses their
 * reset. The SMC firmware is the STACKLESS consumer whose naked entry symbol is
 * `sep_mbox_irq_entry` (fw/smc/tests/sep_mbox_irq/src/main.c, SMC_STACKLESS_ENTRY).
 *
 * BOTH values below are image-dependent: reconcile them against the freshly BUILT image exactly
 * as sep_interop / smu_smc_stall_sep do (entry -> address of sep_mbox_irq_entry in out/test.dis
 * .sym; cookie ->
 * first data word at the SRAM base in out/test.preload.hex). Re-verify after any fw/linker change.
 */
#define SEP_MBOX_IRQ_SMC_ENTRY 0x00000000C00601B2    /* RECONCILE vs built image */
#define SEP_MBOX_IRQ_SMC_IMAGE_FIRST_WORD 0x41014081 /* RECONCILE vs built image */

#endif /* SEP_MBOX_IRQ_PROTOCOL_H */
