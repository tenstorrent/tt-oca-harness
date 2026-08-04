/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */
/*
 * SEP_SMU_002  sep_interop  --  shared protocol contract (single source of truth).
 *
 * Included by BOTH firmwares (SMC producer main.c + SEP consumer sep_smc_interop.c) and
 * parsed by the cocotb checker so the DUT stimulus and the DV expectations can never drift
 * (AGENTS.md one-source rule). Keep every value a plain integer/hex #define so the Python
 * parser can read it -- no expressions the parser cannot evaluate.
 *
 * Topology -- the SMC CPU and the real SEP CPU exchange 32-bit words over the two ports of
 * the SEP AXI-lite mailbox pair (och_sep_top_reg.h AXIL_MAILBOX_*):
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
#define SEP_INTEROP_TOKEN     0xA5C3E1B7   /* SMC -> SEP : opening token                 */
#define SEP_INTEROP_RESPONSE  0x5A3C1E48   /* SEP -> SMC : reply (verified as this exact */
                                           /*              literal, NOT ~TOKEN)          */
#define SEP_INTEROP_ACK       0xACC00200   /* SMC -> SEP : acknowledge the response       */
#define SEP_INTEROP_SEP_PASS  0x5E900002   /* SEP -> SMC : SEP-side completion            */

/* Rendezvous / verdict markers. */
#define SEP_INTEROP_SMC_UP    0x5C1A11E0u  /* SMC -> SEP scratch2  : SMC past its own scratch init */
#define SEP_INTEROP_READY     0x51EAD001   /* SEP -> SMC scratch12 : SEP mailbox side up  */
#define SEP_INTEROP_TEST_PASS 0xACAFACA1   /* SMC scratch0 : whole test passed            */
#define SEP_INTEROP_TEST_FAIL 0x7E57FA11u  /* SMC scratch0 / SEP fail marker (distinctive non-reset
                                            * value; NOT 0xFFFFFFFF, which collides with an
                                            * uninitialised scratch read)                 */

/* Mailbox port bases (och_sep_top_reg.h AXIL_MAILBOX_{OUTBOUND,INBOUND}_MAILBOX_0). */
#define SEP_LOCAL_MBOX_BASE    0x10A00000  /* OUTBOUND_MAILBOX_0 : SEP-local port          */
#define SMC_INBOUND_MBOX_BASE  0x10A00800  /* INBOUND_MAILBOX_0  : SMC-facing port         */

/* Per-port register offsets (identical layout on both ports). */
#define MBOX_WRITE_DATA_OFFSET 0x00        /* push a word into this port's TX FIFO         */
#define MBOX_READ_DATA_OFFSET  0x08        /* pop a word from this port's RX FIFO          */
#define MBOX_STATUS_OFFSET     0x10        /* bit0 = RX FIFO empty                         */
#define MBOX_RIRQT_OFFSET      0x28        /* read-data IRQ threshold                      */
#define MBOX_IRQS_OFFSET       0x30        /* IRQ status (write-1-to-clear)                */
#define MBOX_IRQEN_OFFSET      0x38        /* IRQ enable                                   */
#define MBOX_IRQP_OFFSET       0x40        /* IRQ pending (= IRQS & IRQEN)                 */
#define MBOX_STATUS_EMPTY_MASK 0x1         /* STATUS.empty                                 */
#define MBOX_IRQ_READ_MASK     0x2         /* IRQS/IRQEN/IRQP read-data-available bit      */
/* W1C ALL three IRQ status bits (write[0] | read[1] | error[2]). The write-threshold status
 * (bit0) is LEVEL-latched and STICKY: it self-sets whenever this side's TX FIFO is non-empty
 * (wirqt defaults to 0), i.e. as a side effect of pushing TOKEN/RESPONSE/ACK/SEP_PASS. A pop
 * only needs to clear the read bit, but the full-clear readback (IRQS==0) then trips on the
 * still-set write bit -- so W1C ALL after each pop. Safe from re-latch: request/response
 * ordering guarantees the peer has already popped this side's TX word (TX FIFO empty) before we
 * pop its reply, so bit0 does not immediately re-assert. Mirrors sep_mailbox_plic_test. */
#define MBOX_IRQ_ALL           0x7         /* write | read | error status bits             */

/* Firmware poll bound (loop iterations) shared by both sides -- mirrors 004's
 * SMU_STALL_FW_POLL_LIMIT. Bounded so a missing peer times out to a fail marker instead
 * of hanging the simulation. */
#define SEP_INTEROP_POLL_LIMIT 4000000

/*
 * SEP-driven SMC bring-up (mirrors SEP_SMU_004) -- the TB backdoor-preloads the SMC image
 * into SRAM, then the SEP re-vectors the four SMC cores to the SMC entry symbol and pulses
 * their reset. The SMC firmware is the STACKLESS producer whose naked entry symbol is
 * `sep_interop_entry` (fw/smc/tests/sep_interop/src/main.c, SMC_STACKLESS_ENTRY).
 *
 * SEP_INTEROP_SMC_ENTRY            = SMC-local link address of sep_interop_entry (the value
 *                                    written into RESET_VECTOR_* to launch the SMC).
 * SEP_INTEROP_SMC_IMAGE_FIRST_WORD = first word of the preloaded SMC image (SRAM[0] cookie).
 *
 * BOTH are image-dependent: the human MUST reconcile them against the freshly BUILT image,
 * exactly as SEP_SMU_004 reconciles SMU_STALL_SMC_ENTRY / SMU_STALL_SMC_IMAGE_FIRST_WORD:
 *   entry  -> address of `sep_interop_entry` in fw/smc/tests/sep_interop/out/test.dis (.sym)
 *   cookie -> first data word at the SRAM base in fw/smc/tests/sep_interop/out/test.preload.hex
 * The values below were auto-filled from the local build (see agent report); re-verify after
 * any firmware/linker change.
 */
#define SEP_INTEROP_SMC_ENTRY             0x00000000C00601B6  /* RECONCILE vs built image */
#define SEP_INTEROP_SMC_IMAGE_FIRST_WORD  0x41014081          /* RECONCILE vs built image */

/* SEP-view alias of SMC CPU_CTRL scratch12 (SMC-local 0xC00390E0): the SEP READY rendezvous. */
#define SEP_INTEROP_SMC_SCRATCH12_ALIAS   0x400390E0

/* SEP-view alias of SMC CPU_CTRL scratch2 (SMC-local 0xC0039090): the SMC "up" marker that the
 * SEP POLLS before its first SMC-scratch write, so READY can never race the SMC clearing/initing
 * its own scratch (mirrors SEP_SMU_004's INIT_RELEASE_OK gate on SMU_STALL_STATUS_ALIAS_ADDR).
 * 0x40039090 = 0xC0039090 - 0x80000000. */
#define SEP_INTEROP_SMC_SCRATCH2_ALIAS    0x40039090u

#endif /* SEP_INTEROP_PROTOCOL_H */
