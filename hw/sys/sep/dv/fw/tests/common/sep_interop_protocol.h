/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */
/*
 * sep_interop  --  shared protocol contract (single source of truth).
 *
 * Included by BOTH firmwares (SMC producer main.c + SEP consumer sep_smc_interop.c).
 * Python goldens derive mailbox CSR facts independently from PeakRDL; they do
 * not parse this header.
 *
 * Topology -- the SMC CPU and the real SEP CPU exchange 32-bit words over the two ports of
 * the SEP AXI-lite mailbox pair (sep.h AXIL_MAILBOX_*):
 *   port 0  OUTBOUND_MAILBOX_0 @ 0x10A00000  <- SEP-local port  (the SEP drives this side)
 *   port 1  INBOUND_MAILBOX_0  @ 0x10A00800  <- SMC-facing port (the SMC drives this side)
 * The mailbox cross-connects the two FIFOs: a WRITE_DATA push at one port is drained by the
 * other port's READ_DATA, and each port's STATUS.empty / read-data IRQ tracks the FIFO it
 * drains. So the SMC pushes TOKEN/ACK at 0x10A00800 (SEP pops at 0x10A00008), and the SEP
 * pushes RESPONSE/SEP_PASS at 0x10A00000 (SMC pops at 0x10A00808).
 *
 * SEP<->SMC scratch -- the SEP reaches SMC CPU_CTRL scratch through the SEP->SMC alias
 * (SEP-view 0x4000_0000 -> SMC-local 0xC000_0000): SMC scratch12 (SMC-local 0xC00390E0) is
 * the SEP READY rendezvous at SEP-view 0x400390E0.
 */
#ifndef SEP_INTEROP_PROTOCOL_H
#define SEP_INTEROP_PROTOCOL_H

/* Handshake payload words (32-bit) pushed through the mailbox. */
#define SEP_INTEROP_TOKEN 0xA5C3E1B7    /* SMC -> SEP : opening token                 */
#define SEP_INTEROP_RESPONSE 0x5A3C1E48 /* SEP -> SMC : reply (verified as this exact */
                                        /*              literal, NOT ~TOKEN)          */
#define SEP_INTEROP_ACK 0xACC00200      /* SMC -> SEP : acknowledge the response       */
#define SEP_INTEROP_SEP_PASS 0x5E900002 /* SEP -> SMC : SEP-side completion            */

/* Rendezvous / verdict markers. */
#define SEP_INTEROP_SMC_UP 0x5C1A11E0u   /* SMC -> SEP scratch2  : SMC past its own scratch init */
#define SEP_INTEROP_READY 0x51EAD001     /* SEP -> SMC scratch12 : SEP mailbox side up  */
#define SEP_INTEROP_TEST_PASS 0xACAFACA1 /* SMC scratch0 : whole test passed            */
#define SEP_INTEROP_TEST_FAIL \
    0x7E57FA11u /* SMC scratch0 / SEP fail marker (distinctive non-reset \
                 * value; NOT 0xFFFFFFFF, which collides with an \
                 * uninitialised scratch read)                 */

#ifdef SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR
#define SEP_LOCAL_MBOX_BASE SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR
#define SMC_INBOUND_MBOX_BASE SEP_TOP_AXIL_MAILBOX_INBOUND_MAILBOX_0_BASE_ADDR
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
#define MBOX_STATUS_EMPTY_MASK AXIL_MAILBOX__STATUS__EMPTY_bm
#define MBOX_IRQ_READ_MASK AXIL_MAILBOX__IRQS__RTIRQ_bm
#define MBOX_IRQ_ALL \
    (AXIL_MAILBOX__IRQS__WTIRQ_bm | AXIL_MAILBOX__IRQS__RTIRQ_bm | AXIL_MAILBOX__IRQS__EIRQ_bm)
