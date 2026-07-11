/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file rom_isr.c
 * @brief ISR dispatch framework implementation
 *
 * Provides the rom_irq() C entry point (overrides the weak symbol in crt0.s),
 * KMCSR sticky-error dispatch, mailbox FIFO drain/fill, EBREAK/bus-error
 * handlers, and fault trigger utilities.
 */

#include "rom_defs.h"
#include "rom_isr.h"
#include "irq_common.h"
#include "rom_picorv32.h"
#include "rom_msgbuf.h"
#include "rom_sideload.h"
#include "rom_mailbox.h"
#include "rom_kmcsr.h"
#include "rom_otp.h"
#include "rom_boot.h"

#include "rom_state.h"
#include "rom_msg_tx.h"

/*===========================================================================
 * ABR ML-KEM Shared-Key Notify State
 *===========================================================================*/

/**
 * @brief Pending-notify flag set by the ABR shared-key ISR handler.
 *
 * The ISR (sole writer) sets this to 1 when the bit-5 shared-key IRQ fires.
 * The main loop (sole reader) samples and clears it inside a maskirq window.
 * Declared volatile so the compiler does not cache it across the ISR boundary.
 */
volatile uint8_t g_abr_sk_notify_pending;

/*===========================================================================
 * rom_irq() — C ISR entry point (overrides weak symbol in crt0.s)
 *===========================================================================*/

/**
 * @brief Top-level interrupt handler dispatching by PicoRV32 IRQ bitmask.
 *
 * Priority: EBREAK/illegal > bus error > KMCSR sticky errors > mailbox.
 * Any unrecognised IRQ bits trigger an unrecoverable fault.
 *
 * @param[in,out] frame Saved IRQ frame. `frame->ret_addr` contains the
 *                      return address with PicoRV32's compressed-width flag.
 */
void rom_irq(rom_irq_frame_t *frame) {
    uint32_t irq_mask = frame->irq_mask;

    if (irq_mask & PICORV32_IRQ_EBREAK) rom_isr_ebreak(frame);
    if (irq_mask & PICORV32_IRQ_BUSERR) rom_isr_buserr(frame);
    if (irq_mask & PICORV32_IRQ_KMCSR) rom_isr_kmcsr();
    if (irq_mask & PICORV32_IRQ_MBOX) rom_isr_mailbox();
    if (irq_mask & PICORV32_IRQ_ABR_SHAREDKEY) rom_isr_abr_sharedkey();

    if (irq_mask & ~(uint32_t)PICORV32_IRQ_KNOWN_MASK)
        rom_trigger_unrecoverable(ROM_KM_UFAULT_SPURIOUS_IRQ);
}

/*===========================================================================
 * EBREAK / Illegal Instruction Handler
 *===========================================================================*/

/**
 * @brief Handle EBREAK or illegal instruction trap.
 *
 * Decodes the faulting instruction and triggers UFAULT_EBREAK for a
 * recognised EBREAK/C.EBREAK, or UFAULT_ILLEGAL_INSN otherwise.
 *
 * PicoRV32 convention for frame->ret_addr (q0):
 *   bit 0 clear → 32-bit insn, faulting PC = ret_addr - 4
 *   bit 0 set   → 16-bit insn, faulting PC = ret_addr - 3
 *
 * Instruction memory is read in 16-bit halves to avoid misaligned-load
 * traps (irq_active is set, so any trap is fatal).
 *
 * @param[in] frame Saved IRQ frame; `ret_addr` encodes the return address and
 *                  instruction-width flag as above.
 */
__attribute__((cold)) void rom_isr_ebreak(rom_irq_frame_t *frame) {
    uint32_t ret_addr = frame->ret_addr;
    uint32_t compressed = ret_addr & 1u;
    uint32_t pc = compressed ? (ret_addr - 3u) : (ret_addr - 4u);

    uint32_t insn = *(volatile uint16_t *)pc;
    int is_32bit = ((insn & 3u) == 3u);
    if (is_32bit) insn |= (uint32_t)(*(volatile uint16_t *)(pc + 2u)) << 16;

    /*
     * Consistency check (from official PicoRV32 ISR convention):
     * bit 0 of the return address encodes instruction width.  If it
     * disagrees with the decoded opcode width, something is wrong and
     * we cannot trust the decoded instruction.
     */
    if (is_32bit == (int)compressed) rom_trigger_unrecoverable(ROM_KM_UFAULT_ILLEGAL_INSN);

    if (insn == ROM_KM_EBREAK_OPCODE || insn == ROM_KM_C_EBREAK_OPCODE)
        rom_trigger_unrecoverable(ROM_KM_UFAULT_EBREAK);

    rom_trigger_unrecoverable(ROM_KM_UFAULT_ILLEGAL_INSN);
}

