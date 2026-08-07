/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_efuse_km_axil.c
 * @brief SEP-TB KM CPU -> real eFuse controller routing/remap test (eFuse Suite 10.1).
 *
 * Runs as the KM ROM image inside the SEP UVM testbench (loaded via
 * +KM_ROM_HEX_FILE). Unlike the KM block-level test_efuse_axil.c (which hits a
 * dumb behavioural RAM responder), here the KM CPU drives the REAL
 * efuse_interface_controller through:
 *
 *   KM CPU store/load @ KM-local 0x0001_1xxx
 *     -> km_axi_lite_xbar master port 8
 *     -> key_manager.sv addr[31:12] remap to 0x1093_0xxx
 *     -> u_km_efuse_axi_lite_mux (slv1 = KM)
 *     -> efuse_interface_controller host axil_req_i
 *
 * Phase 1 (this file): routing/remap correctness + anti-aliasing + write path,
 * using ONLY side-effect-safe targets in the real controller:
 *   - MAP  read : CHIPLET_UID word0      (preloaded shadow field, benign read)
 *   - CTRL read : INTERFACE_CTRL_STATUS  (controller CSR, benign read)
 *   - MMR  write+read : RMA_SIP_TOKEN_I_0 (plain RW token-input CSR, benign)
 * (LOCKS / PROGRAM_CTRL / READ_CTRL are deliberately avoided — they have
 *  functional side effects in the real controller.)
 *
 * Results are reported to the SEP host over the KM<->SEP hardware mailbox as a
 * raw word frame (separator on the last word). The SEP UVM drains it with
 * km_mbox_read_response() and cross-checks every value SEP-side at 0x1093_0xxx.
 *
 * Frame format (6 words, separator on word 5):
 *   [0] MAGIC  = 0xEF11_5EED
 *   [1] STATUS : FW self-check bits — bit0=MMR write/readback matched,
 *               bit1=fuse-sense completed (efuse_sense_done seen)
 *   [2] MAP_RD : CHIPLET_UID word0 readback
 *   [3] CTRL_RD: INTERFACE_CTRL_STATUS readback
 *   [4] MMR_RD : RMA_SIP_TOKEN_I_0 readback (== sentinel if write routed OK)
 *   [5] END    = 0xEF11_E0D0   (separator-tagged)
 *
 * Permission parity across host classes and LC states is Phase 2, covered by
 * test_efuse_km_perm: it needs the UVM to set lock/secure_tm/LC preconditions and
 * to gate each access, so it is a UVM-driven agent rather than a fixed sequence.
 *
 * Build:  make -f ocah.mk ocah-dv-fw-tests TARGET=key_manager TEST=test_efuse_km_axil
 * Output: dv/fw/build/tests/test_efuse_km_axil/test_efuse_km_axil.rom.parhex
 *
 * NOTE: This file lives in sep_images/ and is built for the SEP UVM testbench,
 * NOT the KM block-level cocotb testbench.  It uses the mailbox protocol to
 * report results to the SEP host and requires the real eFuse controller.
 */

#include <stdint.h>
#include "key_manager_addr.h"     /* KEY_MANAGER_OTP_EFUSE_* register addresses */
#include "efuse_interface_ctrl.h" /* CTRL_STATUS sense-done field mask */
#include "rom_mailbox.h"          /* rom_mailbox_write_data / set_write_separator / space */

/* ---- Report frame constants ---- */
#define KM_EFUSE_ALIVE 0xA11FE5EEu /* boot heartbeat, sent before any eFuse access */
#define KM_EFUSE_MAGIC 0xEF115EEDu
#define KM_EFUSE_END 0xEF11E0D0u

/* ---- Benign routing targets (KM-local addresses) ---- */
#define MAP_RD_ADDR KEY_MANAGER_OTP_EFUSE_MAP_CHIPLET_UID_BASE_ADDR /* 0x0001_10C8 */
#define CTRL_RD_ADDR \
    KEY_MANAGER_OTP_EFUSE_CTRL_EFUSE_INTERFACE_CTRL_STATUS_BASE_ADDR       /* 0x0001_1400 */
