/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/*
 * PIC delivery of the token-comparator redundancy fault.
 *
 * The fault interrupt is a level that software cannot clear, so the handler
 * masks the source instead. The host injects the fault on the secure-disable
 * comparator after this firmware signals READY; firmware then presents a token
 * so the compare is in flight.
 *
 * Checks:
 *   CHK-PIC-CLAIM  : the ISR claims the fault source
 *   CHK-PIC-FAULT  : the secure-disable fault bit is set
 *   CHK-PIC-MASK   : after masking, the ISR does not re-enter, and the source
 *                    is still pending at both ends of the quiet window
 */

#include <stdint.h>

#include "efuse_fw_test_common.h"
#include "sep_outbound_filter.h"
#include "sep_mailbox.h"
#include "sep_pic.h"
#include "sep_scratch_drv.h"

#define CSR_MEIHAP 0xFC8
#define PIC_TOKEN_FAULT 40u
#define READY_MARKER 0xE9050040u
#define SCRATCH_READY 0u
#define ISR_WAIT_ITERS 200000
#define STORM_CHECK_ITERS 4096
#define PRESENT_TRIES 8

static volatile uint32_t g_isr_count;
static volatile uint32_t g_claim_id;
static volatile uint32_t g_fault;

void __attribute__((interrupt("machine"))) token_fault_isr(void) {
    uint32_t meihap;
    __asm__ volatile("csrr %0, %1" : "=r"(meihap) : "i"(CSR_MEIHAP));
    g_claim_id = (meihap >> 2) & 0xFFu;
    g_fault = READ_REG(SEP_TOP_EFUSE_MMR_TOKEN_MATCH_FAULT_BASE_ADDR);
    pic_disable_source(PIC_TOKEN_FAULT);
    g_isr_count++;
    __asm__ volatile("fence" ::: "memory");
}

static void present_sec_disable(void) {
    const uint32_t token[SEP_TOP_EFUSE_MMR_SEC_DISABLE_TOKEN_I_NUM] = {1u};
    for (uint32_t i = 0; i < SEP_TOP_EFUSE_MMR_SEC_DISABLE_TOKEN_I_NUM; i++) {
        WRITE_REG(SEP_TOP_EFUSE_MMR_SEC_DISABLE_TOKEN_I_BASE_ADDR(i), token[i]);
    }
    WRITE_REG(SEP_TOP_EFUSE_MMR_TOKEN_EOP_BASE_ADDR,
              EFUSE_MMR__TOKEN_EOP__SECURE_DISABLE_TOKEN_GO_bm);
}

int main(void) {
    int errors = 0;
    uint32_t i;

    sep_outbound_filter_init();
    sep_mbx_puts("SEP token-match fault PIC test\n");

    pic_register_handler(PIC_TOKEN_FAULT, token_fault_isr);
    pic_set_gateway(PIC_TOKEN_FAULT, 0, 0);
    pic_set_priority(PIC_TOKEN_FAULT, 1);
    pic_enable_source(PIC_TOKEN_FAULT);
    pic_enable_interrupts();

    g_isr_count = 0;
    g_claim_id = 0;
    g_fault = 0;
    sep_scratch_wr(SCRATCH_READY, READY_MARKER);
    sep_mbx_puts("STEP PIC 40 armed; READY\n");

    for (i = 0; i < PRESENT_TRIES && g_isr_count == 0; i++) {
        present_sec_disable();
    }

    for (i = 0; i < ISR_WAIT_ITERS && g_isr_count == 0; i++) {
        __asm__ volatile("wfi");
    }

    if (g_isr_count == 0) {
        sep_mbx_puts("FAIL: PIC source 40 ISR never reached the CPU\n");
        errors++;
    } else if (g_claim_id != PIC_TOKEN_FAULT) {
        sep_mbx_puts("FAIL: PIC claim id was not 40\n");
        errors++;
    } else {
        sep_mbx_puts("CHK-PIC-CLAIM PASS: ISR claim id == 40\n");
    }

    if ((g_fault & EFUSE_MMR__TOKEN_MATCH_FAULT__SECURE_DISABLE_TOKEN_FAULT_bm) == 0) {
        sep_mbx_puts("FAIL: TOKEN_MATCH_FAULT secure-disable bit not set\n");
        errors++;
    } else {
        sep_mbx_puts("CHK-PIC-FAULT PASS: SEC_DISABLE sticky bit set\n");
    }

    if (g_isr_count == 0) {
        /* The mask claim needs a delivered interrupt to have been masked. With
         * no delivery the quiet window below is quiet for the wrong reason. */
        sep_mbx_puts("FAIL: CHK-PIC-MASK not evaluated; no ISR was delivered\n");
        errors++;
    } else {
        uint32_t before = g_isr_count;
        /* The fault clears only on reset. Sample the pending state at both
         * ends of the quiet window so a request that drops during it fails. */
        uint32_t pending_before = pic_source_pending(PIC_TOKEN_FAULT);
        for (i = 0; i < STORM_CHECK_ITERS; i++) {
            __asm__ volatile("nop");
        }
        uint32_t pending_after = pic_source_pending(PIC_TOKEN_FAULT);
        if (!pending_before || !pending_after) {
            sep_mbx_puts("FAIL: PIC 40 not requesting across the mask window\n");
            errors++;
        } else if (g_isr_count != before) {
            sep_mbx_puts("FAIL: PIC 40 re-entered after mask\n");
            errors++;
        } else {
            sep_mbx_puts("CHK-PIC-MASK PASS: source 40 still requesting, meie[40] "
                         "mask stopped re-entry\n");
        }
    }

    return errors;
}
