/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */
/*
 * smu_sep_external_irq_test -- shared protocol contract for the SMU wrapper
 * interrupt pin.
 *
 * sep.sv concatenates the wrapper pin vector directly above the internal
 * slots, so wrapper bit N drives sep_interrupts[NUM_INTERNAL_IRQS + N], and
 * EL2 numbers PIC sources from 1. The source ID is that mapping, not a hedged
 * candidate window.
 *
 * SEP_NUM_INTERNAL_IRQS mirrors sep_pkg::NUM_INTERNAL_IRQS, which C cannot
 * read. It has moved twice already (34 -> 38 -> 43), and each move slides the
 * wrapper pin onto a different source: at 43, the stale 39 addresses the eFuse
 * token comparator fault instead. Arming the wrong source is not a visible
 * failure -- the pin pulse lands on a source nobody enabled, no ISR runs, and
 * the test waits forever. run_ext_irq() therefore bounds that wait and reports
 * which source did go pending, so the next parameter change fails with the
 * number it should have used rather than with a timeout.
 */
#ifndef SEP_SMU_EXT_IRQ_PROTOCOL_H
#define SEP_SMU_EXT_IRQ_PROTOCOL_H

#define EXT_IRQ_SMC_IMAGE_FIRST_WORD 0x41014081
#define EXT_IRQ_SMC_ENTRY 0x00000000C00601B2ULL
#define EXT_IRQ_FW_POLL_LIMIT 4000000

#define SEP_NUM_INTERNAL_IRQS 43
#define SEP_PIC_TOTAL_SOURCES 255

#define EXT_IRQ_PIN_BIT 0
#define EXT_IRQ_PIC_SOURCE (SEP_NUM_INTERNAL_IRQS + EXT_IRQ_PIN_BIT + 1)

_Static_assert(EXT_IRQ_PIC_SOURCE > SEP_NUM_INTERNAL_IRQS,
               "wrapper pin must map above the internal IRQ slots");
_Static_assert(EXT_IRQ_PIC_SOURCE <= SEP_PIC_TOTAL_SOURCES,
               "wrapper pin source exceeds the EL2 PIC source range");

/* Bound on the wait for the armed pulse, in mcycle. */
#define EXT_IRQ_ISR_WAIT_MCYCLE 200000

#define EXT_IRQ_MEIPL 1
#define EXT_IRQ_MEIGWCTRL 0x2
#define EXT_IRQ_DISABLED_MCYCLE 256
#define EXT_IRQ_POST_ISR_MCYCLE 32

#define EXT_IRQ_S0_FAIL 0x00820FA1
/* Published when the armed pulse never reached the expected source; the low
 * byte carries whichever source was pending instead, 0xFF for none. */
#define EXT_IRQ_WRONG_SOURCE 0x00820F00
#define EXT_IRQ_BRINGUP_OK 0x00820000
#define EXT_IRQ_DISABLED_ARMED 0x00820001
#define EXT_IRQ_DISABLED_CLEAN 0x00820002
#define EXT_IRQ_ARMED 0x00820003
#define EXT_IRQ_ISR_SEEN 0x00820004
#define EXT_IRQ_CLEARED 0x00820005

#endif /* SEP_SMU_EXT_IRQ_PROTOCOL_H */