#define MMR_RW_ADDR KEY_MANAGER_OTP_EFUSE_MMR_RMA_SIP_TOKEN_I_BASE_ADDR(0) /* 0x0001_1500 */

/* Distinctive sentinel for the MMR write-path check (unlikely to collide with
 * any preloaded token value). */
#define MMR_SENTINEL 0xC0FFEE05u

/* CTRL_STATUS.efuse_sense_done bit (controller has completed fuse sense). */
#define SENSE_DONE_MASK EFUSE_INTERFACE_CTRL__EFUSE_INTERFACE_CTRL_STATUS__EFUSE_SENSE_DONE_bm

/* Bound on the sense-done poll so a stuck controller fails fast instead of
 * hanging the simulation. */
#define SENSE_POLL_LIMIT 100000u

static inline void reg_write32(uint32_t addr, uint32_t val) {
    *(volatile uint32_t *)addr = val;
}

static inline uint32_t reg_read32(uint32_t addr) {
    return *(volatile uint32_t *)addr;
}

/* Push one word to the SEP-facing mailbox, waiting (bounded) for outbound FIFO
 * space. The spin is bounded so a wedged/full mailbox cannot hang the CPU and
 * mask whether the KM reached this point. */
static void mbox_send(uint32_t word, int last) {
    uint32_t guard = 1000000u;
    while ((rom_mailbox_outbound_space_available_read() == 0u) && (guard != 0u)) {
        guard--;
    }
    if (last) {
        rom_mailbox_set_write_separator(); /* tag this word as end-of-message */
    }
    rom_mailbox_write_data(word);
}

int main(void) {
    uint32_t map_rd;
    uint32_t ctrl_rd;
    uint32_t mmr_rd;
    uint32_t status = 0u;
    uint32_t sense_ok = 0u;
    uint32_t i;

    /* Start from a clean mailbox so the SEP side sees only our frame. */
    rom_mailbox_flush();

    /* Liveness heartbeat — sent BEFORE any eFuse access (1-word frame). Lets the
     * SEP host distinguish "KM not running / mailbox path broken" (no heartbeat)
     * from "KM hung on its first eFuse access" (heartbeat seen, data frame not). */
    mbox_send(KM_EFUSE_ALIVE, 1);

    /* Wait for the real controller to finish fuse sense before touching the
     * shadow map (pre-sense shadow access is boot-gated). CTRL CSRs are
     * readable throughout, so poll the sense-done status bit. */
    for (i = 0u; i < SENSE_POLL_LIMIT; i++) {
        if (reg_read32(CTRL_RD_ADDR) & SENSE_DONE_MASK) {
            sense_ok = 1u;
            break;
        }
    }

    /* --- Routing reads: each access remaps to its own 0x1093_0xxx region --- */
    map_rd = reg_read32(MAP_RD_ADDR);   /* -> 0x1093_00C8 (MAP/shadow)  */
    ctrl_rd = reg_read32(CTRL_RD_ADDR); /* -> 0x1093_0400 (CTRL CSR)    */

    /* --- Write path: benign RW token-input CSR in the MMR region --- */
    reg_write32(MMR_RW_ADDR, MMR_SENTINEL); /* -> 0x1093_0500 (MMR)       */
    mmr_rd = reg_read32(MMR_RW_ADDR);

    /* FW-side self-check, reported in the status word:
     *   bit0 = MMR write/readback round-tripped through the mux+remap
     *   bit1 = fuse-sense completed (efuse_sense_done seen before the poll limit) */
    status = ((mmr_rd == MMR_SENTINEL) ? 0x1u : 0x0u) | (sense_ok ? 0x2u : 0x0u);

    /* --- Report to the SEP host over the mailbox --- */
    mbox_send(KM_EFUSE_MAGIC, 0);
    mbox_send(status, 0);
    mbox_send(map_rd, 0);
    mbox_send(ctrl_rd, 0);
    mbox_send(mmr_rd, 0);
    mbox_send(KM_EFUSE_END, 1); /* separator-tagged final word */

    /* Idle; the SEP UVM completes the test after draining the frame. */
    for (;;) {
        /* park */
    }
    return 0;
}
