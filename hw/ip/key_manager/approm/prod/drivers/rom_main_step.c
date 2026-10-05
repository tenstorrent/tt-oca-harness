/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_main_step.c
 * @brief Key Manager main-loop step.
 *
 * Implements one iteration of the KM firmware main loop. The top-level
 * firmware entry point lives in `rom_main.c` and repeatedly calls
 * `rom_main_step()` after boot initialization.
 */

#include "rom_main_step.h"
#include "rom_defs.h"
#include "rom_msg_rx.h"
#include "rom_msg_tx.h"
#include "rom_msgbuf.h"
#include "rom_picorv32.h"
#include "rom_isr.h"
#include "rom_state.h"
#include <stddef.h>

/*===========================================================================
 * rom_main_step() — Main event loop step
 *===========================================================================*/

/**
 * @brief Run one main-loop iteration.
 *
 * The RX path may also need service when no complete frame is buffered yet
 * (for example, a partial-frame overflow recovery or re-arming inbound IRQ
 * after a mailbox drain race). Therefore the loop runs `rom_msg_rx_process()`
 * every iteration.
 *
 * Both the mailbox IRQ and the ABR shared-key IRQ are masked around the
 * notify-flag sample+clear and the sleep decision so two races are closed:
 *   (a) lost-update: an ISR set between sample and clear cannot be silently
 *       dropped (the ISR is masked for the duration of the window).
 *   (b) lost-wakeup: a pending notify cannot leave the CPU sleeping in
 *       waitirq (notify is sampled before waitirq, inside the same window).
 *
 * rom_msg_tx_send() is called outside the masked region because it manages
 * its own mailbox-IRQ guard and may spin on FIFO drain.
 */
void rom_main_step(void) {
    rom_msg_rx_process();

    uint32_t saved_mask = rom_picorv32_maskirq(0xFFFFFFFFu);
    rom_picorv32_maskirq(saved_mask | ROM_KM_IRQ_MBOX_BIT | ROM_KM_IRQ_ABR_SHAREDKEY_BIT);

    uint8_t notify = g_abr_sk_notify_pending; /* atomic sample under mask */
    g_abr_sk_notify_pending = 0u;             /* atomic clear  under mask */

    if (notify == 0u && rom_msgbuf_frame_available(&rom_rx_msgbuf) == 0u) rom_picorv32_waitirq();

    rom_picorv32_maskirq(saved_mask);

    /* Send unsolicited notification outside the masked region. */
    if (notify) rom_msg_tx_send(ROM_KM_RESP_ABR_SHARED_KEY_READY, NULL, 0);
}
