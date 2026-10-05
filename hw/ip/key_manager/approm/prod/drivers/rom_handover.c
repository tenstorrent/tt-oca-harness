/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_handover.c
 * @brief KM ROM-to-SRAM firmware handover sequence.
 *
 * Implements direct-FIFO firmware image streaming with CRC-32C verification,
 * sensitive-data locking, SRAM write-lock application, and the transition to
 * the stack-less assembly handoff (rom_handover_jump.S).
 */

#include "rom_handover.h"
#include "rom_defs.h"
#include "rom_state.h"
#include "rom_persist.h"
#include "rom_mailbox.h"
#include "rom_msgbuf.h"
#include "rom_msg_tx.h"
#include "rom_isr.h"
#include "rom_kmcsr.h"
#include "rom_otp.h"
#include "rom_sideload.h"
#include "rom_kpv.h"
#include "rom_keyreg.h"
#include "rom_picorv32.h"
#include "irq_common.h"
#include "key_manager_fw.h"

/*===========================================================================
 * Internal helpers
 *===========================================================================*/

/**
 * @brief Poll inbound FIFO until one word is available, then return it.
 *
 * The inbound mailbox IRQ is disabled while this function is active, so the
 * ISR will not consume FIFO words.  Spin-waits for the SEP to fill the FIFO.
 *
 * @return 32-bit data word from the inbound FIFO.
 */
static uint32_t fifo_read_word_blocking(void) {
    while (rom_mailbox_inbound_empty()) {
    }
    return rom_mailbox_read_data();
}

/**
 * @brief Send a RESP_CMD success frame directly to the outbound FIFO.
 *
 * Waits for the TX software buffer to drain (via ISR), then takes ownership
 * of the mailbox by disabling the inbound IRQ and masking CPU IRQs.  Sends the
 * confirmation frame synchronously via rom_msg_tx_send_direct(), then
 * re-enables the outbound drain IRQ and unmasks CPU IRQs so the ISR can drain
 * the new frame to the SEP.
 *
 * The inbound IRQ remains disabled after this function returns; callers that
 * need direct FIFO polling must keep it disabled.
 *
 * @param cmd_seq  Command sequence number to echo in the response.
 * @param cmd_id   Command ID to echo in the response.
 */
static void send_direct_success(uint8_t cmd_seq, uint8_t cmd_id) {
    /* Wait for any pending TX frames to be drained by the ISR. */
    rom_mailbox_enable_outbound_drain_irq();
    while (rom_msgbuf_frame_available(&rom_tx_msgbuf)) {
    }

    /* Disable inbound IRQ to prevent the ISR from consuming image words. */
    rom_mailbox_disable_inbound_irq();

    /* Mask CPU IRQs so the ISR cannot interfere with the direct FIFO write. */
    rom_picorv32_maskirq(0xFFFFFFFFu);

    /* Build and send RESP_CMD success directly to the outbound FIFO. */
    uint32_t resp_payload[3];
    resp_payload[0] = (uint32_t)cmd_seq;
    resp_payload[1] = (uint32_t)cmd_id;
    resp_payload[2] = (uint32_t)(uint8_t)ROM_KM_RC_SUCCESS;
    rom_msg_tx_send_direct(ROM_KM_RESP_CMD, resp_payload, 3);

    /* Re-enable outbound drain IRQ and unmask CPU so the ISR can forward the
     * confirmation frame from the hardware FIFO to the SEP. */
    rom_mailbox_enable_outbound_drain_irq();
    rom_picorv32_maskirq(0u);
}

/*===========================================================================
 * Public API
 *===========================================================================*/

/**
 * @brief Deny mutable firmware access to KPV key material.
 *
 * KPV key entry data has no warm reset and the KM-port scrambler descrambles
 * on read, so any live key would otherwise be plaintext-readable by mutable
 * firmware at the KPV KM-port base.  Provisioned keys are only write-locked
 * (lock_write) by the load path, not read-locked, so reads are not blocked
 * unless we act here.
 *
 * Walk every KPV slot, using the firmware key registry to tell live slots from
 * free ones:
 *   - Registered slot: set lock_use (read-lock).  lock_use is independent of
 *     lock_write, so this works on the already-write-locked key slots; the HW
 *     then returns zero for KM-port key reads.
 *   - Unregistered slot: shred it.  rom_kpv_shred_slot drives the hardware
 *     erase path, which is not blocked by the slot locks, so even a
 *     write-locked free slot (e.g. a revoked key) is wiped and its contents
 *     made unreadable.
 */