/*===========================================================================
 * Bus Error Handler
 *===========================================================================*/

/**
 * @brief Handle AXI bus-error trap.
 *
 * Always triggers an unrecoverable fault.
 *
 * @param[in] regs Saved register file (unused).
 */
__attribute__((cold)) void rom_isr_buserr(rom_irq_frame_t *frame) {
    (void)frame;
    rom_trigger_unrecoverable(ROM_KM_UFAULT_BUS_ERROR);
}

/*===========================================================================
 * KMCSR Sticky-Error Dispatch
 *===========================================================================*/

/**
 * @brief Decode KMCSR IRQ_STATUS and route each sticky error to its handler.
 *
 */
__attribute__((cold)) void rom_isr_kmcsr(void) {
    km_csr__irq_status_reg_t status;
    km_csr__irq_enable_reg_t enable;
    status.w = rom_kmcsr_irq_status_read();
    enable.w = rom_kmcsr_irq_enable_read();

    if (status.f.wipe_state && enable.f.wipe_state_en)
        rom_trigger_unrecoverable(ROM_KM_UFAULT_WIPE_STATE);

    if (status.f.rom_parity_err && enable.f.rom_parity_en)
        rom_trigger_unrecoverable(ROM_KM_UFAULT_ROM_PARITY);

    if (status.f.sram_parity_err && enable.f.sram_parity_en)
        rom_trigger_unrecoverable(ROM_KM_UFAULT_SRAM_PARITY);

    if (status.f.rom_write_err && enable.f.rom_write_en)
        rom_trigger_unrecoverable(ROM_KM_UFAULT_ROM_WRITE);

    if (status.f.sram_write_lock_err && enable.f.sram_write_lock_en)
        rom_trigger_unrecoverable(ROM_KM_UFAULT_SRAM_WRITE_LOCK);

    if (status.f.axi_decerr && enable.f.axi_decerr_en)
        rom_trigger_unrecoverable(ROM_KM_UFAULT_AXI_DECERR);

    if (status.f.axi_slverr && enable.f.axi_slverr_en)
        rom_trigger_unrecoverable(ROM_KM_UFAULT_AXI_SLVERR);

    if (status.f.drbg_err && enable.f.drbg_err_en)
        rom_trigger_unrecoverable(ROM_KM_UFAULT_DRBG_ERR);

    if (status.f.otp_sigint && enable.f.otp_sigint_en)
        rom_trigger_unrecoverable(ROM_KM_UFAULT_OTP_SIGINT);

    if (status.f.exec_violation && enable.f.exec_violation_en)
        rom_trigger_unrecoverable(ROM_KM_UFAULT_EXEC);

    if (status.f.otp_change && enable.f.otp_change_en) {
        uint32_t changed = rom_otp_get_change_status();
        rom_otp_on_change(changed);
        rom_otp_clear_change_status(changed);
    }
}

/*===========================================================================
 * Mailbox ISR
 *===========================================================================*/

/**
 * @brief Flush mailbox FIFOs and software buffers, reset sequence numbers.
 *
 * Used by error recovery paths within the mailbox ISR.
 *
 * @param[in] flush_fifos If non-zero, also flush hardware FIFOs via CTRL.flush.
 */
__attribute__((cold)) static void mbox_flush_and_reset(int flush_fifos) {
    if (flush_fifos) rom_mailbox_flush();

    rom_msgbuf_flush(&rom_rx_msgbuf);
    rom_msgbuf_flush(&rom_tx_msgbuf);
    rom_cmd_seq_num = 0;
    rom_resp_seq_num = 0;
    rom_mailbox_enable_inbound_irq();
}

/**
 * @brief Enable the outbound write-space-available mailbox IRQ.
 *
 * Ensures the mailbox ISR will run when the outbound FIFO has space so
 * the TX buffer is drained promptly.  Used by the TX path after enqueuing
 * a frame and when blocking on a full TX buffer.
 */
void rom_mailbox_enable_outbound_drain_irq(void) {
    km_mailbox_km__irq_enable_reg_t en;
    en.w = rom_mailbox_irq_enable_read();
    en.f.outbound_write_space_avail_en = 1;
    rom_mailbox_irq_enable_write(en.w);
}

/**
 * @brief Disable the outbound write-space-available mailbox IRQ.
 *
 * Called by the mailbox ISR when the TX buffer is empty or a complete
 * frame has just been sent, to avoid repeated interrupts until the
 * main loop enqueues another frame.
 */
void rom_mailbox_disable_outbound_drain_irq(void) {
    km_mailbox_km__irq_enable_reg_t en;
    en.w = rom_mailbox_irq_enable_read();
    en.f.outbound_write_space_avail_en = 0;
    rom_mailbox_irq_enable_write(en.w);
}

