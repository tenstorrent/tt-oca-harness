/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_efuse_km_coexist.c
 * @brief KM CPU eFuse mux-coexistence driver.
 *
 * Runs as the KM ROM image in the SEP UVM testbench. After boot it announces
 * readiness over the mailbox, then FREE-RUNS a tight loop writing an incrementing
 * counter to the MMR token register through the real KM->eFuse path
 * (xbar port 8 -> remap -> u_km_efuse_axi_lite_mux -> controller).
 *
 * Meanwhile the UVM (SEP host on cpu_lsu) drives its own concurrent eFuse reads.
 * Both masters contend at u_km_efuse_axi_lite_mux. The UVM checks:
 *   - the KM counter (read back from MMR) advances  -> KM makes progress,
 *   - its own reads all complete                    -> host not starved,
 *   - a known reg (CHIPLET_UID) always reads its real value -> no cross-attribution,
 *   - the KM counter is monotonic non-decreasing    -> no torn/swapped responses.
 *
 * The KM never exits; the UVM ends the test.
 *
 * Build:  make -f ocah.mk ocah-dv-fw-tests TARGET=key_manager TEST=test_efuse_km_coexist
 * Output: dv/fw/build/tests/test_efuse_km_coexist/test_efuse_km_coexist.rom.parhex
 *
 * NOTE: This file lives in sep_images/ and is built for the SEP UVM testbench,
 * NOT the KM block-level cocotb testbench.  It uses the mailbox protocol and
 * requires a live SEP host sending the GO token on the inbound mailbox.
 */

#include <stdint.h>
#include "key_manager_addr.h" /* KEY_MANAGER_OTP_EFUSE_MMR_RMA_SIP_TOKEN_I_BASE_ADDR */
#include "rom_mailbox.h"

#define KM_READY_TOKEN 0xA11FE5EEu /* KM -> EL2 : ready (sent on outbound mailbox) */
#define EL2_GO_TOKEN 0x60600060u   /* EL2 -> KM : start the write loop (inbound)   */

/* Two KM-owned MMR registers carry an owner-tagged, incrementing pattern so the
 * EL2 host can validate KM progress AND response attribution (each read must
 * return its register's own tag byte). Payload is the 24-bit counter.
 * MMR0 is KM-local 0x0001_1500, MMR1 is KM-local 0x0001_1504. */
#define MMR0_ADDR KEY_MANAGER_OTP_EFUSE_MMR_RMA_SIP_TOKEN_I_BASE_ADDR(0)
#define MMR1_ADDR KEY_MANAGER_OTP_EFUSE_MMR_RMA_SIP_TOKEN_I_BASE_ADDR(1)
#define KM_TAG0 0xA5000000u
#define KM_TAG1 0x5A000000u
#define KM_PAYLOAD_MASK 0x00FFFFFFu

static inline void reg_write32(uint32_t addr, uint32_t val) {
    *(volatile uint32_t *)addr = val;
}

/* Blocking read of one inbound (EL2->KM) mailbox word. */
static uint32_t km_inbound_get(void) {
    while (rom_mailbox_inbound_empty() != 0u) {
        /* wait for the EL2 host to push a word */
    }
    return rom_mailbox_read_data();
}

static void mbox_put(uint32_t word, int last) {
    uint32_t guard = 1000000u;
    while ((rom_mailbox_outbound_space_available_read() == 0u) && (guard != 0u)) {
        guard--;
    }
    if (last) {
        rom_mailbox_set_write_separator();
    }
    rom_mailbox_write_data(word);
}

int main(void) {
    uint32_t counter = 1u; /* start at 1 so the host sees nonzero progress */

    rom_mailbox_flush();

    /* Mailbox handshake with the EL2 host: announce READY, then wait for GO. */
    mbox_put(KM_READY_TOKEN, 1);
    while (km_inbound_get() != EL2_GO_TOKEN) {
        /* ignore any unexpected word; wait for the GO token */
    }

    /* Free-run: continuous KM eFuse writes to contend at the mux. Both MMR
     * registers carry the same incrementing payload but distinct owner tags.
     * Write MMR1 (leading) BEFORE MMR0 (trailing): combined with the EL2 read
     * order (MMR0 then MMR1), this guarantees value(MMR1) >= value(MMR0) at the
     * host, so the EL2 p1 >= p0 ordering check cannot false-fail under normal
     * concurrency. */
    for (;;) {
        uint32_t n = counter & KM_PAYLOAD_MASK;
        reg_write32(MMR1_ADDR, KM_TAG1 | n);
        reg_write32(MMR0_ADDR, KM_TAG0 | n);
        counter++;
    }
    return 0;
}