void rom_handover_lock_kpv_root_keys(void) {
    for (uint8_t slot = 0u; slot < ROM_KM_KPV_NUM_SLOTS; slot++) {
        if (rom_keyreg_get_handle(&rom_keyreg_state, slot) != ROM_KM_KEY_HANDLE_NULL) {
            rom_kpv_read_lock(slot);
        } else {
            rom_kpv_shred_slot(slot);
        }
    }
}

/**
 * @brief Lock sensitive data: OTP secrets, rom_persist region, KPV root keys.
 */
void rom_handover_lock_sensitive(void) {
    rom_otp_set_read_lock(ROM_KM_OTP_LOCK_SECRET_MASK);
    rom_persist_lock();
    rom_handover_lock_kpv_root_keys();
}

/**
 * @brief Shred all crypto-engine sideload key registers before handover.
 *
 * The HMAC/KMAC/AES/OTBN and Adams Bridge seed key-share register banks are
 * outside the SRAM address space, so the whole-SRAM scramble in
 * rom_handover_jump.S does not clear them. Overwrite each engine's key shares
 * with PRNG data and clear key_valid, and zeroize the ML-KEM shared key, so
 * mutable firmware cannot read any key material the ROM previously sideloaded
 * or any shared key delivered but not yet consumed.
 */
void rom_handover_shred_sideload_keys(void) {
    rom_hmac_shred_key(&rom_prng_state, 1);
    rom_kmac_shred_key(&rom_prng_state, 1);
    rom_aes_shred_key(&rom_prng_state, 1);
    rom_otbn_shred_key(&rom_prng_state, 1);
    rom_abr_mldsa_seed_shred_key(&rom_prng_state, 1);
    rom_abr_mlkem_seed_d_shred_key(&rom_prng_state, 1);
    rom_abr_mlkem_seed_z_shred_key(&rom_prng_state, 1);
    rom_abr_mlkem_msg_shred_key(&rom_prng_state, 1);
    rom_abr_mlkem_sharedkey_zeroize();
}

/**
 * @brief Final C-side handover steps: shred sideload keys, lock sensitive data,
 *        write-lock firmware SRAM, reseed PRNG, wait for the outbound FIFO to
 *        drain and flush the mailbox, disable IRQs, get PRNG seed, tail-call
 *        assembly handoff.
 */
__attribute__((noreturn)) void rom_handover_finish(uint32_t fw_size_bytes) {
    /* --- Step 1: shred crypto-engine sideload keys ---
     * The HMAC/KMAC/AES/OTBN and ABR seed key-share banks (and the ML-KEM
     * shared key) are outside SRAM, so the whole-SRAM scramble in
     * rom_handover_jump.S cannot reach them.  Overwrite them now — before IRQs
     * are disabled below, so a DRBG reseed fault is still caught — to deny
     * mutable firmware any ROM-sideloaded key material.
     */
    rom_handover_shred_sideload_keys();

    /* --- Step 2: lock sensitive data --- */
    rom_handover_lock_sensitive();

    /* --- Step 3: write-lock SRAM regions covering the firmware image ---
     * Compute number of SRAM_LOCK_REGION_BYTES regions occupied by the image
     * (round up).
     * The bounds-check in rom_cmd_sram_load_exec guarantees these regions are
     * disjoint from the ROM stack/data, so write-locking them cannot prevent
     * the scramble from erasing ROM private data.
     */
    uint32_t num_regions = (fw_size_bytes + SRAM_LOCK_REGION_BYTES - 1u) / SRAM_LOCK_REGION_BYTES;
    uint32_t fw_lock_mask = (num_regions < 32u) ? ((1u << num_regions) - 1u) : 0xFFFFFFFFu;
    rom_kmcsr_sram_lock_set(fw_lock_mask);

    /* --- Step 4: reseed the PRNG from the DRBG ---
     * Refresh the xoshiro128++ state with fresh entropy for the SRAM scramble
     * seed captured below.  Done here, before the IRQ-disable steps, so a DRBG
     * fault during the reseed is still reported via the KMCSR IRQ.
     */
    rom_prng_seed(&rom_prng_state);

    /* --- Step 5: disable all KMCSR IRQs and clear sticky status ---
     * Prevents spurious SRAM_WRITE_LOCK faults when the assembly scramble
     * routine writes to locked regions (hardware silently drops the writes but
     * still sets the sticky bit if the IRQ is enabled).
     */
    rom_kmcsr_irq_enable_write(0u);
    rom_kmcsr_irq_status_clear(0xFFFFFFFFu);

    /* --- Step 6: wait for the SEP to drain the outbound FIFO, then flush ---
     * The RESP_CMD confirmation was sent directly to the hardware outbound
     * FIFO by send_direct_success().  Spin until the outbound FIFO is
     * empty so the flush below cannot discard a confirmation the SEP has not
     * yet read.  Then flush both directions to erase any residual inbound
     * payload. */
    while (rom_mailbox_outbound_depth_read() != 0u) {
    }
    rom_mailbox_flush();

    /* --- Step 7: disable all mailbox IRQ enables --- */
    rom_mailbox_irq_enable_write(0u);

    /* --- Step 8: mask ALL CPU IRQs --- */
    rom_picorv32_maskirq(0xFFFFFFFFu);

    /* --- Step 9: capture PRNG seed for the scramble routine ---
     * Pass all four xoshiro128++ state words to the assembly so it can
     * generate a pseudo-random wipe pattern.
     */
    uint32_t s0 = rom_prng_state.s[0];
    uint32_t s1 = rom_prng_state.s[1];
    uint32_t s2 = rom_prng_state.s[2];
    uint32_t s3 = rom_prng_state.s[3];

    /* --- Step 10: tail-call stack-less assembly --- */
    rom_handover_jump(s0, s1, s2, s3);
}

