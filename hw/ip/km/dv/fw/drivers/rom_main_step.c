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
#include "rom_msgbuf.h"
#include "rom_picorv32.h"
#include "rom_state.h"

/*===========================================================================
 * rom_main_step() — Main event loop step (FR-0000-242, FR-0000-243)
 *===========================================================================*/

/**
 * @brief Run one main-loop iteration.
 *
 * The RX path may also need service when no complete frame is buffered yet
 * (for example, a partial-frame overflow recovery or re-arming inbound IRQ
 * after a mailbox drain race). Therefore the loop runs `rom_msg_rx_process()`
 * every iteration, then masks only the mailbox IRQ around the empty-check /
 * `waitirq` pair so the mailbox ISR cannot fill `rom_rx_msgbuf` in the gap and
 * leave the CPU sleeping with buffered work already available.
 */
void rom_main_step(void)
{
    rom_msg_rx_process();
    uint32_t saved_mask = rom_picorv32_maskirq(0xFFFFFFFFu);
    rom_picorv32_maskirq(saved_mask | ROM_KM_IRQ_MBOX_BIT);
    if (rom_msgbuf_frame_available(&rom_rx_msgbuf) == 0u)
        rom_picorv32_waitirq();
    rom_picorv32_maskirq(saved_mask);
}
