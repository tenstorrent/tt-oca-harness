/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_boot.c
 * @brief Key Manager one-time boot sequence.
 *
 * Separated from `rom_main.c` so tests can link `rom_boot_init()`
 * without also linking production main-loop code.
 */

#include "rom_defs.h"
#include "rom_state.h"
#include "rom_boot.h"
#include "rom_drbg.h"
#include "rom_prng.h"
#include "rom_kpv.h"
#include "rom_sideload.h"
#include "rom_kmcsr.h"
#include "rom_mailbox.h"
#include "rom_msgbuf.h"
#include "rom_msg_tx.h"
#include "rom_keyreg.h"
#include "irq_common.h"
#include "rom_picorv32.h"
#include "key_manager_regs.h"
#include <stddef.h>
#include <stdint.h>

#ifndef ROM_KM_BOOT_WIPE_DEFAULT
#define ROM_KM_BOOT_WIPE_DEFAULT 1
#endif

#ifndef ROM_KM_UNREC_WIPE_DEFAULT
#define ROM_KM_UNREC_WIPE_DEFAULT 1
#endif

/** @brief Weak default hook: boot wipe is enabled. */
__attribute__((weak)) int rom_boot_wipe_enabled(void)
{
    return ROM_KM_BOOT_WIPE_DEFAULT;
}
/** @brief Weak default hook: unrecoverable-fault wipe is enabled. */
__attribute__((weak)) int rom_unrec_wipe_enabled(void)
{
    return ROM_KM_UNREC_WIPE_DEFAULT;
}

/**
 * @brief Runs one-time Key Manager boot initialization.
 *
 * Configures fault/IRQ state, initializes entropy and PRNG state, sets up
 * scramblers, optionally shreds key material regions, initializes software
 * state, and announces ready to SEP.
 */
void rom_boot_init(void)
{
    /* ----- FR-0000-171: Enable KMCSR fault IRQs ----- */

    KM_CSR_IRQ_ENABLE_REG_reg_u irq_en = {0};
    irq_en.f.rom_parity_en      = 1;
    irq_en.f.sram_parity_en     = 1;
    irq_en.f.rom_write_en       = 1;
    irq_en.f.sram_write_lock_en = 1;
    irq_en.f.axi_slverr_en      = 1;
    irq_en.f.axi_decerr_en      = 1;
    irq_en.f.drbg_err_en        = 1;
    irq_en.f.wipe_state_en      = 1;
    rom_kmcsr_irq_status_clear(0xFFFFFFFF);
    rom_kmcsr_irq_enable_write(irq_en.val);

    rom_picorv32_maskirq(0);

    /* ----- FR-0000-172: Init DRBG & seed firmware PRNG ----- */

    rom_drbg_init();
    rom_prng_seed(&rom_prng_state);

    /* ----- FR-0000-173: SRAM scrambler first-time init ----- */

    if (!rom_kmcsr_sram_scrambler_enable_bit_read()) {
        for (uint8_t i = 0; i < ROM_KM_SHRED_ITER + 1; i++)
            rom_kmcsr_sram_scrambler_key_write(rom_drbg_get_word());

        /* Enable + lock scrambler and restart from 0; never returns. */
        rom_boot_sram_restart();
    }

    /* ----- FR-0000-174: KPV scrambler init & shred all slots ----- */

    rom_kpv_init_scrambler();
    rom_kpv_scrambler_enable();
    rom_kpv_scrambler_lock();

    if (rom_boot_wipe_enabled()) {
        rom_kpv_shred_all(&rom_prng_state);

        /* ----- FR-0000-175: Shred all crypto engine sideload keys ----- */

        rom_hmac_shred_key(&rom_prng_state, 1);
        rom_kmac_shred_key(&rom_prng_state, 1);
        rom_aes_shred_key(&rom_prng_state, 1);
        rom_otbn_shred_key(&rom_prng_state, 1);
    }

    /* ----- FR-0000-176: Init message buffers & mailbox ----- */

    rom_msgbuf_init(&rom_rx_msgbuf);
    rom_msgbuf_init(&rom_tx_msgbuf);

    /* ----- FR-0000-176: Init key registry ----- */

    rom_keyreg_init(&rom_keyreg_state);

    /* ----- FR-0000-176: Init message sequence state ----- */

    rom_cmd_seq_num  = 0;
    rom_resp_seq_num = 0;

    /* Boot mailbox FIFO cleanup before clearing mailbox IRQ status. */
    rom_mailbox_flush();

    /* Clear any latched mailbox IRQ status */
    rom_mailbox_irq_status_clear(0xFFFFFFFF);

    /* Enable inbound data + error sources; keep outbound data IRQ off */
    KM_MAILBOX_KM_IRQ_ENABLE_REG_reg_u mbox_en = {0};
    mbox_en.f.inbound_read_data_avail_en = 1;
    mbox_en.f.outbound_overflow_en       = 1;
    mbox_en.f.inbound_underflow_en       = 1;
    mbox_en.f.flushed_by_sep_en          = 1;
    rom_mailbox_irq_enable_write(mbox_en.val);

    /* ----- FR-0000-176: Announce readiness to SEP ----- */

    rom_msg_tx_send(ROM_KM_RESP_KM_READY, NULL, 0);

    /* ----- Mark cold boot done (sticky until next cold reset; survives warm resets) ----- */

    rom_kmcsr_cold_boot_done_set();
}