#else
#define SEP_LOCAL_MBOX_BASE 0x10A00000
#define SMC_INBOUND_MBOX_BASE 0x10A00800
#define MBOX_WRITE_DATA_OFFSET 0x00
#define MBOX_READ_DATA_OFFSET 0x08
#define MBOX_STATUS_OFFSET 0x10
#define MBOX_RIRQT_OFFSET 0x28
#define MBOX_IRQS_OFFSET 0x30
#define MBOX_IRQEN_OFFSET 0x38
#define MBOX_IRQP_OFFSET 0x40
#define MBOX_STATUS_EMPTY_MASK 0x1
#define MBOX_IRQ_READ_MASK 0x2
#define MBOX_IRQ_ALL 0x7
#endif
/* W1C ALL three IRQ status bits (write | read | error). The write-threshold status
 * is LEVEL-latched and STICKY: it self-sets whenever this side's TX FIFO is non-empty
 * (wirqt defaults to 0), i.e. as a side effect of pushing TOKEN/RESPONSE/ACK/SEP_PASS. A pop
 * only needs to clear the read bit, but the full-clear readback (IRQS==0) then trips on the
 * still-set write bit -- so W1C ALL after each pop. Safe from re-latch: request/response
 * ordering guarantees the peer has already popped this side's TX word (TX FIFO empty) before we
 * pop its reply, so bit0 does not immediately re-assert. Mirrors sep_mailbox_plic_test. */

/* Firmware poll bound (loop iterations) shared by both sides -- mirrors
 * smu_smc_stall_sep's SMU_STALL_FW_POLL_LIMIT. Bounded so a missing peer times out to a fail marker
 * instead of hanging the simulation. */
#define SEP_INTEROP_POLL_LIMIT 4000000

/*
 * SEP-driven SMC bring-up (mirrors smu_smc_stall_sep) -- the TB backdoor-preloads the SMC image
 * into SRAM, then the SEP re-vectors the four SMC cores to the SMC entry symbol and pulses
 * their reset. The SMC firmware is the STACKLESS producer whose naked entry symbol is
 * `sep_interop_entry` (fw/smc/tests/sep_interop/src/main.c, SMC_STACKLESS_ENTRY).
 *
 * SEP_INTEROP_SMC_ENTRY            = SMC-local link address of sep_interop_entry (the value
 *                                    written into RESET_VECTOR_* to launch the SMC).
 * SEP_INTEROP_SMC_IMAGE_FIRST_WORD = first word of the preloaded SMC image (SRAM[0] cookie).
 *
 * BOTH are image-dependent: the human MUST reconcile them against the freshly BUILT image,
 * exactly as smu_smc_stall_sep reconciles SMU_STALL_SMC_ENTRY / SMU_STALL_SMC_IMAGE_FIRST_WORD:
 *   entry  -> address of `sep_interop_entry` in fw/smc/tests/sep_interop/out/test.dis (.sym)
 *   cookie -> first data word at the SRAM base in fw/smc/tests/sep_interop/out/test.preload.hex
 * The values below must match the current build; re-verify after any firmware/linker change.
 */
#define SEP_INTEROP_SMC_ENTRY 0x00000000C00601B2    /* RECONCILE vs built image */
#define SEP_INTEROP_SMC_IMAGE_FIRST_WORD 0x41014081 /* RECONCILE vs built image */

/* SEP-view alias of SMC CPU_CTRL scratch12 (SMC-local 0xC00390E0): the SEP READY rendezvous. */
#define SEP_INTEROP_SMC_SCRATCH12_ALIAS 0x400390E0

/* SEP-view alias of SMC CPU_CTRL scratch2 (SMC-local 0xC0039090): the SMC "up" marker that the
 * SEP POLLS before its first SMC-scratch write, so READY can never race the SMC clearing/initing
 * its own scratch (mirrors the smu_smc_stall_sep INIT_RELEASE_OK gate on
 * SMU_STALL_STATUS_ALIAS_ADDR).
 * 0x40039090 = 0xC0039090 - 0x80000000. */
#define SEP_INTEROP_SMC_SCRATCH2_ALIAS 0x40039090u

#endif /* SEP_INTEROP_PROTOCOL_H */