/**
 * @brief Stream firmware image from mailbox FIFO, verify CRC-32C, then execute.
 */
__attribute__((noreturn)) void rom_handover_load_and_exec(uint8_t cmd_seq, uint32_t fw_words,
                                                          uint32_t load_limit) {
    /* --- Step 1: invalidate any previous load --- */
    rom_persist_set_sram_fw_size(0u);

    /* --- Step 2-3: send direct RESP_CMD confirmation to SEP ---
     * After this call, the inbound IRQ is disabled and we own the FIFO.
     */
    send_direct_success(cmd_seq, ROM_KM_CMD_SRAM_LOAD_EXEC);

    /* --- Step 4: stream firmware image into SRAM, compute CRC-32C ---
     * The inbound IRQ is disabled; we poll the FIFO directly.
     * Per-word guard: verify the destination never reaches load_limit
     * (the region-aligned stack boundary).  Triggers unrecoverable fault
     * if a misbehaving SEP over-streams.
     */
    volatile uint32_t *dest = (volatile uint32_t *)ROM_KM_SRAM_BASE;
    uint32_t crc_state = 0xFFFFFFFFu;

    for (uint32_t i = 0u; i < fw_words; i++) {
        uint32_t dest_addr = (uint32_t)(uintptr_t)dest;
        if (dest_addr >= load_limit) rom_trigger_unrecoverable(ROM_KM_UFAULT_FW_STACK_OVF);

        uint32_t word = fifo_read_word_blocking();
        crc_state = rom_picorv32_crc32c_word_update(crc_state, word);
        *dest++ = word;
    }

    /* Finalise CRC-32C: XOR with 0xFFFFFFFF. */
    uint32_t computed_crc = crc_state ^ 0xFFFFFFFFu;

    /* --- Step 5: read and verify the trailing CRC word (with separator) --- */
    uint32_t rx_crc = fifo_read_word_blocking();
    /* Consume separator status (read to clear; not used further). */
    (void)rom_mailbox_inbound_separator();

    if (rx_crc != computed_crc) rom_trigger_unrecoverable(ROM_KM_UFAULT_FW_CRC);

    /* --- Step 6: commit firmware size and execute handover --- */
    rom_persist_set_sram_fw_size(fw_words * 4u);
    rom_handover_finish(fw_words * 4u);
}

/**
 * @brief Send direct RESP_CMD success and execute handover for pre-loaded firmware.
 */
__attribute__((noreturn)) void rom_handover_exec_existing(uint8_t cmd_seq, uint32_t fw_size_bytes) {
    /* Send direct RESP_CMD success; inbound IRQ disabled after this. */
    send_direct_success(cmd_seq, ROM_KM_CMD_SRAM_EXEC);

    rom_handover_finish(fw_size_bytes);
}