/**
 * @brief Enable the inbound data-available mailbox IRQ.
 *
 * Called by the main loop after consuming an RX frame so the ISR can
 * drain the inbound FIFO when space is available.
 */
void rom_mailbox_enable_inbound_irq(void) {
    km_mailbox_km__irq_enable_reg_t en;
    en.w = rom_mailbox_irq_enable_read();
    en.f.inbound_read_data_avail_en = 1;
    rom_mailbox_irq_enable_write(en.w);
}

/**
 * @brief Disable the inbound data-available mailbox IRQ.
 *
 * Called by the mailbox ISR when the RX buffer cannot accept more words
 * (buffer full or frame already present) to avoid repeated interrupts.
 */
void rom_mailbox_disable_inbound_irq(void) {
    km_mailbox_km__irq_enable_reg_t en;
    en.w = rom_mailbox_irq_enable_read();
    en.f.inbound_read_data_avail_en = 0;
    rom_mailbox_irq_enable_write(en.w);
}

/**
 * @brief Send a recoverable fault response directly to the outgoing FIFO.
 *
 * Sets RECOVERABLE_ERR in KMCSR and writes RESP_RECOVERABLE_FAULT to the
 * outgoing mailbox FIFO (bypasses TX buffer).
 *
 * @param[in] fault_code Fault identifier (ROM_KM_RFAULT_*).
 */
__attribute__((cold)) static void rom_trigger_recoverable_direct(int8_t fault_code) {
    rom_kmcsr_recoverable_err_bit_write(1);
    uint32_t payload = (uint32_t)(int32_t)fault_code;
    rom_msg_tx_send_direct(ROM_KM_RESP_RECOVERABLE_FAULT, &payload, 1);
}

/**
 * @brief Service the mailbox interrupt.
 *
 * Checks error conditions first (overflow, underflow, SEP flush), then
 * drains the TX buffer into the outbound FIFO, then drains the inbound
 * FIFO into the RX buffer.
 */
void rom_isr_mailbox(void) {
    km_mailbox_km__irq_status_reg_t irq_sts;
    km_mailbox_km__irq_enable_reg_t irq_en;
    irq_sts.w = rom_mailbox_irq_status_read();
    irq_en.w = rom_mailbox_irq_enable_read();

    /* --- Error conditions (checked first) --- */

    if (irq_sts.f.outbound_overflow && irq_en.f.outbound_overflow_en) {
        mbox_flush_and_reset(1);
        km_mailbox_km__irq_status_reg_t w1c = {0};
        w1c.f.outbound_overflow = 1;
        rom_mailbox_irq_status_clear(w1c.w);
        rom_trigger_recoverable_direct(ROM_KM_RFAULT_MBOX_OVERFLOW);
        return;
    }

    if (irq_sts.f.inbound_underflow && irq_en.f.inbound_underflow_en) {
        mbox_flush_and_reset(1);
        km_mailbox_km__irq_status_reg_t w1c = {0};
        w1c.f.inbound_underflow = 1;
        rom_mailbox_irq_status_clear(w1c.w);
        rom_trigger_recoverable_direct(ROM_KM_RFAULT_MBOX_UNDERFLOW);
        return;
    }

    if (irq_sts.f.flushed_by_sep && irq_en.f.flushed_by_sep_en) {
        mbox_flush_and_reset(0);
        km_mailbox_km__irq_status_reg_t w1c = {0};
        w1c.f.flushed_by_sep = 1;
        rom_mailbox_irq_status_clear(w1c.w);
        rom_trigger_recoverable_direct(ROM_KM_RFAULT_FLUSHED_BY_SEP);
        return;
    }

    /* --- Drain TX buffer to outbound FIFO ---
     * Single frame only: transfer min(FIFO free space, remaining frame length).
     * If the frame is larger than the FIFO, the rest is sent on the next IRQ.
     */
    if (irq_sts.f.outbound_write_space_avail && irq_en.f.outbound_write_space_avail_en) {
        uint32_t n_fifo_free = rom_mailbox_outbound_space_available_read();

        if (rom_msgbuf_frame_available(&rom_tx_msgbuf) && n_fifo_free > 0u) {
            uint16_t start, length;
            if (rom_msgbuf_peek_frame(&rom_tx_msgbuf, &start, &length) == 0) {
                uint32_t n_send = (uint32_t)length < n_fifo_free ? (uint32_t)length : n_fifo_free;

                for (uint32_t i = 0u; i < n_send; i++) {
                    uint32_t word;
                    rom_msgbuf_pop_word(&rom_tx_msgbuf, &word);

                    if (i == n_send - 1u && n_send == (uint32_t)length)
                        rom_mailbox_set_write_separator();

                    rom_mailbox_write_data(word);
                }
                if (rom_msgbuf_frame_empty(&rom_tx_msgbuf))
                    rom_msgbuf_consume_frame(&rom_tx_msgbuf);
            }
        }
        if (!rom_msgbuf_frame_available(&rom_tx_msgbuf)) rom_mailbox_disable_outbound_drain_irq();
    }

    /* --- Drain inbound FIFO into RX buffer ---
     * Pull mailbox data into the RX buffer while it can take more. If data
     * remains in the FIFO afterward, disable the inbound IRQ only when
     * software must make progress first (complete frame buffered or RX buffer
     * out of space). When a partial frame still has room, leave the IRQ
     * enabled so residual FIFO data continues draining.
     */
    if (irq_sts.f.inbound_read_data_avail && irq_en.f.inbound_read_data_avail_en) {
        uint32_t n_fifo = rom_mailbox_inbound_depth_read();
        uint16_t n_space = rom_msgbuf_space_available(&rom_rx_msgbuf);
        uint32_t can_accept_frame = (uint32_t)rom_msgbuf_can_accept_frame(&rom_rx_msgbuf);
        uint32_t n_buf = can_accept_frame ? (uint32_t)n_space : 0u;
        uint32_t n = n_fifo < n_buf ? n_fifo : n_buf;

        for (uint32_t i = 0u; i < n; i++) {
            uint32_t word = rom_mailbox_read_data();
            uint8_t sep = rom_mailbox_inbound_separator();
            rom_msgbuf_write_word(&rom_rx_msgbuf, word, sep);
            if (sep) break; /* Frame complete; stop draining until main loop consumes it */
        }
        if (!rom_mailbox_inbound_empty() && (rom_msgbuf_frame_available(&rom_rx_msgbuf) ||
                                             rom_msgbuf_space_available(&rom_rx_msgbuf) == 0u))
            rom_mailbox_disable_inbound_irq();
    }
}

