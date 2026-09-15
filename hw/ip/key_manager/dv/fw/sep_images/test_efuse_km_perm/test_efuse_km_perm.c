/* SPDX-License-Identifier: Apache-2.0 */
/* SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. */

/* Copyright 2026 Tenstorrent Inc. */
/**
 * @file test_efuse_km_perm.c
 * @brief KM CPU eFuse permission-parity agent (Phase 2 of test_efuse_km_axil).
 *
 * Runs as the KM ROM image inside the SEP UVM testbench. Unlike the Phase-1
 * routing test (test_efuse_km_axil), this firmware is a generic, UVM-driven
 * "remote eFuse access agent": the SEP host (UVM) sends a command over the
 * KM<->SEP mailbox, the KM performs the eFuse access through the real path
 * (KM xbar port 8 -> remap -> u_km_efuse_axi_lite_mux -> controller), and the
 * KM returns the observable. The UVM sets lock/secure_tm/LC preconditions, then
 * compares the KM observable against the SEP host (cpu_lsu) doing the same
 * access — proving the KM is subject to the SAME downstream permission policy.
 *
 * Protocol (KM-local addresses are passed by the UVM; the remap is in HW):
 *   Boot:  KM sends a 1-word ready frame [KM_AGENT_ALIVE] (separator).
 *   Loop:  UVM sends a 3-word command frame on the inbound mailbox:
 *            word0 = op   (0=EXIT, 1=READ32, 2=WRITE32)
 *            word1 = addr (KM-local 0x0001_1xxx)
 *            word2 = wdata (WRITE32 only; ignored for READ32)
 *          KM executes and sends a 2-word response (separator on last):
 *            word0 = KM_RESP_MAGIC
 *            word1 = rdata (READ32 result; 0 for WRITE32)
 *
 * The KM reports the RAW read data; the UVM interprets it against the
 * permission context it set up (e.g. 0xbadcab1e == read-lock deny sentinel).
 *
 * Build:  make -f ocah.mk ocah-dv-fw-tests TARGET=key_manager TEST=test_efuse_km_perm
 * Output: dv/fw/build/tests/test_efuse_km_perm/test_efuse_km_perm.rom.parhex
 *
 * NOTE: This file lives in sep_images/ and is built for the SEP UVM testbench,
 * NOT the KM block-level cocotb testbench.  It uses the mailbox protocol and
 * requires a live SEP host to drive the command/response loop.
 */

#include <stdint.h>
#include "rom_mailbox.h"

#define KM_AGENT_ALIVE 0xA11FE5EEu /* boot/ready heartbeat */
#define KM_RESP_MAGIC 0xEF112E59u  /* response frame tag    */

/* Command opcodes (UVM -> KM). */
#define KM_OP_EXIT 0u
#define KM_OP_READ 1u
#define KM_OP_WRITE 2u

static inline void reg_write32(uint32_t addr, uint32_t val) {
    *(volatile uint32_t *)addr = val;
}

static inline uint32_t reg_read32(uint32_t addr) {
    return *(volatile uint32_t *)addr;
}

/* Blocking read of one inbound (SEP->KM) mailbox word. */
static uint32_t mbox_get(void) {
    while (rom_mailbox_inbound_empty() != 0u) {
        /* wait for the SEP host to push a command word */
    }
    return rom_mailbox_read_data();
}

/* Push one outbound (KM->SEP) word, bounded wait for FIFO space. */
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
    rom_mailbox_flush();

    /* Announce the agent is up before any command/eFuse access. */
    mbox_put(KM_AGENT_ALIVE, 1);

    for (;;) {
        uint32_t op = mbox_get();
        uint32_t addr = mbox_get();
        uint32_t wd = mbox_get();
        uint32_t rd = 0u;

        if (op == KM_OP_EXIT) {
            break;
        } else if (op == KM_OP_READ) {
            rd = reg_read32(addr);
        } else if (op == KM_OP_WRITE) {
            reg_write32(addr, wd);
            rd = 0u;
        }

        mbox_put(KM_RESP_MAGIC, 0);
        mbox_put(rd, 1);
    }

    for (;;) {
        /* park */
    }
    return 0;
}