/*===========================================================================
 * ABR ML-KEM Shared-Key ISR Handler
 *===========================================================================*/

/**
 * @brief Service the ABR ML-KEM shared-key IRQ (bit 5).
 *
 * Acknowledges the interrupt by clearing the sticky IRQ_STATUS bit (W1C) and
 * flags g_abr_sk_notify_pending for the main loop. Does not consume the key:
 * KEY_VALID stays set for the SEP-issued CMD_ABR_SK_TRANSFER.
 */
void rom_isr_abr_sharedkey(void) {
    rom_abr_mlkem_sharedkey_irq_status_clear();
    g_abr_sk_notify_pending = 1u;
}

/*===========================================================================
 * Fault Triggers
 *===========================================================================*/

/**
 * @brief Enter unrecoverable fault path: purge keys, report fault, optional shred, halt.
 *
 * @param[in] fault_code Fault identifier (ROM_KM_UFAULT_*).
 */
__attribute__((noreturn, cold)) void rom_trigger_unrecoverable(int8_t fault_code) {
    int do_shred = rom_unrec_wipe_enabled();

    if (do_shred) {
        /* Purge all crypto engine sideload keys (no DRBG reseed in fault path). */
        rom_hmac_shred_key(&rom_prng_state, 0);
        rom_kmac_shred_key(&rom_prng_state, 0);
        rom_aes_shred_key(&rom_prng_state, 0);
        rom_otbn_shred_key(&rom_prng_state, 0);
        rom_abr_mldsa_seed_shred_key(&rom_prng_state, 0);
        rom_abr_mlkem_seed_d_shred_key(&rom_prng_state, 0);
        rom_abr_mlkem_seed_z_shred_key(&rom_prng_state, 0);
        rom_abr_mlkem_msg_shred_key(&rom_prng_state, 0);
        rom_abr_mlkem_sharedkey_zeroize();
    }

    rom_mailbox_flush();

    uint32_t payload = (uint32_t)(int32_t)fault_code;
    rom_msg_tx_send_direct(ROM_KM_RESP_UNRECOVERABLE_FAULT, &payload, 1);

    if (do_shred) rom_wipe_shred_sram();

    rom_picorv32_halt_trap();
}

/**
 * @brief Signal a recoverable fault.
 *
 * Sets KMCSR RECOVERABLE_ERR and enqueues the fault response in the
 * TX buffer.
 *
 * @param[in] fault_code Fault identifier (ROM_KM_RFAULT_*).
 */
__attribute__((cold)) void rom_trigger_recoverable(int8_t fault_code) {
    rom_kmcsr_recoverable_err_bit_write(1);
    uint32_t payload = (uint32_t)(int32_t)fault_code;
    rom_msg_tx_send(ROM_KM_RESP_RECOVERABLE_FAULT, &payload, 1);
}
